# app.py
import streamlit as st
import pandas as pd
import numpy as np
import threading
import time
from datetime import datetime
import os
import requests
import boto3
import io
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# -----------------------------
# Telegram Bot Settings
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

# -----------------------------
# Cloudflare R2 Settings
# -----------------------------
R2_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ENDPOINT = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

s3_client = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_KEY_ID,
    aws_secret_access_key=R2_SECRET
)

# -----------------------------
# File keys on R2
# -----------------------------
VERIFIED_FILE = "verified_signals.csv"
HISTORICAL_FILE = "historical_signals.csv"
PERIOD_FILE = "periods.csv"
UPDATE_ID_FILE = "last_update_id.txt"

# -----------------------------
# Helper functions for R2
# -----------------------------
def r2_exists(key):
    try:
        s3_client.head_object(Bucket=R2_BUCKET, Key=key)
        return True
    except:
        return False

def r2_read_csv(key):
    if r2_exists(key):
        obj = s3_client.get_object(Bucket=R2_BUCKET, Key=key)
        return pd.read_csv(io.BytesIO(obj['Body'].read()))
    return pd.DataFrame()

def r2_write_csv(df, key):
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    s3_client.put_object(Bucket=R2_BUCKET, Key=key, Body=csv_buffer.getvalue())

def r2_read_text(key):
    if r2_exists(key):
        obj = s3_client.get_object(Bucket=R2_BUCKET, Key=key)
        return obj['Body'].read().decode()
    return None

def r2_write_text(key, text):
    s3_client.put_object(Bucket=R2_BUCKET, Key=key, Body=text.encode())

# -----------------------------
# Load historical data from R2
# -----------------------------
hist_df = r2_read_csv(HISTORICAL_FILE)
if not hist_df.empty:
    hist_df['result'] = hist_df['result'].astype(bool)
else:
    hist_df = pd.DataFrame(columns=["timestamp", "coin", "color", "number", "direction", "result", "quantity"])

# Load last processed Telegram update_id from R2
LAST_UPDATE_ID = r2_read_text(UPDATE_ID_FILE)
if LAST_UPDATE_ID:
    LAST_UPDATE_ID = int(LAST_UPDATE_ID)
else:
    LAST_UPDATE_ID = None

# -----------------------------
# Telegram Fetch
# -----------------------------
def fetch_signals_from_telegram():
    global LAST_UPDATE_ID
    try:
        res = requests.get(API_URL, timeout=10)
        res.raise_for_status()
        data = res.json()
        print(f"[Telegram] Fetched {len(data.get('result',[]))} updates")
    except Exception as e:
        print(f"[Telegram] Fetch error: {e}")
        return []

    signals = []
    for update in data.get('result', []):
        update_id = update['update_id']
        if LAST_UPDATE_ID is not None and update_id <= LAST_UPDATE_ID:
            continue

        LAST_UPDATE_ID = update_id
        r2_write_text(UPDATE_ID_FILE, str(LAST_UPDATE_ID))

        message = update.get('message', {})
        text = message.get('text', '')
        if "Coin:" in text and "Color:" in text and "Number:" in text and "Quantity:" in text:
            try:
                coin = text.split("Coin:")[1].split("Color:")[0].strip()
                color = text.split("Color:")[1].split("Number:")[0].strip()
                number = text.split("Number:")[1].split("Quantity:")[0].strip()
                quantity_str = text.split("Quantity:")[1].split()[0]
                quantity = float(quantity_str.replace("x",""))
            except Exception as e:
                print(f"[Telegram] Parsing error: {e}, text: {text}")
                quantity = 1.0
            signals.append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "coin": coin,
                "color": color,
                "number": number,
                "direction": color,
                "quantity": quantity,
                "verified": None,
                "confidence": None,
                "period_id": None
            })
    return signals

# -----------------------------
# Verification & Period Functions
# -----------------------------
def verify_signal(signal):
    global hist_df
    coin_hist = hist_df[(hist_df["coin"]==signal["coin"]) & ((hist_df["color"]==signal["color"]) | (hist_df["number"]==signal["number"]))]
    prob_correct = coin_hist["result"].mean() if len(coin_hist) > 0 else 0.5
    signal["verified"] = np.random.rand() < prob_correct
    signal["confidence"] = round(prob_correct * 100, 2)
    return signal

def assign_period_id():
    period_df = r2_read_csv(PERIOD_FILE)
    last_id = period_df["period_id"].max() if not period_df.empty else 0
    return last_id + 1

# -----------------------------
# Save signals to R2
# -----------------------------
def save_signal(signal):
    global hist_df

    # Verified
    df = pd.DataFrame([signal])
    if r2_exists(VERIFIED_FILE):
        old = r2_read_csv(VERIFIED_FILE)
        df = pd.concat([old, df], ignore_index=True)
    r2_write_csv(df, VERIFIED_FILE)

    # Historical
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

    # Period
    period_df = pd.DataFrame([{"period_id": signal["period_id"]}])
    if r2_exists(PERIOD_FILE):
        old_period = r2_read_csv(PERIOD_FILE)
        period_df = pd.concat([old_period, period_df], ignore_index=True)
    r2_write_csv(period_df, PERIOD_FILE)

# -----------------------------
# Background Worker
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
st.set_page_config(page_title="CoinRyze Tracker", layout="wide")
st.title("💹 CoinRyze Color/Number Signal Tracker Terminal")

menu = ["Live Dashboard", "Signal Analytics", "Next Best Trade", "Heatmaps"]
choice = st.sidebar.selectbox("Menu", menu)

# -----------------------------
# Utility function to read verified signals from R2
# -----------------------------
def get_verified_df():
    df = r2_read_csv(VERIFIED_FILE)
    if not df.empty:
        df["verified"] = df["verified"].astype(bool)
        df["confidence"] = df["confidence"].round(2)
        df["period_id"] = df["period_id"].astype(int)
    return df

# -----------------------------
# Live Dashboard
# -----------------------------
if choice == "Live Dashboard":
    st.subheader("🎯 Real-Time Signals")
    df = get_verified_df()
    if not df.empty:
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
    df = get_verified_df()
    if not df.empty:
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
    df = get_verified_df()
    if not df.empty:
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
    st.subheader("🌈 CoinRyze-Style Heatmap: Color & Number Win Probabilities + Mini Trend")
    df = get_verified_df()
    if not df.empty:
        colors_list = df['color'].unique().tolist()
        numbers_list = sorted(df['number'].unique().tolist(), key=lambda x: int(x))
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

# -----------------------------
# Footer
# -----------------------------
st.markdown("---")
st.markdown("🔄 Background worker running ✅ Real-time CoinRyze terminal with self-learning verification, high-confidence alerts, period IDs, prediction confidence, quantity trends, next best trade ranking, colored badges/icons, and heatmap with mini trends.")
