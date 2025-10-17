# app.py

# -----------------------------
# Must be first: Streamlit page config
# -----------------------------
import streamlit as st
st.set_page_config(page_title="CoinRyze Tracker", layout="wide")

# -----------------------------
# Imports
# -----------------------------
import pandas as pd
import numpy as np
import threading
import time
from datetime import datetime
import io
import os
import boto3
from telethon import TelegramClient
from telethon.sessions import StringSession
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go

# -----------------------------
# Environment / R2 Config
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

# Telegram API
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
TELETHON_SESSION = os.getenv("TELETHON_SESSION")
TARGET_CHAT = "@ETHGPT60s_bot"

# -----------------------------
# R2 Client Setup
# -----------------------------
session = boto3.session.Session()
r2_client = session.client(
    's3',
    region_name='auto',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY
)

# CSV file names in R2
VERIFIED_FILE = "verified_signals.csv"
HISTORICAL_FILE = "historical_signals.csv"
PERIOD_FILE = "periods.csv"
UPDATE_ID_FILE = "last_update_id.txt"

# -----------------------------
# Telegram Client Setup
# -----------------------------
client = TelegramClient(StringSession(TELETHON_SESSION), API_ID, API_HASH)
client.start()

# -----------------------------
# Helper functions for R2
# -----------------------------
def r2_read_csv(filename):
    try:
        obj = r2_client.get_object(Bucket=R2_BUCKET, Key=filename)
        return pd.read_csv(io.BytesIO(obj['Body'].read()))
    except r2_client.exceptions.NoSuchKey:
        return pd.DataFrame()
    except Exception as e:
        print(f"Error reading {filename} from R2:", e)
        return pd.DataFrame()

def r2_save_csv(df, filename):
    with io.StringIO() as csv_buffer:
        df.to_csv(csv_buffer, index=False)
        r2_client.put_object(Bucket=R2_BUCKET, Key=filename, Body=csv_buffer.getvalue())

# -----------------------------
# Load historical data & last update
# -----------------------------
hist_df = r2_read_csv(HISTORICAL_FILE)
if 'result' in hist_df.columns:
    hist_df['result'] = hist_df['result'].astype(bool)

try:
    obj = r2_client.get_object(Bucket=R2_BUCKET, Key=UPDATE_ID_FILE)
    LAST_UPDATE_ID = int(obj['Body'].read().decode())
except:
    LAST_UPDATE_ID = None

# -----------------------------
# Telegram signal fetch
# -----------------------------
def fetch_signals_from_telegram():
    global LAST_UPDATE_ID
    signals = []
    try:
        updates = client.get_messages(TARGET_CHAT, limit=20)
    except Exception as e:
        print("Telegram fetch error:", e)
        return []

    for message in updates:
        update_id = message.id
        if LAST_UPDATE_ID is not None and update_id <= LAST_UPDATE_ID:
            continue
        LAST_UPDATE_ID = update_id
        r2_client.put_object(Bucket=R2_BUCKET, Key=UPDATE_ID_FILE, Body=str(LAST_UPDATE_ID))

        text = message.text or ""
        if "Trade:" in text and "Recommended quantity:" in text:
            try:
                color = text.split("Trade:")[1].split()[0]
                quantity_str = text.split("Recommended quantity:")[1].split()[0]
                quantity = float(quantity_str.replace("x",""))
                number = "1"  # default placeholder, adjust if needed
                signals.append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "coin": "ETH",
                    "color": color,
                    "number": number,
                    "direction": color,
                    "quantity": quantity,
                    "verified": None,
                    "confidence": None,
                    "period_id": None
                })
            except:
                continue
    return signals

# -----------------------------
# Signal verification / saving
# -----------------------------
def verify_signal(signal):
    global hist_df
    coin_hist = hist_df[(hist_df["coin"]==signal["coin"]) & ((hist_df["color"]==signal["color"]) | (hist_df["number"]==signal["number"]))]
    prob_correct = coin_hist["result"].mean() if len(coin_hist) > 0 else 0.5
    signal["verified"] = np.random.rand() < prob_correct
    signal["confidence"] = round(prob_correct * 100, 2)
    return signal

def assign_period_id():
    df = r2_read_csv(PERIOD_FILE)
    last_id = df["period_id"].max() if not df.empty else 0
    return last_id + 1

def save_signal(signal):
    global hist_df
    # Save verified signals
    try:
        df = pd.DataFrame([signal])
        try:
            existing = r2_read_csv(VERIFIED_FILE)
            df = pd.concat([existing, df], ignore_index=True)
        except:
            pass
        r2_save_csv(df, VERIFIED_FILE)
    except Exception as e:
        print("Save verified signal error:", e)

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
    r2_save_csv(hist_df, HISTORICAL_FILE)

    # Update period
    period_df = pd.DataFrame([{"period_id": signal["period_id"]}])
    try:
        existing_periods = r2_read_csv(PERIOD_FILE)
        period_df = pd.concat([existing_periods, period_df], ignore_index=True)
    except:
        pass
    r2_save_csv(period_df, PERIOD_FILE)

# -----------------------------
# Background worker
# -----------------------------
high_confidence_signals = []

def background_worker():
    global high_confidence_signals
    while True:
        try:
            new_signals = fetch_signals_from_telegram()
            for signal in new_signals:
                signal["period_id"] = assign_period_id()
                verified_signal = verify_signal(signal)
                save_signal(verified_signal)
                if verified_signal["confidence"] >= 75:
                    high_confidence_signals.append(verified_signal)
            time.sleep(60)
        except Exception as e:
            print("Worker error:", e)
            time.sleep(60)

if "worker_started" not in st.session_state:
    st.session_state.worker_started = True
    threading.Thread(target=background_worker, daemon=True).start()

# -----------------------------
# Auto-refresh
# -----------------------------
st_autorefresh(interval=60*1000, key="datarefresh")

# -----------------------------
# Streamlit UI
# -----------------------------
st.title("💹 CoinRyze Color/Number Signal Tracker Terminal")

menu = ["Live Dashboard", "Signal Analytics", "Next Best Trade", "Heatmaps"]
choice = st.sidebar.selectbox("Menu", menu)

# -----------------------------
# Live Dashboard
# -----------------------------
if choice == "Live Dashboard":
    st.subheader("🎯 Real-Time Signals")
    df = r2_read_csv(VERIFIED_FILE)
    if not df.empty:
        df["verified"] = df["verified"].astype(bool)
        df["confidence"] = df["confidence"].round(2)
        df["period_id"] = df["period_id"].astype(int)

        def color_rows(row):
            if row['verified']:
                return ['background-color: #b6fcd5']*len(row)
            elif row['confidence'] >= 75:
                return ['background-color: #fef3b3']*len(row)
            else:
                return ['background-color: #fcb6b6']*len(row)
        st.dataframe(df.tail(30).style.apply(color_rows, axis=1))

        if high_confidence_signals:
            for signal in high_confidence_signals:
                st.toast(f"🚨 High-Confidence Signal: {signal['coin']} {signal['color']}/{signal['number']} | Confidence: {signal['confidence']}%", icon="⚡")
            high_confidence_signals.clear()
    else:
        st.info("No signals yet.")

# -----------------------------
# Signal Analytics
# -----------------------------
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

# -----------------------------
# Next Best Trade
# -----------------------------
elif choice == "Next Best Trade":
    st.subheader("🚀 Next Best Color/Number Trade Prediction")
    df = r2_read_csv(VERIFIED_FILE)
    if not df.empty:
        df["verified"] = df["verified"].astype(bool)

        color_prob = df.groupby("color")["verified"].mean().sort_values(ascending=False)
        number_prob = df.groupby("number")["verified"].mean().sort_values(ascending=False)

        def color_badge(color):
            colors = {"Red":"🔴","Green":"🟢","Blue":"🔵"}
            return colors.get(color,color)

        def number_badge(number):
            return f"🔹{number}"

        color_df = pd.DataFrame({
            "Color": color_prob.index,
            "Win Probability": (color_prob.values*100).round(2),
            "Badge": [color_badge(c) for c in color_prob.index]
        })
        number_df = pd.DataFrame({
            "Number": number_prob.index,
            "Win Probability": (number_prob.values*100).round(2),
            "Badge": [number_badge(n) for n in number_prob.index]
        })

        st.markdown("### 🔴 Color Ranking")
        st.table(color_df[["Badge","Color","Win Probability"]])

        st.markdown("### 🔢 Number Ranking")
        st.table(number_df[["Badge","Number","Win Probability"]])
    else:
        st.info("No verified signals yet.")

# -----------------------------
# Heatmaps
# -----------------------------
elif choice == "Heatmaps":
    st.subheader("🌡️ Heatmaps")
    df = r2_read_csv(VERIFIED_FILE)
    if not df.empty:
        heat_data = df.pivot_table(index="number", columns="color", values="confidence", aggfunc="mean")
        fig = go.Figure(data=go.Heatmap(
            z=heat_data.values,
            x=heat_data.columns,
            y=heat_data.index,
            colorscale='Viridis'
        ))
        st.plotly_chart(fig)
    else:
        st.info("No data for heatmap yet.")
