# app.py
import asyncio
import threading
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import streamlit as st
import time

# =======================
# Telegram Credentials
# =======================
API_ID = 11345160
API_HASH = "2912d1786520d56f2b0df8be2f0a8616"
STRING_SESSION = "1BVtsOJgBu4mVFFnw9DrbLHpfSir4AFF8nqf1Nl3-KedXp-WdfyCNwbw6x2aUtIX-YiK5r_tXzrd_aq6Cw9YJNvlaBIKAIA6XZro37UaxxRBc9LcdnKKz2DNTe3HKSp3QU71-7vdD6vpMR0gmWLWrTj8Eknm5t5fgVEaR4lk_VwhHDsI_hRvQFpoYFPCBtRj5aQosTS0kf5KR2pWHcyWMbaVN4s2fAsuMZ5CLykvbKdFlyHTuSBzQBHRuwRvotBW8fIf3NodWmZCn7i5e8jmtg7G8okkDD_oMpHrWGoXyjK67jm0oMztiPOIxS70NFSPPcQ6VZ2gpB67f1lI1y2W0hQckeyG5VW8="

# =======================
# Initialize Telegram Client
# =======================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# =======================
# Streamlit State
# =======================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "thread_started" not in st.session_state:
    st.session_state.thread_started = False

# =======================
# Telegram listener function
# =======================
@client.on(events.NewMessage)
async def handler(event):
    sender = await event.get_sender()
    name = sender.first_name if sender else str(event.sender_id)
    text = event.text
    # Add message to Streamlit state
    st.session_state.messages.append({"sender": name, "text": text})

# =======================
# Function to run client in background
# =======================
def run_client():
    client.start()
    client.run_until_disconnected()

# =======================
# Start Telegram listener in background thread
# =======================
if not st.session_state.thread_started:
    threading.Thread(target=run_client, daemon=True).start()
    st.session_state.thread_started = True

# =======================
# Streamlit UI
# =======================
st.set_page_config(page_title="📲 Coinryze Telegram Tracker", page_icon="📩", layout="wide")
st.title("📲 Coinryze Telegram Tracker")

st.subheader("Live Telegram Messages")

# Chat container
chat_container = st.container()

# Auto-refresh every 1.5 seconds
while True:
    with chat_container:
        for msg in st.session_state.messages[-50:]:  # show last 50 messages
            st.markdown(f"**{msg['sender']}**: {msg['text']}")
        # Auto-scroll to latest message
        st.markdown("<div style='height:1px;'>&nbsp;</div>", unsafe_allow_html=True)

    time.sleep(1.5)
    st.experimental_rerun()
