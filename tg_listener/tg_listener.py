from telethon import TelegramClient, events
from backend.utils import get_latest_draw
import os

api_id = int(os.environ.get("API_ID"))
api_hash = os.environ.get("API_HASH")
session_name = "my_session"

client = TelegramClient(session_name, api_id, api_hash)

@client.on(events.NewMessage)
async def handler(event):
    if "draw" in event.text.lower():
        new_draw = get_latest_draw()
        print("New draw via Telegram:", new_draw)

client.start()
client.run_until_disconnected()
