# coinryze_tracker.py
import os, asyncio, random
from datetime import datetime
import pandas as pd
import streamlit as st
from telethon import TelegramClient, events
from cloudflare import CloudFlare

# ------------------- ENV VARIABLES -------------------
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_KEY_ID = os.getenv("R2_KEY_ID")
R2_SECRET = os.getenv("R2_SECRET")
TELEGRAM_API_IDS = [int(x) for x in os.getenv("TELEGRAM_API_IDS", "").split(",")]
TELEGRAM_API_HASHES = os.getenv("TELEGRAM_API_HASHES", "").split(",")
TELEGRAM_SESSIONS = os.getenv("TELEGRAM_SESSION", "").split(",")

# ------------------- CLOUD R2 UPLOAD -------------------
import boto3
s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_KEY_ID,
    aws_secret_access_key=R2_SECRET
)

def upload_to_r2(file_name, data):
    for attempt in range(3):
        try:
            s3.put_object(Bucket=R2_BUCKET, Key=file_name, Body=data.encode())
            return True
        except Exception as e:
            print(f"R2 upload attempt {attempt+1} failed:", e)
    return False

def download_from_r2(file_name):
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key=file_name)
        return obj['Body'].read().decode()
    except:
        return None

# ------------------- STREAMLIT DASHBOARD -------------------
st.set_page_config(page_title="CoinRyze Tracker", layout="wide")
st.title("📊 Live Telegram Signals Dashboard")

if "signals_df" not in st.session_state:
    st.session_state.signals_df = pd.DataFrame(columns=["timestamp","bot","signal","verified","outcome"])

def update_dashboard(signal_data):
    df = st.session_state.signals_df
    df = pd.concat([df, pd.DataFrame([signal_data], columns=df.columns)], ignore_index=True)
    st.session_state.signals_df = df
    st.dataframe(df.tail(20))
    upload_to_r2("signals.csv", df.to_csv(index=False))

# ------------------- TELEGRAM LISTENER -------------------
async def start_telegram():
    clients = []
    for idx, session in enumerate(TELEGRAM_SESSIONS):
        client = TelegramClient(session, TELEGRAM_API_IDS[idx], TELEGRAM_API_HASHES[idx])
        await client.start()
        clients.append(client)

        @client.on(events.NewMessage)
        async def handler(event, bot_idx=idx):
            msg = event.message.message
            signal_data = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                f"Bot_{bot_idx+1}",
                msg,
                False,
                ""
            ]
            update_dashboard(signal_data)

    await asyncio.gather(*[c.run_until_disconnected() for c in clients])

# ------------------- LOAD EXISTING SIGNALS -------------------
existing_csv = download_from_r2("signals.csv")
if existing_csv:
    st.session_state.signals_df = pd.read_csv(pd.compat.StringIO(existing_csv))

# ------------------- RUN TELEGRAM IN BACKGROUND -------------------
async def main_loop():
    try:
        await start_telegram()
    except Exception as e:
        print("Telegram listener error:", e)

# ------------------- STREAMLIT AUTO REFRESH -------------------
st.write(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
st.button("Force refresh", on_click=lambda: None)

# Run asyncio in background
asyncio.run(main_loop())
