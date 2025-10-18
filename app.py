import os, asyncio, threading, io
from datetime import datetime
import pandas as pd
import streamlit as st
from telethon import TelegramClient, events
import boto3

# --- Streamlit page setup
st.set_page_config(page_title="CoinRyze Live Tracker", layout="wide")
st.title("💹 CoinRyze Live Dashboard — Multi-Bot Signal Tracker")

# --- Environment variables
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION = os.getenv("TELEGRAM_SESSION", "")
R2_KEY = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.getenv("R2_BUCKET", "")
R2_ENDPOINT = os.getenv("R2_ENDPOINT", "")
TARGET_CHATS = ["@ETHGPT60s_bot", "@ETHGPT260s_bot"]

# --- Global DataFrame to hold signals
if "signals" not in st.session_state:
    st.session_state.signals = pd.DataFrame(
        columns=["time", "bot", "period", "trade", "result", "confidence"]
    )

# --- Cloudflare R2 client
def upload_to_r2(df):
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_KEY,
            aws_secret_access_key=R2_SECRET,
        )
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        s3.put_object(Bucket=R2_BUCKET, Key="signals.csv", Body=csv_buffer.getvalue())
        print("✅ Synced to Cloudflare R2")
    except Exception as e:
        print("R2 Sync Error:", e)

# --- Telegram listener logic
async def start_telegram_listener():
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

    @client.on(events.NewMessage(chats=TARGET_CHATS))
    async def handler(event):
        msg = event.message.message
        bot = event.chat.username or "Unknown"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # crude parsing for trade/result lines
        trade = "🟢" if "🟢" in msg else ("🔴" if "🔴" in msg else "❔")
        result = "Win" if "Win" in msg else ("Lose" if "Lose" in msg else "Pending")
        confidence = msg.count("🟢") + msg.count("🔴")

        st.session_state.signals.loc[len(st.session_state.signals)] = [
            timestamp,
            bot,
            f"{hash(msg)%100000}",
            trade,
            result,
            confidence,
        ]
        upload_to_r2(st.session_state.signals)

    await client.start()
    print("📡 Telegram listener started...")
    await client.run_until_disconnected()

def run_async_loop():
    asyncio.run(start_telegram_listener())

# --- Start Telegram listener thread once
if "listener_started" not in st.session_state:
    threading.Thread(target=run_async_loop, daemon=True).start()
    st.session_state.listener_started = True

# --- Dashboard UI
df = st.session_state.signals.copy()
if len(df):
    st.dataframe(df.tail(20), use_container_width=True)

    # Summary
    total = len(df)
    wins = len(df[df["result"] == "Win"])
    accuracy = round((wins / total) * 100, 1) if total else 0
    st.metric("📈 Accuracy", f"{accuracy}%")
    st.metric("🏆 Total Trades", total)
else:
    st.info("Waiting for Telegram signals...")

st.caption("© 2025 CoinRyze Analyzer — Live R2-Synced Telegram Dashboard")
