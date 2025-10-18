#!/bin/bash
# Start backend
uvicorn backend.app:app --host 0.0.0.0 --port 8000 &

# Start Telegram listener
python tg_listener/tg_listener.py &

# Start Streamlit dashboard
streamlit run frontend/dashboard.py --server.port 8501 --server.headless true
