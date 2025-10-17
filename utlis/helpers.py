import pandas as pd
import numpy as np

def calculate_accuracy(df):
    if df.empty:
        return 0
    return (df['verified'].sum() / len(df)) * 100

def assign_period_id(df):
    if df.empty:
        return 1
    return df['period_id'].max() + 1

def color_badge(color):
    colors = {"Red":"🔴","Green":"🟢","Blue":"🔵"}
    return colors.get(color,color)

def number_badge(number):
    return f"🔹{number}"
