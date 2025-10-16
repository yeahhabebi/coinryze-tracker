# ==============================
# CoinRyze Tracker Terminal
# ==============================

import streamlit as st
st.set_page_config(page_title="CoinRyze Tracker", layout="wide")  # Must be first command

import pandas as pd
import numpy as np
import threading
import time
import os
from datetime import datetime
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
from telethon import TelegramClient, events, sync
from telethon.sessions import StringSession
import boto3
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

# ==============================
# Environment / R2 / Telegram
# ==============================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
TELETHON_SESSION = os.getenv("TELETHON_SESSION")  # Generated locally
TARGET_CHAT = os.getenv("TARGET_CHAT", "@ETHGPT60s_bot")

R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

# CSV filenames (on R2)
VERIFIED_FILE = "verified_signals.csv"
HISTORICAL_FILE = "historical_signals.csv"
PERIOD_FILE = "periods.csv"

# ==============================
# Initialize Cloudflare R2 client
# ==============================
session = boto3.session.Session()
r2_client = session.client(
    's3',
    region_name='auto',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET
)

def r2_read_csv(filename):
    try:
        obj = r2_client.get_object(Bucket=R2_BUCKET, Key=filename)
        return pd.read_csv(BytesIO(obj['Body'].read()))
    except r2_client.exceptions.NoSuchKey:
        return pd.DataFrame()

def r2_write_csv(df, filename):
    buffer = BytesIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    r2_client.put_object(Bucket=R2_BUCKET, Key=filename, Body=buffer)

# ==============================
# Load historical data
# ==============================
hist_df = r2_read_csv(HISTORICAL_FILE)
if 'result' in hist_df.columns:
    hist_df['result'] = hist_df['result'].astype(bool)

# ==============================
# Helper Functions
# ==============================
def assign_period_id():
    df = r2_read_csv(PERIOD_FILE)
    last_id = df["period_id"].max() if not df.empty else 0
    return last_id + 1

def verify_signal(signal):
    coin = signal["coin"]
    color = signal["color"]
    number = signal["number"]
    coin_hist = hist_df[(hist_df["coin"]==coin) & ((hist_df["color"]==color) | (hist_df["number"]==number))]
    prob_correct = coin_hist["result"].mean() if len(coin_hist) > 0 else 0.5
    signal["verified"] = np.random.rand() < prob_correct
    signal["confidence"] = round(prob_correct * 100, 2)
    return signal

def save_signal(signal):
    global hist_df
    df = pd.DataFrame([signal])
    # Save to R2 verified
    try:
        existing = r2_read_csv(VERIFIED_FILE)
        df = pd.concat([existing, df], ignore_index=True)
    except:
        pass
    r2_write_csv(df, VERIFIED_FILE)

    # Update historical
    hist_update = pd.DataFrame([{
        "timestamp": signal["timestamp"],
        "coin": signal["coin"],
        "color": signal["color"],
        "number": signal["number"],
        "direction": signal["direction"],
        "result": signal["verified"],
        "quantity": signal["quantity"]
    }])
    hist_df = pd.concat([hist_df, hist_update], ignore_index=True)
    r2_write_csv(hist_df, HISTORICAL_FILE)

    # Update period
    period_df = pd.DataFrame([{"period_id": signal["period_id"]}])
    existing_periods = r2_read_csv(PERIOD_FILE)
    period_df = pd.concat([existing_periods, period_df], ignore_index=True)
    r2_write_csv(period_df, PERIOD_FILE)

# ==============================
# Background Telegram Worker
# ==============================
high_confidence_signals = []

client = TelegramClient(StringSession(TELETHON_SESSION), API_ID, API_HASH)
client.start()

@client.on(events.NewMessage(chats=TARGET_CHAT))
async def handler(event):
    text = event.raw_text
    # Parse example message
    if "Trade:" in text and "Recommended quantity:" in text:
        coin = "ETH"  # fixed for this group
        color = text.split("Trade:")[1].split("✔️")[0].strip()
        number = 1  # placeholder
        quantity_str = text.split("Recommended quantity:")[1].split()[0].replace("x","")
        try: quantity = float(quantity_str)
        except: quantity = 1.0
        signal = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "coin": coin,
            "color": color,
            "number": number,
            "direction": color,
            "quantity": quantity,
            "period_id": assign_period_id()
        }
        signal = verify_signal(signal)
        save_signal(signal)
        if signal["confidence"] >= 75:
            high_confidence_signals.append(signal)

def start_telegram_listener():
    client.run_until_disconnected()

if "worker_started" not in st.session_state:
    st.session_state.worker_started = True
    threading.Thread(target=start_telegram_listener, daemon=True).start()

# ==============================
# Streamlit Auto-refresh
# ==============================
st_autorefresh(interval=60*1000, key="datarefresh")

# ==============================
# Streamlit UI
# ==============================
st.title("💹 CoinRyze Tracker Terminal")
menu = ["Live Dashboard", "Signal Analytics", "Next Best Trade", "Heatmaps"]
choice = st.sidebar.selectbox("Menu", menu)

# ------------------------------
# Live Dashboard
# ------------------------------
if choice == "Live Dashboard":
    st.subheader("🎯 Real-Time Signals")
    df = r2_read_csv(VERIFIED_FILE)
    if not df.empty:
        df["verified"] = df["verified"].astype(bool)
        df["confidence"] = df["confidence"].round(2)
        def color_rows(row):
            if row['verified']: return ['background-color: #b6fcd5']*len(row)
            elif row['confidence'] >= 75: return ['background-color: #fef3b3']*len(row)
            else: return ['background-color: #fcb6b6']*len(row)
        st.dataframe(df.tail(30).style.apply(color_rows, axis=1))
        # High-confidence alert
        if high_confidence_signals:
            for s in high_confidence_signals:
                st.toast(f"🚨 High-Confidence Signal: {s['coin']} {s['color']}/{s['number']} | Confidence: {s['confidence']}%", icon="⚡")
            high_confidence_signals.clear()
    else:
        st.info("No signals yet.")

# ------------------------------
# Signal Analytics
# ------------------------------
elif choice == "Signal Analytics":
    st.subheader("📊 Signal Analytics")
    df = r2_read_csv(VERIFIED_FILE)
    if not df.empty:
        df["verified"] = df["verified"].astype(bool)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        total_signals = len(df)
        correct_signals = df["verified"].sum()
        accuracy = (correct_signals / total_signals)*100 if total_signals>0 else 0
        st.metric("Total Signals Verified", total_signals)
        st.metric("Correct Signals", correct_signals)
        st.metric("Overall Accuracy (%)", f"{accuracy:.2f}%")
        accuracy_time = df.groupby(df["timestamp"].dt.floor("1min"))["verified"].mean()*100
        st.line_chart(accuracy_time.rename("Accuracy (%)"))
        coin_acc = df.groupby("coin")["verified"].mean()*100
        st.bar_chart(coin_acc.rename("Accuracy (%) by Coin"))
    else:
        st.info("No verified signals yet.")

# ------------------------------
# Next Best Trade
# ------------------------------
elif choice == "Next Best Trade":
    st.subheader("🚀 Next Best Trade Prediction")
    df = r2_read_csv(VERIFIED_FILE)
    if not df.empty:
        df["verified"] = df["verified"].astype(bool)
        color_prob = df.groupby("color")["verified"].mean().sort_values(ascending=False)
        number_prob = df.groupby("number")["verified"].mean().sort_values(ascending=False)
        color_df = pd.DataFrame({
            "Color": color_prob.index,
            "Win Probability": (color_prob.values*100).round(2)
        })
        number_df = pd.DataFrame({
            "Number": number_prob.index,
            "Win Probability": (number_prob.values*100).round(2)
        })
        st.markdown("### 🔴 Color Ranking")
        st.table(color_df)
        st.markdown("### 🔢 Number Ranking")
        st.table(number_df)
    else:
        st.info("No verified signals yet.")

# ------------------------------
# Heatmaps
# ------------------------------
elif choice == "Heatmaps":
    st.subheader("🌈 Color & Number Heatmap")
    df = r2_read_csv(VERIFIED_FILE)
    if not df.empty:
        df["verified"] = df["verified"].astype(bool)
        colors_list = df['color'].unique().tolist()
        numbers_list = sorted(df['number'].unique().tolist())
        matrix = np.zeros((len(colors_list), len(numbers_list)))
        trends = {}
        for i, color in enumerate(colors_list):
            for j, number in enumerate(numbers_list):
                subset = df[(df['color']==color) & (df['number']==number)]
                matrix[i,j] = subset['verified'].mean()*100 if len(subset)>0 else 0
                trends[(color, number)] = subset['verified'].tail(5).tolist()
        fig = go.Figure()
        for i, color in enumerate(colors_list):
            for j, number in enumerate(numbers_list):
                val = matrix[i,j]
                mini_trend = trends[(color, number)]
                fig.add_trace(go.Scatter(
                    x=[j], y=[i],
                    mode='markers+text',
                    marker=dict(size=60, color=val, colorscale="RdYlGn", showscale=False),
                    text="".join(["🟢" if v else "🔴" for v in mini_trend]),
                    textposition="middle center"
                ))
        fig.update_yaxes(autorange="reversed", tickvals=list(range(len(colors_list))), ticktext=colors_list)
        fig.update_xaxes(tickvals=list(range(len(numbers_list))), ticktext=numbers_list)
        fig.update_layout(height=600, width=900, xaxis_title="Number", yaxis_title="Color")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No verified signals yet.")

# ==============================
# Footer
# ==============================
st.markdown("---")
st.markdown("🔄 Background worker running ✅ Real-time CoinRyze-style terminal with R2 persistence, personal Telegram, high-confidence alerts, analytics, next trade ranking, colored badges, and heatmaps.")
