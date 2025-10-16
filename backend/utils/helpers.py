import pandas as pd
import numpy as np
from datetime import datetime

def verify_signal(signal, hist_df):
    """
    Compute verification and confidence based on historical data
    """
    coin = signal["coin"]
    color = signal["color"]
    number = signal["number"]

    coin_hist = hist_df[(hist_df["coin"]==coin) & ((hist_df["color"]==color) | (hist_df["number"]==number))]
    prob_correct = coin_hist["result"].mean() if len(coin_hist) > 0 else 0.5

    signal["verified"] = np.random.rand() < prob_correct
    signal["confidence"] = round(prob_correct * 100, 2)
    return signal

def assign_period_id(period_file="periods.csv"):
    """
    Generate next period_id
    """
    try:
        df = pd.read_csv(period_file)
        last_id = df["period_id"].max() if not df.empty else 0
    except FileNotFoundError:
        last_id = 0
    return last_id + 1

def save_signal(signal, verified_file="verified_signals.csv", historical_file="historical_signals.csv", period_file="periods.csv"):
    """
    Save signal to local CSV files
    """
    df = pd.DataFrame([signal])
    # Verified
    if not os.path.exists(verified_file):
        df.to_csv(verified_file, index=False)
    else:
        df.to_csv(verified_file, mode="a", header=False, index=False)
    
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
    if os.path.exists(historical_file):
        hist_df = pd.read_csv(historical_file)
        hist_df = pd.concat([hist_df, hist_update], ignore_index=True)
    else:
        hist_df = hist_update
    hist_df.to_csv(historical_file, index=False)

    # Period
    period_df = pd.DataFrame([{"period_id": signal["period_id"]}])
    if not os.path.exists(period_file):
        period_df.to_csv(period_file, index=False)
    else:
        period_df.to_csv(period_file, mode="a", header=False, index=False)
