# app.py
import os
import asyncio
import re
from datetime import datetime
import json
import aiohttp
import streamlit as st
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from threading import Thread
from queue import Queue

# -----------------------------
# Environment variables (safe)
# -----------------------------
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
STRING_SESSION = os.environ.get("STRING_SESSION")
TARGET_CHAT = os.environ.get("TARGET_CHAT")

R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.environ.get("R2_BUCKET")
R2_ENDPOINT = os.environ.get("R2_ENDPOINT")
# -----------------------------

# Validate environment variables
required_vars = [
    "API_ID","API_HASH","STRING_SESSION","TARGET_CHAT",
    "R2_ACCESS_KEY_ID","R2_SECRET_ACCESS_KEY","R2_BUCKET","R2_ENDPOINT"
]
for var in required_vars:
    if not os.environ.get(var):
        raise ValueError(f"Environment variable {var} is missing!")

# -----------------------------
# Telegram client setup
# -----------------------------
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# Queue for live signals to show on Streamlit
signal_queue = Queue()

# Regex to parse signals
SIGNAL_PATTERN = re.compile(
    r"📌Current period ID: (\d+).*?🔔Result:(Win|Lose).*?🔜Next issue.*?📌period ID: (\d+).*?📲Trade: (🟢|🔴)✔️.*?Recommended quantity: x([\d\.]+)",
    re.DOTALL
)

# -----------------------------
# Cloudflare R2 upload
# -----------------------------
async def upload_to_r2(filename: str, data: str):
    url = f"{R2_ENDPOINT}/{filename}"
    async with aiohttp.ClientSession() as session:
        async with session.put(
            url,
            data=data.encode("utf-8"),
            auth=aiohttp.BasicAuth(R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY),
            headers={"Content-Type": "application/json"}
        ) as resp:
            if resp.status in [200, 201]:
                print(f"[R2] Uploaded {filename} successfully")
            else:
                print(f"[R2] Failed to upload {filename}, status={resp.status}")
                text = await resp.text()
                print(f"Response: {text}")

# -----------------------------
# Signal parser
# -----------------------------
async def handle_signal(message_text: str):
    matches = SIGNAL_PATTERN.findall(message_text)
    if not matches:
        return
    signals = []
    for m in matches:
        signal_data = {
            "current_period": m[0],
            "result": m[1],
            "next_period": m[2],
            "trade": m[3],
            "quantity": m[4],
            "timestamp": datetime.utcnow().isoformat()
        }
        signals.append(signal_data)
        # Add to live queue for Streamlit dashboard
        signal_queue.put(signal_data)
    if signals:
        filename = f"signal_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json"
        await upload_to_r2(filename, json.dumps(signals, indent=2))

# -----------------------------
# Telegram listener
# -----------------------------
@client.on(events.NewMessage(chats=TARGET_CHAT))
async def signal_listener(event):
    try:
        await handle_signal(event.raw_text)
    except Exception as e:
        print(f"[Error] {e}")

async def telegram_runner():
    await client.start()
    print("[Telegram] Client started, listening for signals...")
    await client.run_until_disconnected()

# -----------------------------
# Streamlit dashboard
# -----------------------------
st.set_page_config(page_title="Coinryze Signals", layout="wide")
st.title("📊 Coinryze ETH 60s Signal Dashboard")

signal_container = st.container()

def streamlit_loop():
    signals_list = []
    while True:
        while not signal_queue.empty():
            signal = signal_queue.get()
            signals_list.append(signal)
        with signal_container:
            if signals_list:
                st.subheader(f"Latest {len(signals_list)} signals")
                st.table(signals_list[-20:][::-1])  # show last 20 signals
        st.sleep(1)

# -----------------------------
# Run Telegram client in background thread
# -----------------------------
def run_asyncio_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(telegram_runner())

loop = asyncio.new_event_loop()
t = Thread(target=run_asyncio_loop, args=(loop,), daemon=True)
t.start()

# -----------------------------
# Run Streamlit UI
# -----------------------------
streamlit_loop()
