import os
import asyncio
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from telethon import TelegramClient, events
from minio import Minio
import threading
import time

# --- Fix Python 3.13 event loop issue ---
try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

# --- Environment Config ---
API_ID = int(os.getenv("API_ID", "123456"))
API_HASH = os.getenv("API_HASH", "your_api_hash")

R2_ENDPOINT = os.getenv("R2_ENDPOINT", "https://your-r2-endpoint")
R2_BUCKET = os.getenv("R2_BUCKET", "coinryze-tracker")
R2_KEY_ID = os.getenv("R2_KEY_ID", "your_key_id")
R2_SECRET = os.getenv("R2_SECRET", "your_secret")

DATA_FILE = "signals.csv"

# --- Initialize R2 Client ---
r2 = Minio(
    R2_ENDPOINT.replace("https://", "").replace("http://", ""),
    access_key=R2_KEY_ID,
    secret_key=R2_SECRET,
    secure=True
)

# --- Load existing messages ---
if os.path.exists(DATA_FILE):
    df = pd.read_csv(DATA_FILE)
else:
    df = pd.DataFrame(columns=["timestamp", "message"])

# --- Initialize Telegram (personal session) ---
# Make sure telethon.session file is uploaded in the same folder
tg_client = TelegramClient("telethon", API_ID, API_HASH)

# --- Define message handler ---
@tg_client.on(events.NewMessage)
async def new_message_handler(event):
    global df
    msg = event.raw_text.strip()
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    new_row = pd.DataFrame([[ts, msg]], columns=["timestamp", "message"])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)
    try:
        r2.fput_object(R2_BUCKET, "signals.csv", DATA_FILE)
    except Exception as e:
        print("⚠️ R2 upload failed:", e)

# --- Background Telegram Listener Thread ---
def run_telegram_listener():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(tg_client.start())
    print("✅ Telegram client started (persistent background mode)")
    loop.run_until_complete(tg_client.run_until_disconnected())

thread = threading.Thread(target=run_telegram_listener, daemon=True)
thread.start()

# --- Streamlit Dashboard ---
st.set_page_config(page_title="CoinRyze Tracker", layout="wide")
st.title("📡 CoinRyze Tracker — Live Telegram Feed + Cloudflare R2 Sync")

st.sidebar.header("⚙️ Controls")
if st.sidebar.button("🔄 Manual Sync to R2"):
    try:
        if os.path.exists(DATA_FILE):
            r2.fput_object(R2_BUCKET, "signals.csv", DATA_FILE)
            st.sidebar.success("✅ Synced to R2 successfully!")
        else:
            st.sidebar.warning("No data file found yet.")
    except Exception as e:
        st.sidebar.error(f"Sync failed: {e}")

# --- Live Data View ---
st.markdown("### 📨 Latest Telegram Messages")
st.dataframe(df.tail(25), use_container_width=True)

if not df.empty:
    st.markdown("### 📈 Message Frequency Over Time")
    freq = (
        df.groupby(df["timestamp"].str[:16])
        .size()
        .reset_index(name="count")
        .rename(columns={"timestamp": "minute"})
    )
    fig = px.line(freq, x="minute", y="count", title="Messages per Minute")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No Telegram messages yet — waiting for new updates...")

# --- Keep background thread alive ---
while True:
    time.sleep(5)
