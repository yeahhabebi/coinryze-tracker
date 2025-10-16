import os
from telethon import TelegramClient, events
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

client = TelegramClient("coinryze_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@client.on(events.NewMessage(chats="@CoinryzeColor"))
async def handler(event):
    text = event.raw_text
    print(f"New message: {text}")

if __name__ == "__main__":
    print("Telegram listener started...")
    client.run_until_disconnected()
