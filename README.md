# CoinRyze Tracker

Real-time ETH 60s Color/Number signal tracker with analytics, heatmaps, and Telegram integration. Uses Cloudflare R2 for data storage and Streamlit for dashboards.

## Setup

1. Clone repo
2. Add `.env` or Render Environment Variables:
   - BOT_TOKEN
   - R2_ACCESS_KEY_ID
   - R2_SECRET_ACCESS_KEY
   - R2_BUCKET
   - R2_ENDPOINT
   - API_ID
   - API_HASH
   - TELETHON_SESSION
3. Deploy on Render:
   - Build Command: `pip install --upgrade pip && pip install -r requirements.txt`
   - Start Command: `streamlit run app.py`
