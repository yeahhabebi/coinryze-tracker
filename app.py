import os
import time
import threading
import pandas as pd
import streamlit as st
import numpy as np
from CloudFlare import CloudFlare
from pyrogram import Client, filters
import requests
import plotly.express as px

# --- ENV VARIABLES ---
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_KEY_ID = os.getenv("R2_KEY_ID")
R2_SECRET = os.getenv("R2_SECRET")
TELEGRAM_API_IDS = os.getenv("TELEGRAM_API_IDS").split(",")
TELEGRAM_API_HASHES = os.getenv("TELEGRAM_API_HASHES").split(",")
TELEGRAM_SESSIONS = os.getenv("TELEGRAM_SESSION").split(",")

# --- GLOBAL DATA ---
signals_df = pd.DataFrame(columns=["bot","signal","verified","time"])
lock = threading.Lock()

# --- CLOUD FLARE R2 SYNC ---
cf = CloudFlare(token=R2_SECRET)

def upload_r2_file(filename, retries=3):
    for attempt in range(retries):
        try:
            with open(filename, "rb") as f:
                cf.r2.put_object(R2_BUCKET, filename, data=f.read())
            return True
        except Exception as e:
            print(f"R2 upload failed attempt {attempt+1}: {e}")
            time.sleep(2)
    print(f"Failed to upload {filename} after {retries} attempts.")
    return False

# --- TELEGRAM LISTENER ---
def start_bot(session_name, api_id, api_hash):
    app = Client(session_name, api_id=int(api_id), api_hash=api_hash)

    @app.on_message(filters.private)
    def handle_signal(client, message):
        signal = message.text
        bot_name = session_name
        verified = False  # placeholder verification logic
        with lock:
            global signals_df
            signals_df = pd.concat([signals_df, pd.DataFrame([{
                "bot": bot_name,
                "signal": signal,
                "verified": verified,
                "time": pd.Timestamp.now()
            }])], ignore_index=True)
            # save backup
            signals_df.to_csv("signals_backup.csv", index=False)
            upload_r2_file("signals_backup.csv")

    app.run()

# Start all bots in separate threads
for i, session in enumerate(TELEGRAM_SESSIONS):
    t = threading.Thread(target=start_bot, args=(session, TELEGRAM_API_IDS[i], TELEGRAM_API_HASHES[i]))
    t.start()

# --- STREAMLIT DASHBOARD ---
st.set_page_config(page_title="CoinRyze Live Dashboard", layout="wide")
st.title("📊 CoinRyze Live Telegram Signals Dashboard")

last_update = st.empty()
data_area = st.empty()

def dashboard_loop():
    while True:
        with lock:
            df = signals_df.copy()
        if df.empty:
            data_area.text("No data yet. Waiting for signals...")
        else:
            # Show leaderboard
            leaderboard = df.groupby("bot")["verified"].mean().sort_values(ascending=False).reset_index()
            leaderboard.columns = ["Bot", "Accuracy"]
            st.subheader("Bot Accuracy Leaderboard")
            st.table(leaderboard)

            # Show heatmap of signals per bot
            heatmap_data = df.pivot_table(index="bot", columns="signal", aggfunc="size", fill_value=0)
            fig = px.imshow(heatmap_data, text_auto=True, aspect="auto", title="Signals Heatmap per Bot")
            st.plotly_chart(fig, use_container_width=True)

        last_update.text(f"Last updated: {pd.Timestamp.now()}")
        time.sleep(5)

# Start dashboard loop in background
threading.Thread(target=dashboard_loop, daemon=True).start()
