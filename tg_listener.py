from telethon import TelegramClient
from telethon.sessions import StringSession
import os
import pandas as pd
from datetime import datetime

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
TELETHON_SESSION = os.getenv("TELETHON_SESSION")
TARGET_CHAT = os.getenv("TARGET_CHAT")

client = TelegramClient(StringSession(TELETHON_SESSION), API_ID, API_HASH)
client.start()

def fetch_signals(limit=20):
    signals = []
    updates = client.get_messages(TARGET_CHAT, limit=limit)
    for message in updates:
        text = message.text or ""
        if "Trade:" in text and "Recommended quantity:" in text:
            try:
                color = text.split("Trade:")[1].split()[0]
                quantity = float(text.split("Recommended quantity:")[1].split()[0].replace("x",""))
                signals.append({
                    "timestamp": datetime.now(),
                    "coin":"ETH",
                    "color":color,
                    "number":"1",
                    "direction":color,
                    "quantity":quantity
                })
            except:
                continue
    return signals
