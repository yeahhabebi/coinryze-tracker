# coinryze_live_all_in_one.py
# Single-file Streamlit dashboard + Telegram listener + Cloudflare R2 + alerts + leaderboard + high-confidence filter
# Run: streamlit run coinryze_live_all_in_one.py

import os
import re
import time
import threading
import datetime
from io import BytesIO

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Telethon & boto3
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import boto3

st.set_page_config(page_title="CoinRyze All-in-One Live Dashboard", layout="wide")
st.title("🎨 CoinRyze — All-in-One Live Dashboard (Multi-bot, Verified, Alerts)")

# ------------------------
# CONFIG (defaults + env override)
# ------------------------
# -- TELEGRAM --
# You gave these earlier; kept here as defaults but it's safer to set env vars on Render
DEFAULT_API_ID = "11345160"
DEFAULT_API_HASH = "2912d1786520d56f2b0df8be2f0a8616"
DEFAULT_SESSION = ""  # optional StringSession if you have it
DEFAULT_BOT_TOKEN = "8320822050:AAGk4YmnvA5sqIWK5RcYodiCe9PNLp8bNUA"

API_ID = int(os.environ.get("API_ID", DEFAULT_API_ID))
API_HASH = os.environ.get("API_HASH", DEFAULT_API_HASH)
TELETHON_SESSION = os.environ.get("TELETHON_SESSION", DEFAULT_SESSION)  # StringSession (if you prefer)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", DEFAULT_BOT_TOKEN)

# Bot list to monitor (add or remove)
BOT_LIST = os.environ.get("BOT_LIST", "@ETHGPT60s_bot,@CRAgency_bot,@ETHGPT260s_bot").split(",")

# -- CLOUDFLARE R2 (S3-compatible) --
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "7423969d6d623afd9ae23258a6cd2839")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "dd858bf600c0d8e63cd047d128b46ad6df0427daef29f57c312530da322fc63c")
R2_BUCKET = os.environ.get("R2_BUCKET", "coinryze-analyzer")
R2_ENDPOINT = os.environ.get("R2_ENDPOINT", "https://coinryze-analyzer.6d266c53f2f03219a25de8f12c50bc3b.r2.cloudflarestorage.com")

# Behavior settings
REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", 4))
CONFIDENCE_DEFAULT = int(os.environ.get("CONFIDENCE_DEFAULT", 50))  # percent threshold for high-confidence
QUANTITY_CONFIDENCE_WEIGHT = float(os.environ.get("QUANTITY_CONFIDENCE_WEIGHT", 1.0))

# ------------------------
# Storage: in-memory (also sync to R2)
# ------------------------
messages = []   # list of dicts for all parsed signals (historical in-memory)
alerts = []     # queue of new alerts to flash (dicts)
lock = threading.Lock()

# ------------------------
# Helper: Parsing & scoring
# ------------------------
def parse_signal(text, bot_name):
    """Extract standard fields from CoinRyze message text (robust to formatting)."""
    try:
        # normalize
        msg = text.replace("\xa0", " ")
        period = None
        next_period = None
        trade = None
        quantity = 0.0
        result = None
        prediction = None

        m = re.search(r"period\s*ID[: ]\s*([0-9]+)", msg, re.IGNORECASE)
        if m:
            period = int(m.group(1))

        m2 = re.search(r"Next issue\s*.*period\s*ID[: ]\s*([0-9]+)", msg, re.IGNORECASE)
        if m2:
            next_period = int(m2.group(1))

        m3 = re.search(r"Trade[: ]\s*([🔴🟢✔️❌A-Za-z0-9]+)", msg)
        if m3:
            trade = m3.group(1).strip()

        m4 = re.search(r"Recommended quantity[: ]\s*x?([\d.]+)", msg, re.IGNORECASE)
        if m4:
            quantity = float(m4.group(1))

        m5 = re.search(r"Result[: ]\s*(Win🎉|Lose💔|Win|Lose)", msg, re.IGNORECASE)
        if m5:
            result = m5.group(1)

        m6 = re.search(r"Prediction model .*: ([🔴🟢\s]+)", msg)
        if m6:
            prediction = m6.group(1).strip()

        # fallback: try to infer trade from "🔴" or "🟢" in message lines
        if not trade:
            m7 = re.search(r"([🔴🟢])", msg)
            if m7:
                trade = m7.group(1)

        if period is None:
            return None  # ignore messages without a period ID

        timestamp = datetime.datetime.utcnow()
        parsed = {
            "bot": bot_name,
            "period": period,
            "next_period": next_period,
            "trade": trade,
            "quantity": quantity,
            "result": result,
            "prediction": prediction,
            "timestamp": timestamp
        }
        # scoring: compute a confidence score (0-100)
        parsed["confidence"] = score_confidence(parsed)
        return parsed
    except Exception as e:
        print("parse error:", e)
        return None

def score_confidence(parsed):
    """Heuristic scoring of confidence using prediction string and quantity."""
    pred = parsed.get("prediction") or ""
    q = float(parsed.get("quantity") or 0.0)
    # count emojis if present
    greens = pred.count("🟢")
    reds = pred.count("🔴")
    total = greens + reds
    emoji_score = 0
    if total > 0:
        emoji_score = abs(greens - reds) / total  # 0..1
    # quantity weight: larger recommended quantity implies more confidence
    q_score = min(q / 10.0, 1.0) * QUANTITY_CONFIDENCE_WEIGHT  # normalize assuming x10 is max strong
    # final combine (weights chosen to favor clear emoji patterns)
    combined = (emoji_score * 0.75) + (q_score * 0.25)
    return int(round(combined * 100))

# ------------------------
# Cloudflare R2 sync (synchronous)
# ------------------------
def sync_to_r2_sync():
    """Write current messages list to R2 as CSV (non-blocking minimal)."""
    try:
        df = pd.DataFrame(messages)
        if df.empty:
            return
        buf = BytesIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        s3 = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY
        )
        s3.put_object(Bucket=R2_BUCKET, Key="signals.csv", Body=buf.getvalue())
    except Exception as e:
        print("R2 sync error:", e)

# ------------------------
# Telegram listener setup
# ------------------------
# We support starting either as a Bot (BOT_TOKEN) or as a user via StringSession
use_bot_token = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN.strip())
client = None

if use_bot_token:
    # Telethon can also start with bot token via TelegramClient().start(bot_token=...)
    client = TelegramClient(StringSession(TELETHON_SESSION or ""), API_ID, API_HASH)
else:
    client = TelegramClient(StringSession(TELETHON_SESSION or ""), API_ID, API_HASH)

@client.on(events.NewMessage(chats=BOT_LIST))
async def _on_new_message(event):
    text = event.raw_text or ""
    # event.chat may be None for bot/channel; use provided target username
    bot_name = getattr(event.chat, "username", None) or (event.sender.username if hasattr(event, "sender") and event.sender else None) or "unknown"
    parsed = parse_signal(text, bot_name)
    if parsed:
        with lock:
            messages.append(parsed)
            alerts.append(parsed)
        # sync in a background thread to avoid blocking Telethon event loop
        threading.Thread(target=sync_to_r2_sync, daemon=True).start()

def start_telegram_listener():
    loop = None
    try:
        loop = __import__("asyncio").new_event_loop()
        __import__("asyncio").set_event_loop(loop)
        # start either with a bot token (if provided) or normal start
        if use_bot_token:
            loop.run_until_complete(client.start(bot_token=TELEGRAM_BOT_TOKEN))
        else:
            loop.run_until_complete(client.start())
        print("Telegram listener started")
        loop.run_forever()
    except Exception as e:
        print("Telegram start error:", e)

# start in background thread
t = threading.Thread(target=start_telegram_listener, daemon=True)
t.start()

# ------------------------
# UI: controls & containers
# ------------------------
st.sidebar.header("Display & Filter Controls")
confidence_threshold = st.sidebar.slider("High-confidence threshold (%)", min_value=10, max_value=100, value=CONFIDENCE_DEFAULT, step=5)
only_high_confidence = st.sidebar.checkbox("Show only high-confidence alerts on flashing banner", value=True)
flash_only_top_signals = st.sidebar.checkbox("Flash ONLY top signals (flash banner limited to high-confidence)", value=True)

rolling_window = st.sidebar.number_input("Rolling window size (trades)", min_value=5, max_value=200, value=20)

# Bot filter multiselect
selected_bots = st.sidebar.multiselect("Bots to display", options=BOT_LIST, default=BOT_LIST)

# Color map for bots
bot_colors = {
    "@ETHGPT60s_bot": "#FFDDC1",
    "@CRAgency_bot": "#D1F2EB",
    "@ETHGPT260s_bot": "#FADBD8"
}

# Audio & icon
ALERT_SOUND_HTML = """
<audio autoplay>
  <source src="https://www.soundjay.com/button/beep-07.wav" type="audio/wav">
</audio>
"""

# Dashboard containers
leaderboard_container = st.container()
controls_container = st.container()
alerts_container = st.container()
bots_container = st.container()
charts_container = st.container()
heatmap_container = st.container()
verified_container = st.container()

# ------------------------
# Dashboard computation & display
# ------------------------
def compute_leaderboard(df):
    rows = []
    for bot in BOT_LIST:
        dfb = df[df['bot'] == bot]
        total = len(dfb)
        wins = int(dfb['result'].value_counts().get('Win🎉', 0))
        losses = int(dfb['result'].value_counts().get('Lose💔', 0))
        win_rate = round((wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0, 2)
        cum_profit = float((dfb.apply(lambda r: r['quantity'] if str(r['result']).lower().startswith("win") else -r['quantity'], axis=1)).sum()) if not dfb.empty else 0.0
        avg_conf = int(dfb['confidence'].mean()) if not dfb.empty else 0
        rows.append({
            "Bot": bot,
            "Total": total,
            "Wins": wins,
            "Losses": losses,
            "Win Rate %": win_rate,
            "Cum Profit": round(cum_profit, 4),
            "Avg Confidence %": avg_conf
        })
    if rows:
        ldf = pd.DataFrame(rows).sort_values(["Win Rate %", "Cum Profit"], ascending=[False, False]).reset_index(drop=True)
        return ldf
    return pd.DataFrame(rows)

def draw_heatmap(df_bot):
    if df_bot.empty or 'prediction' not in df_bot.columns or 'trade' not in df_bot.columns:
        st.write("No heatmap data")
        return
    data = pd.crosstab(df_bot['prediction'], df_bot['trade'])
    fig, ax = plt.subplots(figsize=(6,3))
    sns.heatmap(data, annot=True, fmt="d", cmap="RdYlGn", ax=ax)
    st.pyplot(fig)

# Main refresh loop (Streamlit-friendly placeholder)
placeholder = st.empty()

def render_dashboard():
    with placeholder:
        # copy snapshot under lock
        with lock:
            snapshot = pd.DataFrame(messages)

        # Top: Leaderboard
        with leaderboard_container:
            st.subheader("🏆 Bot Accuracy Leaderboard")
            if not snapshot.empty:
                lb = compute_leaderboard(snapshot)
                st.dataframe(lb)
            else:
                st.info("No signals yet — waiting for Telegram messages...")

        # Alerts flashing banner (high-confidence)
        with alerts_container:
            st.subheader("🚨 Live Alerts (flashing high-confidence)")
            flashed = False
            # check alerts queue (consume safely)
            with lock:
                local_alerts = list(alerts)  # copy
            # iterate recent alerts newest-first
            for a in local_alerts[::-1]:
                # only for selected bots
                if a['bot'] not in selected_bots:
                    continue
                is_high = (a.get("confidence", 0) >= confidence_threshold)
                if only_high_confidence and not is_high:
                    continue
                if flash_only_top_signals and not is_high:
                    continue
                # show only most recent one prominently
                # create a flashing banner using CSS animation
                trade_symbol = a.get("trade", "❓")
                botname = a.get("bot")
                period = a.get("period")
                confidence = a.get("confidence", 0)
                color = bot_colors.get(botname, "#FFF")
                st.markdown(f"""
                <div style="padding:12px;border-radius:8px;margin-bottom:10px;background:{color};">
                  <h2 style="margin:0;padding:0;">
                    🔔 <span style="color:#B22222">ALERT</span> — <strong>{trade_symbol}</strong>  | Bot: <strong>{botname}</strong> | Period: {period} | Confidence: {confidence}%
                  </h2>
                </div>
                """, unsafe_allow_html=True)
                # sound + desktop notification for the top-most matching alert
                st.markdown(ALERT_SOUND_HTML, unsafe_allow_html=True)
                st.markdown(f"""
                <script>
                if (Notification && Notification.permission !== "granted") {{
                  Notification.requestPermission();
                }}
                if (Notification && Notification.permission === "granted") {{
                  new Notification("CoinRyze: {botname}", {{
                    body: "{trade_symbol} — Period {period} — Confidence {confidence}%",
                    icon: "https://upload.wikimedia.org/wikipedia/commons/6/6b/Bitcoin-icon.png"
                  }});
                }}
                </script>
                """, unsafe_allow_html=True)
                flashed = True
                break
            if not flashed:
                st.write("No recent high-confidence alerts passing your filters.")

        # Per-bot sections
        with bots_container:
            st.subheader("🤖 Per-Bot Signals & Verified Outcomes (color-coded)")
            for bot in BOT_LIST:
                if bot not in selected_bots:
                    continue
                df_bot = snapshot[snapshot['bot'] == bot] if not snapshot.empty else pd.DataFrame()
                color = bot_colors.get(bot, "#FFF")
                st.markdown(f"<div style='background:{color};padding:8px;border-radius:6px;margin-top:8px'>", unsafe_allow_html=True)
                st.markdown(f"### {bot}")
                if df_bot.empty:
                    st.write("No signals from this bot yet.")
                    st.markdown("</div>", unsafe_allow_html=True)
                    continue

                # Show latest 20 signals for this bot with verification columns
                display_df = df_bot.sort_values("timestamp").tail(40).copy()
                # Normalize result strings for easier flags
                display_df['outcome_flag'] = display_df['result'].apply(lambda r: 1 if str(r).lower().startswith("win") else (0 if pd.notna(r) else None))
                st.dataframe(display_df[['timestamp','period','next_period','trade','quantity','prediction','confidence','result']].tail(20))

                # small per-bot stats
                wins = int(display_df['result'].value_counts().get('Win🎉', 0))
                losses = int(display_df['result'].value_counts().get('Lose💔', 0))
                win_rate = round((wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0, 2)
                st.markdown(f"**Total:** {len(display_df)}  •  **Wins:** {wins}  •  **Losses:** {losses}  •  **Win Rate:** {win_rate}%  •  **Avg Confidence:** {int(display_df['confidence'].mean()) if not display_df.empty else 0}%")

                st.markdown("</div>", unsafe_allow_html=True)

        # Charts: combined rolling & profit
        with charts_container:
            st.subheader("📊 Rolling Win Rate & Cumulative Profit (selected bots)")
            if not snapshot.empty:
                win_df = {}
                profit_df = {}
                for bot in BOT_LIST:
                    if bot not in selected_bots:
                        continue
                    dfb = snapshot[snapshot['bot'] == bot].sort_values("timestamp")
                    if dfb.empty:
                        continue
                    dfb['win_flag'] = dfb['result'].apply(lambda x: 1 if str(x).lower().startswith("win") else 0)
                    win_df[bot] = dfb['win_flag'].rolling(rolling_window, min_periods=1).mean().reset_index(drop=True)
                    profit_df[bot] = (dfb['win_flag'] * dfb['quantity'] - (1 - dfb['win_flag']) * dfb['quantity']).cumsum().reset_index(drop=True)
                if win_df:
                    st.line_chart(pd.DataFrame(win_df))
                if profit_df:
                    st.line_chart(pd.DataFrame(profit_df))
            else:
                st.write("No data yet for charts.")

        # Heatmaps
        with heatmap_container:
            st.subheader("🌡️ Trade vs Prediction Heatmaps (per bot)")
            for bot in BOT_LIST:
                if bot not in selected_bots:
                    continue
                dfb = snapshot[snapshot['bot'] == bot] if not snapshot.empty else pd.DataFrame()
                if dfb.empty:
                    continue
                st.markdown(f"**{bot}**")
                draw_heatmap(dfb)

        # Verified outcomes table
        with verified_container:
            st.subheader("✅ Verified Outcomes / Next Periods (recent)")
            if not snapshot.empty:
                vdf = snapshot[['bot','period','next_period','trade','prediction','result','confidence','timestamp']].sort_values('timestamp', ascending=False).head(80)
                st.dataframe(vdf)
            else:
                st.write("No verified results yet.")

# run initial rendering then loop
while True:
    render_dashboard()
    time.sleep(REFRESH_SECONDS)
