from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from utils import get_latest_draw, calculate_accuracy

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def home():
    return {"message":"CoinRyze Tracker Backend Running"}

@app.get("/latest")
async def latest_draw():
    return {"latest_draw": get_latest_draw()}

@app.get("/accuracy")
async def accuracy():
    return {"accuracy": calculate_accuracy()}
