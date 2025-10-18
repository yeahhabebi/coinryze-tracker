import os
import pandas as pd
import streamlit as st
import requests
from telethon import TelegramClient, events
from datetime import datetime
from io import BytesIO
import boto3

# -----------------------
# CONFIGURATION
# -----------------------
# Telegram
API_ID = int(os.getenv("TG_API_ID", "123456"))  # Your Telegram API ID
API_HASH = os.getenv("TG_API_HASH", "abcdef123456")  # Your API HASH
SESSION_NAME = os.getenv("TG_SESSION", "coinryze_session")  # Telethon session file

# Cloudflare R2
R2_KEY_ID = os.getenv("R2_KEY_ID", "")
R2_SECRET = os.getenv("R2_SECRET", "")
R2_BUCKET = os.getenv("R2_BUCKET", "")
R2_ENDPOINT = os.getenv("R2_ENDPOINT", "")

# CoinRyze Data
COINRYZE_URL = "https://www.coinryze.org/api/latest-draws"  # Example API URL

# -----------------------
# TELEGRAM CLIENT
# -----------------------
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
draws_data = []

@client.on(events.NewMessage(chats='@coinryze_channel'))
async def handler(event):
    text = event.message.message
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    draws_data.append({"time": timestamp, "message": text})
    print(f"[{timestamp}] {text}")

# -----------------------
# CLOUD R2 SYNC
# -----------------------
def upload_to_r2(df, filename="draws.csv"):
    session = boto3.session.Session()
    client_r2 = session.client(
        's3',
        region_name='auto',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_KEY_ID,
        aws_secret_access_key=R2_SECRET
    )
    csv_buffer = BytesIO()
    df.to_csv(csv_buffer, index=False)
    client_r2.put_object(Bucket=R2_BUCKET, Key=filename, Body=csv_buffer.getvalue())
    print(f"Uploaded {filename} to R2 bucket {R2_BUCKET}")

# -----------------------
# COINRYZE FETCHER
# -----------------------
def fetch_latest_draws():
    try:
        resp = requests.get(COINRYZE_URL)
        if resp.status_code == 200:
            data = resp.json()  # Assuming JSON API
            df = pd.DataFrame(data)
            return df
        return pd.DataFrame()
    except Exception as e:
        print("Fetch error:", e)
        return pd.DataFrame()

# -----------------------
# STREAMLIT DASHBOARD
# -----------------------
st.set_page_config(page_title="CoinRyze Tracker", layout="wide")
st.title("🟢 CoinRyze Live Tracker")

# Show fetched data
st.subheader("Latest Draws")
df_draws = fetch_latest_draws()
if not df_draws.empty:
    st.dataframe(df_draws)
else:
    st.info("No data fetched yet.")

# Show Telegram captured messages
st.subheader("Telegram Messages")
if draws_data:
    st.dataframe(pd.DataFrame(draws_data))
else:
    st.info("No Telegram messages captured yet.")

# Upload button
if st.button("Upload CSV to Cloudflare R2"):
    if not df_draws.empty:
        upload_to_r2(df_draws)
        st.success("Uploaded successfully!")
    else:
        st.warning("No data to upload.")

# -----------------------
# RUN TELEGRAM CLIENT
# -----------------------
import threading
def run_telegram():
    client.start()
    client.run_until_disconnected()

threading.Thread(target=run_telegram, daemon=True).start()
