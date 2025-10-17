import streamlit as st
import pandas as pd
import requests
import os

DATA_FILE = os.path.join("..","backend","data","seed.csv")
API_URL = os.environ.get("BACKEND_URL","http://localhost:8000")

st.title("CoinRyze Tracker Dashboard")

placeholder_table = st.empty()
placeholder_chart = st.empty()
placeholder_acc = st.empty()
placeholder_log = st.empty()
logs = []

def refresh():
    df = pd.read_csv(DATA_FILE)
    placeholder_table.dataframe(df)
    placeholder_chart.line_chart(df['result'])
    acc = requests.get(f"{API_URL}/accuracy").json().get("accuracy",0)
    placeholder_acc.metric("Accuracy %", acc)

while True:
    refresh()
