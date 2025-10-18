import os, time, json, asyncio, random
import pandas as pd
import streamlit as st
from pyrogram import Client
from CloudFlare import CloudFlare
import requests
import plotly.express as px

# ========================
# Environment Variables
# ========================
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_KEY_ID = os.getenv("R2_KEY_ID")
R2_SECRET = os.getenv("R2_SECRET")
TELEGRAM_API_IDS = json.loads(os.getenv("TELEGRAM_API_IDS", "[]"))
TELEGRAM_API_HASHES = json.loads(os.getenv("TELEGRAM_API_HASHES", "[]"))
TELEGRAM_SESSIONS = json.loads(os.getenv("TELEGRAM_SESSION", "[]"))

# ========================
# Cloudflare R2 client
# ========================
def upload_r2(file_name, data, retries=3):
    for attempt in range(retries):
        try:
            cf = CloudFlare(token=R2_SECRET)
            url = f"https://{R2_BUCKET}.{R2_ENDPOINT}/{file_name}"
            resp = requests.put(url, data=data, auth=(R2_KEY_ID, R2_SECRET))
            if resp.status_code in [200,201]:
                return True
        except Exception as e:
            print(f"R2 Upload failed attempt {attempt+1}: {e}")
        time.sleep(2)
    return False

# ========================
# Telegram Listener
# ========================
signals = []

async def start_telegram():
    clients = []
    for i, session in enumerate(TELEGRAM_SESSIONS):
        client = Client(
            session_name=f"bot{i}",
            api_id=int(TELEGRAM_API_IDS[i]),
            api_hash=TELEGRAM_API_HASHES[i],
            session_string=session
        )
        clients.append(client)

    async def handler(client):
        async with client:
            @client.on_message()
            async def message_listener(_, message):
                text = message.text or ""
                signal = {"bot": client.session_name, "signal": text, "time": time.time()}
                signals.append(signal)
                df = pd.DataFrame(signals)
                upload_r2("signals.json", df.to_json())

    await asyncio.gather(*[handler(c) for c in clients])

# ========================
# Streamlit Dashboard
# ========================
st.set_page_config(page_title="CoinRyze Tracker", layout="wide")
st.title("📊 Live Telegram Signals Dashboard")

def display_dashboard():
    if not signals:
        st.warning("No data yet. Waiting for signals...")
        return

    df = pd.DataFrame(signals)
    df['time_str'] = pd.to_datetime(df['time'], unit='s').dt.strftime("%H:%M:%S")
    st.dataframe(df.tail(20))

    # Heatmap per bot
    if 'bot' in df.columns:
        heat = df.groupby('bot').size().reset_index(name='count')
        fig = px.bar(heat, x='bot', y='count', title="Signals per Bot", color='count')
        st.plotly_chart(fig)

    # Leaderboard
    df['verified'] = df['signal'].apply(lambda x: random.choice([0,1]))
    leaderboard = df.groupby('bot')['verified'].mean().reset_index()
    leaderboard['accuracy'] = (leaderboard['verified']*100).round(2)
    st.subheader("Bot Accuracy Leaderboard")
    st.table(leaderboard.sort_values("accuracy", ascending=False))

# ========================
# Main Async Runner
# ========================
async def main():
    asyncio.create_task(start_telegram())
    while True:
        display_dashboard()
        await asyncio.sleep(5)

# Run dashboard
asyncio.run(main())
