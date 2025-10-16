import os
import pandas as pd
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px
import requests
from datetime import datetime

# -----------------------------
# Environment variables
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Telegram bot token from Render env vars
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # optional if you use alerts

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(
    page_title="CoinRyze Tracker",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------
# Load initial data
# -----------------------------
@st.cache_data
def load_seed_data():
    df = pd.read_csv("seed.csv")
    return df

data = load_seed_data()

# -----------------------------
# Sidebar filters
# -----------------------------
st.sidebar.header("Filters")
coin_filter = st.sidebar.multiselect("Select Coin", options=data['coin'].unique(), default=data['coin'].unique())
data_filtered = data[data['coin'].isin(coin_filter)]

# -----------------------------
# Dashboard
# -----------------------------
st.title("📈 CoinRyze Tracker Dashboard")
st.markdown(f"**Last updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# KPIs
st.subheader("🔹 Key Metrics")
col1, col2, col3 = st.columns(3)
col1.metric("Total Coins", len(data_filtered))
col2.metric("High Confidence Alerts", (data_filtered['confidence'] > 0.8).sum())
col3.metric("Next Best Trade", data_filtered.loc[data_filtered['confidence'].idxmax(), 'coin'])

# Heatmap
st.subheader("🔥 Correlation Heatmap")
corr = data_filtered.corr(numeric_only=True)
fig, ax = plt.subplots(figsize=(10, 6))
sns.heatmap(corr, annot=True, fmt=".2f", cmap="coolwarm", ax=ax)
st.pyplot(fig)

# Plotly line chart for price trends
st.subheader("📊 Coin Price Trends")
for coin in data_filtered['coin'].unique():
    coin_data = data_filtered[data_filtered['coin'] == coin]
    fig_px = px.line(coin_data, x='date', y='price', title=f"{coin} Price Trend")
    st.plotly_chart(fig_px, use_container_width=True)

# -----------------------------
# High Confidence Alerts
# -----------------------------
st.subheader("⚡ High Confidence Alerts")
high_conf = data_filtered[data_filtered['confidence'] > 0.8]
st.dataframe(high_conf)

# Telegram alert function
def send_telegram_message(message):
    if BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        requests.post(url, data=payload)

# Send alerts for new high-confidence trades
for idx, row in high_conf.iterrows():
    msg = f"🚀 High Confidence Trade Alert!\nCoin: {row['coin']}\nConfidence: {row['confidence']:.2f}\nPrice: {row['price']}"
    send_telegram_message(msg)

# -----------------------------
# Footer
# -----------------------------
st.markdown("---")
st.markdown("CoinRyze Tracker — Fully automated dashboard with high-confidence alerts 🚀")
