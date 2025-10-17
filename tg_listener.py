from telethon import TelegramClient, events
from telethon.sessions import StringSession
import os

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
TELETHON_SESSION = os.getenv("TELETHON_SESSION")
TARGET_CHAT = "@ETHGPT60s_bot"

client = TelegramClient(StringSession(TELETHON_SESSION), API_ID, API_HASH)

@client.on(events.NewMessage(chats=TARGET_CHAT))
async def handler(event):
    print("New message received:", event.message.message)

client.start()
client.run_until_disconnected()
