# main.py - Single-page Replit-ready Bot with R2 + Streamlit Dashboard

import os, asyncio, time, random
import pandas as pd
from telethon import TelegramClient, events
import boto3, botocore
import streamlit as st
from threading import Thread

# =====================
# ENV VARIABLES
# =====================
API_IDS = list(map(int, os.getenv("TELEGRAM_API_IDS","").split(",")))      # comma-separated IDs
API_HASHES = os.getenv("TELEGRAM_API_HASHES","").split(",")               # comma-separated HASHES
SESSIONS = os.getenv("TELEGRAM_SESSIONS","").split(",")                   # comma-separated session names

R2_KEY = os.getenv("R2_KEY_ID")
R2_SECRET = os.getenv("R2_SECRET")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

# =====================
# CLOUD R2 SETUP WITH RETRY
# =====================
session = boto3.session.Session()
r2_client = session.client('s3', region_name='auto',
                           endpoint_url=R2_ENDPOINT,
                           aws_access_key_id=R2_KEY,
                           aws_secret_access_key=R2_SECRET)

def sync_r2(file_path, retries=3, delay=2):
    """Upload file to Cloudflare R2 with retry"""
    filename = os.path.basename(file_path)
    for attempt in range(retries):
        try:
            r2_client.upload_file(file_path, R2_BUCKET, filename)
            print(f"[R2] Uploaded {filename}")
            return True
        except botocore.exceptions.BotoCoreError as e:
            print(f"[R2] Upload failed (attempt {attempt+1}): {e}")
            time.sleep(delay)
    print(f"[R2] Failed to upload {filename} after {retries} attempts")
    return False

# =====================
# TELEGRAM SETUP (MULTI-BOT)
# =====================
clients = []
for i, (api_id, api_hash, session_name) in enumerate(zip(API_IDS, API_HASHES, SESSIONS)):
    client = TelegramClient(session_name, api_id, api_hash)
    clients.append(client)

# =====================
# DATA STORAGE
# =====================
CSV_FILE = "signals.csv"
if not os.path.exists(CSV_FILE):
    pd.DataFrame(columns=["bot","message","verified","next_id"]).to_csv(CSV_FILE, index=False)

def log_signal(bot_name, message, verified=False, next_id=None):
    df = pd.read_csv(CSV_FILE)
    df = pd.concat([df, pd.DataFrame({"bot":[bot_name],"message":[message],
                                     "verified":[verified],"next_id":[next_id]})], ignore_index=True)
    df.to_csv(CSV_FILE, index=False)
    sync_r2(CSV_FILE)

# =====================
# TELEGRAM HANDLER
# =====================
async def start_client(client, bot_name):
    @client.on(events.NewMessage)
    async def handler(event):
        msg = event.message.message
        print(f"[{bot_name}] New message: {msg}")
        # fake verification logic for demo
        verified = random.choice([True, False])
        next_id = random.randint(1000,9999)
        log_signal(bot_name, msg, verified, next_id)
    await client.start()
    print(f"[{bot_name}] Telegram client started")
    await client.run_until_disconnected()

# =====================
# STREAMLIT DASHBOARD
# =====================
def run_dashboard():
    st.set_page_config(page_title="Live Bot Dashboard", layout="wide")
    st.title("📊 Live Telegram Signals Dashboard")
    while True:
        if os.path.exists(CSV_FILE):
            df = pd.read_csv(CSV_FILE)
            # Rolling accuracy per bot
            accuracy = df.groupby("bot")["verified"].mean().reset_index()
            st.subheader("✅ Rolling Accuracy")
            st.bar_chart(accuracy.set_index("bot"))

            # Leaderboard
            leaderboard = df.groupby("bot").size().sort_values(ascending=False).reset_index(name="signals")
            st.subheader("🏆 Bot Leaderboard")
            st.table(leaderboard)

            # Heatmap per bot
            for bot in df["bot"].unique():
                bot_df = df[df["bot"]==bot]
                st.subheader(f"🎨 Heatmap - {bot}")
                heatmap = pd.crosstab(bot_df['verified'], bot_df['next_id'])
                st.dataframe(heatmap)
        time.sleep(5)  # update every 5 seconds

# =====================
# START EVERYTHING
# =====================
# Start Streamlit dashboard in separate thread
Thread(target=lambda: os.system("streamlit run main.py --server.port 8501 --server.headless true")).start()

# Start all Telegram clients
loop = asyncio.get_event_loop()
tasks = [start_client(c, f"Bot-{i+1}") for i, c in enumerate(clients)]
loop.run_until_complete(asyncio.gather(*tasks))
