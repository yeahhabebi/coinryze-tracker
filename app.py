import os
import asyncio
import pandas as pd
import streamlit as st
import boto3
from datetime import datetime
from pyrogram import Client, filters

# ---------- CONFIG ----------
API_ID = int(os.getenv("TG_API_ID", "123456"))
API_HASH = os.getenv("TG_API_HASH", "")
BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
R2_ENDPOINT = os.getenv("R2_ENDPOINT", "")
R2_BUCKET = os.getenv("R2_BUCKET", "")
R2_KEY_ID = os.getenv("R2_KEY_ID", "")
R2_SECRET = os.getenv("R2_SECRET", "")

DATA_FILE = "signals.csv"

# ---------- TELEGRAM LISTENER ----------
app = Client("coinryze_tracker", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def append_signal(user, text):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    new = pd.DataFrame([[ts, user, text]], columns=["timestamp", "user", "signal"])
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
        df = pd.concat([df, new], ignore_index=True)
    else:
        df = new
    df.to_csv(DATA_FILE, index=False)
    return df

@app.on_message(filters.text & ~filters.edited)
async def on_msg(_, msg):
    append_signal(msg.from_user.first_name if msg.from_user else "Unknown", msg.text)
    print(f"📩 {msg.text}")

# ---------- CLOUD R2 SYNC ----------
def upload_to_r2():
    if not all([R2_ENDPOINT, R2_BUCKET, R2_KEY_ID, R2_SECRET]):
        return "⚠️ R2 not configured"
    s3 = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_KEY_ID,
        aws_secret_access_key=R2_SECRET,
    )
    s3.upload_file(DATA_FILE, R2_BUCKET, DATA_FILE)
    return "✅ Synced to R2"

# ---------- STREAMLIT DASHBOARD ----------
st.set_page_config(page_title="CoinRyze Tracker", layout="wide")
st.title("📊 CoinRyze Telegram Tracker")

if os.path.exists(DATA_FILE):
    df = pd.read_csv(DATA_FILE)
else:
    df = pd.DataFrame(columns=["timestamp", "user", "signal"])

col1, col2 = st.columns([2, 1])
with col1:
    st.dataframe(df.tail(20), use_container_width=True)
with col2:
    if st.button("🔁 Sync to Cloudflare R2"):
        st.success(upload_to_r2())

# ---------- START TELEGRAM CLIENT ----------
async def run_bot():
    await app.start()
    print("✅ Telegram listener running...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(run_bot())
