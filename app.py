import os
import time
import threading
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import boto3
from pyrogram import Client, filters

# ===========================
# Environment Variables
# ===========================
TELEGRAM_API_IDS = os.getenv("TELEGRAM_API_IDS", "").split(",")
TELEGRAM_API_HASHES = os.getenv("TELEGRAM_API_HASHES", "").split(",")
TELEGRAM_SESSIONS = os.getenv("TELEGRAM_SESSION", "").split(",")
R2_KEY_ID = os.getenv("R2_KEY_ID")
R2_SECRET = os.getenv("R2_SECRET")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

# ===========================
# Signals storage
# ===========================
signals_df = pd.DataFrame(columns=["bot", "signal", "verified", "timestamp"])

# ===========================
# Telegram Listener
# ===========================
def start_telegram_listener(api_id, api_hash, session_name):
    app = Client(session_name, api_id=int(api_id), api_hash=api_hash)

    @app.on_message(filters.private)
    def handle_signal(client, message):
        global signals_df
        signals_df = pd.concat([
            signals_df,
            pd.DataFrame([{
                "bot": session_name,
                "signal": message.text,
                "verified": False,
                "timestamp": pd.Timestamp.now()
            }])
        ], ignore_index=True)

    app.run()

# ===========================
# R2 Upload with retries (S3 compatible)
# ===========================
def upload_to_r2(filename, data, retries=3):
    session = boto3.session.Session()
    s3 = session.client(
        's3',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_KEY_ID,
        aws_secret_access_key=R2_SECRET,
    )
    for attempt in range(retries):
        try:
            s3.put_object(Bucket=R2_BUCKET, Key=filename, Body=data.encode("utf-8"))
            return True
        except Exception as e:
            print(f"R2 upload failed, retry {attempt+1}: {e}")
            time.sleep(2)
    print("Failed to upload to R2 after retries")
    return False

def backup_signals():
    while True:
        if not signals_df.empty:
            csv_data = signals_df.to_csv(index=False)
            upload_to_r2("signals_backup.csv", csv_data)
        time.sleep(60)

# ===========================
# Start Telegram Threads
# ===========================
for api_id, api_hash, session in zip(TELEGRAM_API_IDS, TELEGRAM_API_HASHES, TELEGRAM_SESSIONS):
    threading.Thread(target=start_telegram_listener, args=(api_id, api_hash, session), daemon=True).start()

threading.Thread(target=backup_signals, daemon=True).start()

# ===========================
# Streamlit Dashboard
# ===========================
st.set_page_config(page_title="CoinRyze Tracker", layout="wide")
st.title("📊 Live Telegram Signals Dashboard")

placeholder = st.empty()

while True:
    df_copy = signals_df.copy()
    if df_copy.empty:
        placeholder.text("No data yet. Waiting for signals...")
    else:
        df_copy["verified_numeric"] = df_copy["verified"].astype(int)
        acc = df_copy.groupby("bot")["verified_numeric"].mean().reset_index()
        acc.columns = ["Bot", "Rolling Accuracy"]
        fig = px.bar(acc, x="Bot", y="Rolling Accuracy", range_y=[0,1], text_auto=True)
        placeholder.plotly_chart(fig, use_container_width=True)

        heatmap_data = pd.crosstab(df_copy["bot"], df_copy["signal"])
        fig2 = px.imshow(heatmap_data, text_auto=True, aspect="auto")
        st.plotly_chart(fig2, use_container_width=True)

    time.sleep(5)
