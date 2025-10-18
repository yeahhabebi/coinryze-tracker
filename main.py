# coinryze_tracker_replit.py
import os
import asyncio
from datetime import datetime
import pandas as pd
import streamlit as st
from telethon import TelegramClient, events
import boto3
import botocore
import json
import time
import random

# =========================
# Load environment variables
# =========================
R2_BUCKET = os.environ.get("R2_BUCKET")
R2_ENDPOINT = os.environ.get("R2_ENDPOINT")
R2_KEY_ID = os.environ.get("R2_KEY_ID")
R2_SECRET = os.environ.get("R2_SECRET")

TELEGRAM_API_IDS = os.environ.get("TELEGRAM_API_IDS", "").split(",")
TELEGRAM_API_HASHES = os.environ.get("TELEGRAM_API_HASHES", "").split(",")
TELEGRAM_SESSION = os.environ.get("TELEGRAM_SESSION")

# =========================
# Setup Cloudflare R2 client
# =========================
s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_KEY_ID,
    aws_secret_access_key=R2_SECRET,
)

def upload_to_r2(key, data):
    """Upload data to R2 with automatic retry."""
    for attempt in range(5):
        try:
            s3.put_object(Bucket=R2_BUCKET, Key=key, Body=data.encode())
            return True
        except botocore.exceptions.ClientError as e:
            print(f"R2 upload failed (attempt {attempt+1}): {e}")
            time.sleep(2)
    print("R2 upload failed permanently.")
    return False

# =========================
# Initialize Streamlit Dashboard
# =========================
st.set_page_config(page_title="CoinRyze Live Dashboard", layout="wide")
st.title("📊 CoinRyze Live Telegram Signals")

# Initialize empty dataframe
if "signals_df" not in st.session_state:
    st.session_state.signals_df = pd.DataFrame(
        columns=["Time", "Bot", "Signal", "Verified", "Outcome"]
    )

# =========================
# Telegram Listener
# =========================
clients = []

for i, api_id in enumerate(TELEGRAM_API_IDS):
    client = TelegramClient(TELEGRAM_SESSION + f"_{i}", int(api_id), TELEGRAM_API_HASHES[i])
    clients.append(client)

async def start_telegram_listeners():
    for idx, client in enumerate(clients):
        @client.on(events.NewMessage)
        async def handler(event, bot_idx=idx):
            message = event.message.message
            bot_name = f"Bot_{bot_idx+1}"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Simple verification simulation
            verified = random.choice([True, False])
            outcome = random.choice(["Win", "Lose"])
            # Append to DataFrame
            st.session_state.signals_df.loc[len(st.session_state.signals_df)] = [
                timestamp, bot_name, message, verified, outcome
            ]
            # Upload to R2
            df_json = st.session_state.signals_df.to_json()
            upload_to_r2("signals_backup.json", df_json)

        await client.start()
    await asyncio.gather(*(c.run_until_disconnected() for c in clients))

# =========================
# Run Telegram in background
# =========================
if "telegram_task" not in st.session_state:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    st.session_state.telegram_task = loop.create_task(start_telegram_listeners())

# =========================
# Streamlit Dashboard Display
# =========================
def show_dashboard():
    df = st.session_state.signals_df
    if df.empty:
        st.info("No data yet. Waiting for Telegram signals...")
        return

    # Signal Table
    st.subheader("Live Signals Table")
    st.dataframe(df.sort_values("Time", ascending=False), use_container_width=True)

    # Accuracy Leaderboard
    st.subheader("Bot Accuracy Leaderboard")
    leaderboard = df.groupby("Bot").apply(lambda x: (x["Verified"] & (x["Outcome"]=="Win")).sum() / max(1,len(x)) )
    st.bar_chart(leaderboard)

    # Rolling accuracy chart
    st.subheader("Rolling Accuracy Over Time")
    df["VerifiedNum"] = df["Verified"].astype(int)
    df["WinNum"] = (df["Outcome"]=="Win").astype(int)
    df["RollingAccuracy"] = df["VerifiedNum"].rolling(5, min_periods=1).mean() * df["WinNum"].rolling(5, min_periods=1).mean()
    st.line_chart(df[["RollingAccuracy"]])

show_dashboard()
