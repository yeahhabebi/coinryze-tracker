import os
import time
import pandas as pd
import streamlit as st
import threading
import requests
from pyrogram import Client, filters
from CloudFlare import CloudFlare
from io import BytesIO

# ============ Environment Variables ============
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_KEY_ID = os.getenv("R2_KEY_ID")
R2_SECRET = os.getenv("R2_SECRET")
TELEGRAM_API_IDS = os.getenv("TELEGRAM_API_IDS").split(",")       # comma-separated
TELEGRAM_API_HASHES = os.getenv("TELEGRAM_API_HASHES").split(",") # comma-separated
TELEGRAM_SESSIONS = os.getenv("TELEGRAM_SESSION").split(",")      # comma-separated

# ============ Cloudflare R2 Client ============
cf_session = CloudFlare(email="", token=R2_KEY_ID)

def upload_to_r2(filename, df):
    buffer = BytesIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    for attempt in range(3):
        try:
            cf_session.zones.r2.put(bucket_name=R2_BUCKET, key=filename, data=buffer)
            break
        except Exception as e:
            time.sleep(2)
            if attempt == 2:
                print(f"Failed to upload {filename}: {e}")

# ============ Signal Storage ============
try:
    df_signals = pd.read_csv("signals.csv")
except:
    df_signals = pd.DataFrame(columns=["bot", "signal", "outcome", "timestamp"])

# ============ Telegram Listener ============
apps = []
for i, session in enumerate(TELEGRAM_SESSIONS):
    app = Client(session_name=session, api_id=int(TELEGRAM_API_IDS[i]), api_hash=TELEGRAM_API_HASHES[i])
    apps.append(app)

def start_listener(app):
    @app.on_message(filters.channel)
    def listener(client, message):
        global df_signals
        bot_name = client.me.username
        signal_text = message.text
        timestamp = pd.Timestamp.now()
        # Dummy verification logic
        outcome = "pending"
        df_signals = pd.concat([df_signals, pd.DataFrame([{"bot": bot_name, "signal": signal_text, "outcome": outcome, "timestamp": timestamp}])], ignore_index=True)
        df_signals.to_csv("signals.csv", index=False)
        upload_to_r2("signals_backup.csv", df_signals)

    app.run()

# Run all Telegram listeners in threads
for app in apps:
    threading.Thread(target=start_listener, args=(app,), daemon=True).start()

# ============ Streamlit Dashboard ============
st.set_page_config(page_title="CoinRyze Live Dashboard", layout="wide")
st.title("📊 CoinRyze Telegram Signals Dashboard")

if df_signals.empty:
    st.warning("No data yet. Waiting for signals...")
else:
    st.write(f"Last updated: {pd.Timestamp.now()}")
    st.dataframe(df_signals)

    # Accuracy leaderboard
    leaderboard = df_signals.groupby("bot").apply(lambda x: (x.outcome=="win").sum() / max(1,len(x))*100).reset_index(name="accuracy")
    st.subheader("Bot Accuracy Leaderboard (%)")
    st.dataframe(leaderboard.sort_values("accuracy", ascending=False))

st.write("Auto-refresh every 5 seconds...")
st_autorefresh = st.experimental_rerun
time.sleep(5)
st.experimental_rerun()
