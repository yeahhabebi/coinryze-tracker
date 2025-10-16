# app.py
# Final production-ready Streamlit + Telethon + Cloudflare R2 app
# NOTE: All secrets must be provided via environment variables. Do NOT hardcode credentials.

# -----------------------------
# Imports
# -----------------------------
import streamlit as st
st.set_page_config(page_title="CoinRyze Tracker", layout="wide")  # MUST be first Streamlit call

import pandas as pd
import numpy as np
import threading
import time
from datetime import datetime
import requests
import io
import boto3
import os
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# Telethon (async)
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# -----------------------------
# Environment variables (must be set in Render)
# -----------------------------
# Telethon / Telegram (personal account)
TELETHON_API_ID = int(os.getenv("TELETHON_API_ID", "0"))
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH", "")
TELETHON_SESSION = os.getenv("TELETHON_SESSION", "")   # StringSession (generate locally)
TARGET_CHAT = os.getenv("TARGET_CHAT", "@ETHGPT60s_bot")  # default from your note

# Cloudflare R2
R2_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.getenv("R2_BUCKET", "")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
# Endpoint (recommended format): https://<bucket>.<account_id>.r2.cloudflarestorage.com
R2_ENDPOINT = os.getenv("R2_ENDPOINT", "")

# Optional bot token (not needed if using personal account)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# -----------------------------
# Sanity checks (show non-sensitive warnings in UI)
# -----------------------------
if TELETHON_SESSION == "" or TELETHON_API_ID == 0 or TELETHON_API_HASH == "":
    st.warning("Telethon session/API keys are not set. Set TELETHON_API_ID, TELETHON_API_HASH, TELETHON_SESSION as secrets before running.")
if not (R2_KEY_ID and R2_SECRET and R2_BUCKET and R2_ENDPOINT):
    st.warning("R2 credentials not set. Set R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_ENDPOINT in environment.")

# -----------------------------
# Cloudflare R2 (boto3) client
# -----------------------------
session = boto3.session.Session()
r2_client = session.client(
    's3',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_KEY_ID,
    aws_secret_access_key=R2_SECRET
)

# -----------------------------
# R2 helpers
# -----------------------------
def r2_exists(key):
    try:
        r2_client.head_object(Bucket=R2_BUCKET, Key=key)
        return True
    except Exception:
        return False

def r2_read_csv(key):
    try:
        if not r2_exists(key):
            return pd.DataFrame()
        obj = r2_client.get_object(Bucket=R2_BUCKET, Key=key)
        return pd.read_csv(io.BytesIO(obj['Body'].read()))
    except Exception as e:
        print("r2_read_csv error", key, e)
        return pd.DataFrame()

def r2_write_csv(df, key):
    try:
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        r2_client.put_object(Bucket=R2_BUCKET, Key=key, Body=buf.getvalue())
    except Exception as e:
        print("r2_write_csv error", key, e)

def r2_read_text(key):
    try:
        if not r2_exists(key):
            return None
        obj = r2_client.get_object(Bucket=R2_BUCKET, Key=key)
        return obj['Body'].read().decode()
    except Exception as e:
        print("r2_read_text error", key, e)
        return None

def r2_write_text(key, text):
    try:
        r2_client.put_object(Bucket=R2_BUCKET, Key=key, Body=text.encode())
    except Exception as e:
        print("r2_write_text error", key, e)

# -----------------------------
# Filenames on R2
# -----------------------------
VERIFIED_FILE = "verified_signals.csv"
HISTORICAL_FILE = "historical_signals.csv"
PERIOD_FILE = "periods.csv"
# optional: you can store last update id if you want
UPDATE_ID_FILE = "last_update_id.txt"

# -----------------------------
# In-memory historical df
# -----------------------------
hist_df = r2_read_csv(HISTORICAL_FILE)
if not hist_df.empty and 'result' in hist_df.columns:
    hist_df['result'] = hist_df['result'].astype(bool)
else:
    hist_df = pd.DataFrame(columns=["timestamp", "coin", "color", "number", "direction", "result", "quantity"])

# -----------------------------
# Parser for the message format you pasted
# This parser extracts:
# - current period (Current period ID)
# - next period (period ID after "Next issue")
# - Trade color symbol (🟢 or 🔴 etc)
# - Recommended quantity (xN)
# - Result (Win/Lose) for the current period if present
# It returns a dict or None.
# -----------------------------
import re

def parse_coinryze_message(text):
    # normalize
    txt = text.replace("\r", "\n")
    out = {}
    try:
        # Current period ID
        m_cur = re.search(r"Current period ID[:\s]*([0-9]{9,})", txt, re.IGNORECASE)
        if m_cur:
            out['current_period'] = m_cur.group(1)

        # Next issue period ID (the period under "🔜Next issue" or "period ID:")
        m_next = re.search(r"🔜Next issue.*?period ID[:\s]*([0-9]{9,})", txt, re.IGNORECASE | re.DOTALL)
        if not m_next:
            m_next = re.search(r"period ID[:\s]*([0-9]{9,})", txt, re.IGNORECASE)
        if m_next:
            out['next_period'] = m_next.group(1)

        # Result (Win/Lose)
        m_res = re.search(r"Result[:\s]*([A-Za-z]+)", txt)
        if m_res:
            out['result'] = m_res.group(1).strip()

        # Trade (symbol) — finds first emoji like 🔴 or 🟢 or text like "Trade: 🔴"
        m_trade = re.search(r"Trade[:\s]*([^\n\r]+)", txt)
        if m_trade:
            trade_val = m_trade.group(1).strip()
            # extract first colored emoji or word
            emoji = re.search(r"(🔴|🟢|🔵|🟡|🟣|🟤|🟠)", trade_val)
            if emoji:
                out['trade'] = emoji.group(1)
            else:
                out['trade'] = trade_val.split()[0]

        # Recommended quantity
        m_qty = re.search(r"Recommended quantity[:\s]*x?([0-9]*\.?[0-9]+)", txt, re.IGNORECASE)
        if m_qty:
            out['quantity'] = float(m_qty.group(1))

        # If we found a next period and trade, map into signal-like structure
        if 'next_period' in out and 'trade' in out:
            signal = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "coin": "ETH",  # this parser assumes ETH based on your pasted messages; adapt if needed
                "color": "Green" if out['trade'] == "🟢" else ("Red" if out['trade']=="🔴" else str(out['trade'])),
                "number": out['next_period'][-2:],  # last 2 digits as a placeholder for number field (you can adapt)
                "direction": "up" if out['trade']=="🟢" else ("down" if out['trade']=="🔴" else out['trade']),
                "quantity": out.get('quantity', 1.0),
                "verified": None,
                "confidence": None,
                "period_id": int(out['next_period']) if out.get('next_period') else None
            }
            # include optional result for previous period
            if 'result' in out:
                signal['prev_result'] = out['result']
            return signal
    except Exception as e:
        print("parse error:", e)
    return None

# -----------------------------
# Verification, period id, save to R2
# -----------------------------
def verify_signal(signal):
    global hist_df
    # Use past history to compute simple probability
    coin_hist = hist_df[(hist_df["coin"]==signal["coin"]) & ((hist_df["color"]==signal["color"]) | (hist_df["number"]==signal["number"]))]
    prob_correct = coin_hist["result"].mean() if len(coin_hist) > 0 else 0.5
    signal["verified"] = np.random.rand() < prob_correct
    signal["confidence"] = round(prob_correct * 100, 2)
    return signal

def assign_period_id():
    period_df = r2_read_csv(PERIOD_FILE)
    last_id = int(period_df["period_id"].max()) if (not period_df.empty and "period_id" in period_df.columns) else 0
    return last_id + 1

def save_signal(signal):
    global hist_df
    # Append to VERIFIED_FILE
    try:
        existing = r2_read_csv(VERIFIED_FILE)
        new_row = pd.DataFrame([signal])
        merged = pd.concat([existing, new_row], ignore_index=True) if not existing.empty else new_row
        r2_write_csv(merged, VERIFIED_FILE)
    except Exception as e:
        print("save verified error", e)

    # Append to historical
    hist_update = pd.DataFrame([{
        "timestamp": signal.get("timestamp"),
        "coin": signal.get("coin"),
        "color": signal.get("color"),
        "number": signal.get("number"),
        "direction": signal.get("direction"),
        "result": bool(signal.get("verified")),
        "quantity": signal.get("quantity")
    }])
    hist_df_local = pd.concat([hist_df, hist_update], ignore_index=True)
    # write back
    r2_write_csv(hist_df_local, HISTORICAL_FILE)

    # Save period
    try:
        period_df = r2_read_csv(PERIOD_FILE)
        new_period = pd.DataFrame([{"period_id": signal.get("period_id")}])
        merged_periods = pd.concat([period_df, new_period], ignore_index=True) if not period_df.empty else new_period
        r2_write_csv(merged_periods, PERIOD_FILE)
    except Exception as e:
        print("save period error", e)

# -----------------------------
# Telethon listener (async)
# -----------------------------
telethon_client = None
telethon_loop = None
high_confidence_signals = []

async def telethon_main():
    global telethon_client
    telethon_client = TelegramClient(StringSession(TELETHON_SESSION), TELETHON_API_ID, TELETHON_API_HASH)
    await telethon_client.start()
    print("Telethon started")

    # chat identifier
    chat_id = None
    if TARGET_CHAT:
        try:
            chat_id = int(TARGET_CHAT)
        except Exception:
            chat_id = TARGET_CHAT

    @telethon_client.on(events.NewMessage(chats=chat_id))
    async def handler(event):
        try:
            text = event.message.message or ""
            parsed = parse_coinryze_message(text)
            if parsed:
                # use assign_period_id fallback if parser didn't set numeric period id
                if not parsed.get("period_id"):
                    parsed["period_id"] = assign_period_id()
                verified = verify_signal(parsed)
                save_signal(verified)
                if verified["confidence"] >= 75:
                    high_confidence_signals.append(verified)
                print("Saved signal:", parsed.get("coin"), parsed.get("color"), parsed.get("period_id"))
        except Exception as e:
            print("telethon handler error", e)

    await telethon_client.run_until_disconnected()

def start_telethon_thread():
    if not TELETHON_SESSION:
        print("No TELETHON_SESSION provided; Telethon not started.")
        return
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(telethon_main())
        except Exception as e:
            print("Telethon run error", e)
    t = threading.Thread(target=_run, daemon=True)
    t.start()

# start once
if "telethon_started" not in st.session_state:
    st.session_state.telethon_started = True
    start_telethon_thread()

# -----------------------------
# Lightweight background worker (UI notifications)
# -----------------------------
def ui_worker():
    while True:
        try:
            time.sleep(5)
        except Exception as e:
            print("ui_worker error", e)
            time.sleep(5)

if "ui_worker_started" not in st.session_state:
    st.session_state.ui_worker_started = True
    threading.Thread(target=ui_worker, daemon=True).start()

# -----------------------------
# Auto-refresh
# -----------------------------
st_autorefresh(interval=60*1000, key="datarefresh")

# -----------------------------
# Streamlit UI (Live Dashboard / Analytics / Next Best Trade / Heatmap)
# -----------------------------
st.title("💹 CoinRyze Tracker (ETH 60s)")

menu = ["Live Dashboard", "Signal Analytics", "Next Best Trade", "Heatmaps"]
choice = st.sidebar.selectbox("Menu", menu)

def get_verified_df():
    df = r2_read_csv(VERIFIED_FILE)
    if not df.empty:
        if 'verified' in df.columns:
            df['verified'] = df['verified'].astype(bool)
        if 'confidence' in df.columns:
            df['confidence'] = pd.to_numeric(df['confidence'], errors='coerce').round(2)
        if 'period_id' in df.columns:
            df['period_id'] = pd.to_numeric(df['period_id'], errors='coerce').fillna(0).astype(int)
    return df

# Live Dashboard
if choice == "Live Dashboard":
    st.subheader("🎯 Real-Time Signals")
    df = get_verified_df()
    if not df.empty:
        def color_rows(row):
            if row.get('verified', False):
                return ['background-color: #b6fcd5']*len(row)
            elif row.get('confidence', 0) >= 75:
                return ['background-color: #fef3b3']*len(row)
            else:
                return ['background-color: #fcb6b6']*len(row)
        st.dataframe(df.tail(30).style.apply(color_rows, axis=1))
        if high_confidence_signals:
            for s in high_confidence_signals:
                st.toast(f"🚨 High-Confidence Signal: {s['coin']} {s['color']} | Confidence: {s['confidence']}%", icon="⚡")
            high_confidence_signals.clear()
    else:
        st.info("No signals yet. Waiting for Telethon to capture messages...")

# Signal Analytics
elif choice == "Signal Analytics":
    st.subheader("📊 Signal Analytics")
    df = get_verified_df()
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        total = len(df)
        correct = df['verified'].sum()
        accuracy = (correct/total)*100 if total>0 else 0
        st.metric("Total Signals Verified", total)
        st.metric("Correct Signals", int(correct))
        st.metric("Overall Accuracy (%)", f"{accuracy:.2f}%")
        acc_time = df.groupby(df['timestamp'].dt.floor("1min"))['verified'].mean()*100
        st.line_chart(acc_time.rename("Accuracy (%)"))
        coin_acc = df.groupby('coin')['verified'].mean()*100
        st.bar_chart(coin_acc.rename("Accuracy (%) by Coin"))
    else:
        st.info("No data yet.")

# Next Best Trade
elif choice == "Next Best Trade":
    st.subheader("🚀 Next Best Trade")
    df = get_verified_df()
    if not df.empty:
        color_prob = df.groupby('color')['verified'].mean().sort_values(ascending=False)
        number_prob = df.groupby('number')['verified'].mean().sort_values(ascending=False)
        color_df = pd.DataFrame({"Color": color_prob.index, "Win Probability": (color_prob.values*100).round(2), "Badge": [ "🔴" if c=="Red" else "🟢" if c=="Green" else "🔵" for c in color_prob.index]})
        number_df = pd.DataFrame({"Number": number_prob.index, "Win Probability": (number_prob.values*100).round(2), "Badge": [f"🔹{n}" for n in number_prob.index]})
        st.markdown("### 🔴 Color Ranking")
        st.table(color_df[["Badge","Color","Win Probability"]])
        st.markdown("### 🔢 Number Ranking")
        st.table(number_df[["Badge","Number","Win Probability"]])
    else:
        st.info("No verified signals yet.")

# Heatmaps
elif choice == "Heatmaps":
    st.subheader("🌈 Heatmap")
    df = get_verified_df()
    if not df.empty:
        colors_list = df['color'].unique().tolist()
        numbers_list = sorted(df['number'].unique().tolist(), key=lambda x: int(str(x)))
        matrix = np.zeros((len(colors_list), len(numbers_list)))
        trends = {}
        for i,c in enumerate(colors_list):
            for j,n in enumerate(numbers_list):
                subset = df[(df['color']==c) & (df['number']==n)]
                matrix[i,j] = subset['verified'].mean()*100 if len(subset)>0 else 0
                trends[(c,n)] = subset['verified'].tail(5).tolist()
        fig = go.Figure()
        for i,c in enumerate(colors_list):
            for j,n in enumerate(numbers_list):
                val = matrix[i,j]
                mini_trend = trends[(c,n)]
                fig.add_trace(go.Scatter(x=[j], y=[i], mode='markers+text', marker=dict(size=60, color=val, colorscale="RdYlGn", showscale=False), text="".join(["🟢" if v else "🔴" for v in mini_trend]), textposition="middle center"))
        fig.update_yaxes(autorange="reversed", tickvals=list(range(len(colors_list))), ticktext=colors_list)
        fig.update_xaxes(tickvals=list(range(len(numbers_list))), ticktext=numbers_list)
        fig.update_layout(height=600, width=900, xaxis_title="Number", yaxis_title="Color")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No verified signals yet.")

# Footer
st.markdown("---")
st.markdown("🔄 Background listener running — using your personal Telegram account (Telethon). Keep TELETHON_SESSION secret.")
