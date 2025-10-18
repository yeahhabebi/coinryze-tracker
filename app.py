import os
import asyncio
import json
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
import boto3
import streamlit as st
import threading
import time

# --- Load environment variables ---
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
TARGET_CHAT = os.getenv("TARGET_CHAT")

R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

# --- Initialize Telegram client ---
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# --- Initialize R2 S3 client ---
s3_client = boto3.client(
    "s3",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    endpoint_url=R2_ENDPOINT
)

# --- Streamlit dashboard ---
st.set_page_config(page_title="Coinryze ETH Signals", layout="wide")
st.title("💹 Coinryze ETH Signals Dashboard")
signal_container = st.empty()
status_container = st.empty()

# In-memory store of latest signals
latest_signals = []

# --- Helper function to parse result (Win/Lose) ---
def parse_result(message: str):
    if "Win" in message:
        return "Win", "🟢"
    elif "Lose" in message:
        return "Lose", "🔴"
    else:
        return "Pending", "🟡"

# --- Telegram event handler ---
@client.on(events.NewMessage(chats=TARGET_CHAT))
async def new_signal_handler(event):
    message = event.message.message
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result_text, icon = parse_result(message)
    latest_signals.append({"time": timestamp, "message": message, "result": result_text, "icon": icon})

    # Keep last 30 messages only
    if len(latest_signals) > 30:
        latest_signals.pop(0)

    # Update Streamlit dashboard
    df_display = "\n\n".join([f"{s['time']} {s['icon']} {s['result']}\n{s['message']}" for s in latest_signals])
    signal_container.text(df_display)

    # Upload latest signals to R2 with retry
    for attempt in range(3):
        try:
            s3_client.put_object(
                Bucket=R2_BUCKET,
                Key="latest_signals.json",
                Body=json.dumps(latest_signals),
                ContentType="application/json"
            )
            break
        except Exception as e:
            print(f"R2 upload error (attempt {attempt+1}):", e)
            await asyncio.sleep(2)

# --- Function to start Telegram client safely ---
async def start_telegram():
    while True:
        try:
            await client.start()
            status_container.text("✅ Telegram connected")
            await client.run_until_disconnected()
        except errors.RPCError as e:
            status_container.text(f"⚠️ Telegram disconnected, retrying... {e}")
            print("Telegram RPC error, reconnecting:", e)
            await asyncio.sleep(5)
        except Exception as e:
            status_container.text(f"⚠️ Telegram error, retrying... {e}")
            print("Telegram unexpected error:", e)
            await asyncio.sleep(5)

# --- Run Telegram client in a background thread for Streamlit ---
def run_telegram_loop():
    asyncio.run(start_telegram())

threading.Thread(target=run_telegram_loop, daemon=True).start()

# --- Streamlit UI loop ---
while True:
    # Refresh dashboard every 3 seconds
    time.sleep(3)
    if latest_signals:
        df_display = "\n\n".join([f"{s['time']} {s['icon']} {s['result']}\n{s['message']}" for s in latest_signals])
        signal_container.text(df_display)
