import os, asyncio, threading, random, time
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import streamlit as st
import pandas as pd
import boto3

# =======================
# Environment Variables
# =======================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
TARGET_CHAT = os.getenv("TARGET_CHAT")

R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

# =======================
# Cloudflare R2 (S3-compatible)
# =======================
r2 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
)

# =======================
# Streamlit States
# =======================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "accuracy" not in st.session_state:
    st.session_state.accuracy = []
if "connected" not in st.session_state:
    st.session_state.connected = False

# =======================
# Helpers
# =======================
def verify_signal(text):
    return "WIN" in text.upper() or "🎉" in text

def get_color(sender):
    random.seed(hash(sender))
    hue = random.randint(0, 360)
    return f"hsl({hue},70%,80%)"

def format_message(msg):
    ts = msg["time"].strftime("%H:%M:%S")
    color = get_color(msg["sender"])
    return f"""
    <div style="background:{color};padding:10px;border-radius:10px;
    margin-bottom:6px;max-width:80%;word-wrap:break-word;">
        <b>{msg['sender']}</b>
        <span style="font-size:10px;color:#555">#{msg['id']} • {ts}</span><br>
        {msg['text']}
    </div>
    """

def backup_to_r2(data, filename=None):
    try:
        if not filename:
            filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        r2.put_object(Bucket=R2_BUCKET, Key=filename, Body=data.encode())
    except Exception as e:
        print("⚠️ R2 backup failed:", e)

# =======================
# Telegram Client
# =======================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

@client.on(events.NewMessage(chats=TARGET_CHAT))
async def handler(event):
    text = event.message.message
    verified = verify_signal(text)
    msg = {
        "id": event.id,
        "sender": "CoinRyze Bot",
        "text": text + (" ✅" if verified else " ❌"),
        "time": datetime.now(),
        "verified": verified,
    }
    st.session_state.messages.append(msg)
    st.session_state.accuracy.append(verified)
    backup_to_r2(str(msg), f"{TARGET_CHAT}_{event.id}.txt")

async def start_client():
    await client.start()
    st.session_state.connected = True
    print("✅ Telegram listener connected")
    await client.run_until_disconnected()

def run_client_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_client())

if not st.session_state.connected:
    threading.Thread(target=run_client_thread, daemon=True).start()

# =======================
# Streamlit UI
# =======================
st.set_page_config(page_title="📊 CoinRyze Tracker", layout="wide")
st.title("📊 CoinRyze Signals Dashboard")
st.caption("Live CoinRyze Telegram signals, verification & analytics")

chat_col, stat_col = st.columns([2, 1])

with chat_col:
    st.markdown("### 💬 Live Messages")
    for msg in st.session_state.messages[-50:]:
        st.markdown(format_message(msg), unsafe_allow_html=True)

with stat_col:
    st.markdown("### 📈 Bot Accuracy")
    total = len(st.session_state.accuracy)
    acc = (sum(st.session_state.accuracy) / total * 100) if total else 0
    st.metric("Overall Accuracy", f"{acc:.2f}%", f"{total} signals")
    if total:
        df = pd.DataFrame({"Result": st.session_state.accuracy})
        df["Cumulative %"] = df["Result"].expanding().mean() * 100
        st.line_chart(df["Cumulative %"], use_container_width=True)

st.caption("🔄 Auto-refreshing every 3 seconds")
time.sleep(3)
st.rerun()
