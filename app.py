# app.py
import asyncio
import threading
import random
import time
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import streamlit as st
import boto3  # Cloudflare R2 compatible with S3 API

# =======================
# Telegram Config
# =======================
API_IDS = [11345160]  # support multi-bot later
API_HASHES = ["2912d1786520d56f2b0df8be2f0a8616"]
STRING_SESSIONS = ["YOUR_STRING_SESSION_HERE"]
BOT_NAMES = ["Tisha"]  # name for display

# =======================
# Cloudflare R2 Config
# =======================
R2_KEY_ID = "YOUR_R2_KEY_ID"
R2_SECRET = "YOUR_R2_SECRET"
R2_BUCKET = "coinryze-backup"
R2_ENDPOINT = "https://<account_id>.r2.cloudflarestorage.com"

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

if "thread_started" not in st.session_state:
    st.session_state.thread_started = False

if "colors" not in st.session_state:
    st.session_state.colors = {}

if "accuracy" not in st.session_state:
    st.session_state.accuracy = {}  # {bot_name: [True, False,...]}

# =======================
# Helpers
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
    # Dummy verification: True if contains "WIN", else False
    return "WIN" in text.upper()

def update_accuracy(bot_name, verified):
    if bot_name not in st.session_state.accuracy:
        st.session_state.accuracy[bot_name] = []
    st.session_state.accuracy[bot_name].append(verified)

# =======================
# Telegram Listeners
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

# =======================
# Run clients in background
# =======================
def run_clients():
    for c in clients:
        threading.Thread(target=lambda: c.start().run_until_disconnected(), daemon=True).start()

if not st.session_state.thread_started:
    run_clients()
    st.session_state.thread_started = True

# =======================
# Streamlit UI
# =======================
st.set_page_config(page_title="📊 Coinryze Signals Dashboard", layout="wide")
st.title("📊 Coinryze Signals Dashboard")
st.subheader("Live Telegram signals, verification & analytics")

chat_container = st.container()
leaderboard_container = st.container()
heatmap_container = st.container()

# Auto-refresh loop
while True:
    with chat_container:
        st.markdown("### Live Chat")
        for msg in st.session_state.messages[-50:]:
            st.markdown(format_message(msg), unsafe_allow_html=True)

    with leaderboard_container:
        st.markdown("### Bot Accuracy Leaderboard")
        for bot, results in st.session_state.accuracy.items():
            total = len(results)
            if total > 0:
                acc = sum(results)/total*100
                st.markdown(f"{bot}: {acc:.2f}% ({total} signals)")

    # Dummy heatmap display
    with heatmap_container:
        st.markdown("### Signal Verification Heatmap")
        for bot, results in st.session_state.accuracy.items():
            verified_count = sum(results)
            st.markdown(f"{bot}: " + "🟩"*verified_count + "🟥"*(len(results)-verified_count))

    time.sleep(2)
    st.experimental_rerun()
