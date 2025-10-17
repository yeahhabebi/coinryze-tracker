import pandas as pd

def safe_mean(series):
    return series.mean() if not series.empty else 0.0
