import os
import time
import psycopg2
import requests
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from starlette.responses import JSONResponse, Response
from prometheus_client import Counter, Histogram, generate_latest

# Import API routers
from auth_handler import router as auth_router
from query_handler import router as query_router
from speech_handler import router as speech_router
from image_handler import router as image_router

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN is missing in .env file")  # Secure way to store sensitive info
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL")

# Validate environment variables
if not GEMINI_API_KEY:
    raise ValueError("❌ GEMINI_API_KEY is missing in .env file")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL is missing in .env file")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN is missing in .env file")
if not TELEGRAM_WEBHOOK_URL:
    raise ValueError("❌ TELEGRAM_WEBHOOK_URL is missing in .env file")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"

print("🔹 Using Database: PostgreSQL")

# Initialize FastAPI
app = FastAPI()

# Prometheus Metrics
REQUEST_COUNT = Counter("api_requests_total", "Total API requests received")
REQUEST_LATENCY = Histogram("api_request_latency_seconds", "API request latency")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    REQUEST_COUNT.inc()
    start_time = time.time()
    try:
        response = await call_next(request)
    except Exception:
        return JSONResponse(content={"error": "Internal Server Error"}, status_code=500)
    process_time = time.time() - start_time
    REQUEST_LATENCY.observe(process_time)
    return response

# Database Connection
def get_db_connection():
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception:
        raise HTTPException(status_code=500, detail="Database connection failed")

# Database Setup
def setup_database():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    transaction_id TEXT UNIQUE,
                    amount REAL,
                    transaction_type TEXT,
                    date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    method TEXT
                );
                """)

                cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    name TEXT,
                    email TEXT UNIQUE,
                    password TEXT
                );
                """)
            conn.commit()
        print("✅ Database setup complete!")
    except Exception as e:
        print("❌ Database setup failed:", str(e))

setup_database()

@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")

# Include API Feature Routers
app.include_router(auth_router)
app.include_router(query_router)
app.include_router(speech_router)
app.include_router(image_router)

# Gemini API Call with Retry Logic
def call_gemini_api(payload, retries=3):
    headers = {"Content-Type": "application/json"}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    for attempt in range(retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json()
        except requests.exceptions.RequestException:
            pass
        time.sleep(2 ** attempt)
    raise HTTPException(status_code=500, detail="Gemini API request failed after retries")

# Set Telegram Webhook
def set_telegram_webhook():
    webhook_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    response = requests.post(webhook_url, json={"url": TELEGRAM_WEBHOOK_URL})
    if response.status_code == 200:
        print("✅ Telegram webhook set successfully!")
    else:
        print("❌ Failed to set Telegram webhook:", response.text)

# Telegram Webhook Handler
@app.post("/webhook")
async def telegram_webhook(update: dict):
    try:
        print("📩 Telegram Update Received:", update)
        if "message" in update:
            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "")
            
            if text.lower() == "/login":
                response_text = "🔑 Please enter your username and password."
            elif text.lower() == "/process-query":
                response_text = "🔍 Processing your query..."
            elif text.lower() == "/speech-to-text":
                response_text = "🎙️ Send a voice message for transcription."
            else:
                response_text = f"🗨️ You said: {text}"

            send_telegram_message(chat_id, response_text)
    except Exception as e:
        print("❌ Error in webhook:", str(e))
    return {"status": "ok"}

# Send Telegram Message
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    response = requests.post(url, json=payload)
    return response.json()

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    traceback.print_exc()
    return JSONResponse(content={"error": "Internal Server Error"}, status_code=500)

@app.get("/")
async def root():
    return {"message": "API is live!"}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(content="", media_type="image/x-icon")

if __name__ == "__main__":
    import uvicorn
    set_telegram_webhook()  # Set webhook on startup
    uvicorn.run(app, host="0.0.0.0", port=8000)
