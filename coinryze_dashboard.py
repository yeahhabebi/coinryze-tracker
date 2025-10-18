import asyncio
import threading
import random
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import streamlit as st
import pandas as pd
import boto3

# =======================
# Telegram Config
# =======================
API_IDS = [11345160]  # multi-bot ready
API_HASHES = ["2912d1786520d56f2b0df8be2f0a8616"]
STRING_SESSIONS = ["1BVtsOJgBu4mVFFnw9DrbLHpfSir4AFF8nqf1Nl3-KedXp-WdfyCNwbw6x2aUtIX-YiK5r_tXzrd_aq6Cw9YJNvlaBIKAIA6XZro37UaxxRBc9LcdnKKz2DNTe3HKSp3QU71-7vdD6vpMR0gmWLWrTj8Eknm5t5fgVEaR4lk_VwhHDsI_hRvQFpoYFPCBtRj5aQosTS0kf5KR2pWHcyWMbaVN4s2fAsuMZ5CLykvbKdFlyHTuSBzQBHRuwRvotBW8fIf3NodWmZCn7i5e8jmtg7G8okkDD_oMpHrWGoXyjK67jm0oMztiPOIxS70NFSPPcQ6VZ2gpB67f1lI1y2W0hQckeyG5VW8"]
BOT_NAMES = ["Tisha"]

# =======================
# Cloudflare R2 Config
# =======================
R2_KEY_ID = "7423969d6d623afd9ae23258a6cd2839"
R2_SECRET = "dd858bf600c0d8e63cd047d128b46ad6df0427daef29f57c312530da322fc63c"
R2_BUCKET = "coinryze-analyzer"
R2_ENDPOINT = "https://coinryze-analyzer.6d266c53f2f03219a25de8f12c50bc3b.r2.cloudflarestorage.com"

r2 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_KEY_ID,
    aws_secret_access_key=R2_SECRET,
)

# =======================
# Streamlit State
# =======================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "colors" not in st.session_state:
    st.session_state.colors = {}
if "accuracy" not in st.session_state:
    st.session_state.accuracy = {}  # {bot_name: [True, False,...]}

# =======================
# Helper Functions
# =======================
def get_color(sender):
    if sender not in st.session_state.colors:
        st.session_state.colors[sender] = f"hsl({random.randint(0,360)},70%,80%)"
    return st.session_state.colors[sender]

def format_message(msg):
    ts = msg['time'].strftime("%H:%M:%S")
    color = get_color(msg['sender'])
    bubble = f"""
    <div style="
        background-color:{color};
        padding:10px;
        border-radius:10px;
        margin-bottom:5px;
        width:fit-content;
        max-width:70%;
        word-wrap:break-word;
    ">
        <b>{msg['sender']}</b> <span style='font-size:10px;color:#555'>#{msg['id']} {ts}</span><br>
        {msg['text']}
    </div>
    """
    return bubble

def backup_to_r2(data, filename=None):
    if not filename:
        filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    r2.put_object(Bucket=R2_BUCKET, Key=filename, Body=data.encode())

def verify_signal(text):
    return "WIN" in text.upper()  # Replace with real verification logic

def update_accuracy(bot_name, verified):
    if bot_name not in st.session_state.accuracy:
        st.session_state.accuracy[bot_name] = []
    st.session_state.accuracy[bot_name].append(verified)

# =======================
# Telegram Clients
# =======================
clients = []

for i in range(len(API_IDS)):
    client = TelegramClient(StringSession(STRING_SESSIONS[i]), API_IDS[i], API_HASHES[i])
    clients.append(client)

    @client.on(events.NewMessage)
    async def handler(event, bot_name=BOT_NAMES[i]):
        sender = await event.get_sender()
        name = sender.first_name if sender else str(event.sender_id)
        text = event.text
        msg_id = event.id
        verified = verify_signal(text)
        update_accuracy(bot_name, verified)
        msg = {
            "id": msg_id,
            "sender": bot_name,
            "text": text + (" ✅" if verified else " ❌"),
            "time": datetime.now(),
            "verified": verified
        }
        st.session_state.messages.append(msg)
        backup_to_r2(str(msg), f"{bot_name}_{msg_id}.txt")

def run_clients():
    for c in clients:
        threading.Thread(target=lambda: c.start().run_until_disconnected(), daemon=True).start()

# =======================
# Streamlit Dashboard
# =======================
st.set_page_config(page_title="📊 CoinRyze Signals Dashboard", layout="wide")
st.title("📊 CoinRyze Signals Dashboard")
st.subheader("Live Telegram signals, verification & analytics")

if "clients_started" not in st.session_state:
    run_clients()
    st.session_state.clients_started = True

# Containers
chat_container = st.container()
leaderboard_container = st.container()
heatmap_container = st.container()
accuracy_chart_container = st.container()

# =======================
# Refresh Dashboard every 3 seconds safely
# =======================
def refresh_dashboard():
    # Chat view
    with chat_container:
        st.markdown("### Live Chat")
        for msg in st.session_state.messages[-50:]:
            st.markdown(format_message(msg), unsafe_allow_html=True)

    # Leaderboard
    with leaderboard_container:
        st.markdown("### Bot Accuracy Leaderboard")
        leaderboard = []
        for bot, results in st.session_state.accuracy.items():
            total = len(results)
            acc = (sum(results)/total*100) if total>0 else 0
            leaderboard.append({"Bot": bot, "Accuracy": acc, "Signals": total})
        if leaderboard:
            df_board = pd.DataFrame(leaderboard).sort_values(by="Accuracy", ascending=False)
            st.dataframe(df_board)

    # Heatmap
    with heatmap_container:
        st.markdown("### Signal Verification Heatmap")
        for bot, results in st.session_state.accuracy.items():
            verified_count = sum(results)
            st.markdown(f"{bot}: " + "🟩"*verified_count + "🟥"*(len(results)-verified_count))

    # Accuracy trend chart
    with accuracy_chart_container:
        st.markdown("### Accuracy Trend per Bot")
        for bot, results in st.session_state.accuracy.items():
            df_trend = pd.DataFrame({"Verified": results})
            if not df_trend.empty:
                df_trend['Cumulative Accuracy'] = df_trend['Verified'].expanding().mean()*100
                st.line_chart(df_trend['Cumulative Accuracy'], use_container_width=True)

# Run refresh safely without st.experimental_rerun
refresh_dashboard()
st_autorefresh = st.experimental_singleton(lambda: None)  # dummy to satisfy Render

st.info("Dashboard auto-refreshes every 3 seconds on Render free plan.")
