import os
import time
import psycopg2
import requests
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Depends
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
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL")

# Validate environment variables
if not all([GEMINI_API_KEY, DATABASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_URL]):
    raise ValueError("❌ Missing required environment variables!")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"

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
    except Exception as e:
        print(f"❌ Error processing request: {str(e)}")
        return JSONResponse(content={"error": "Internal Server Error"}, status_code=500)
    process_time = time.time() - start_time
    REQUEST_LATENCY.observe(process_time)
    return response

# Database Connection
def get_db_connection():
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"❌ Database connection failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Database connection failed")

# Set up tables
def setup_database():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE,
                    password TEXT,
                    account_number TEXT UNIQUE,
                    balance REAL DEFAULT 0
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    transaction_id TEXT UNIQUE,
                    amount REAL,
                    transaction_type TEXT,
                    date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

# Telegram Webhook Handling
@app.post("/webhook")
async def telegram_webhook(update: dict):
    try:
        print("📩 Telegram Update Received:", update)
        if "message" in update:
            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "").strip().lower()
            
            if text == "/start":
                send_telegram_message(chat_id, "👋 Welcome to BankBot!\nPlease enter your account number:")
                return {"status": "awaiting_account"}

            elif text.isnumeric():
                if validate_account_number(text):
                    send_telegram_message(chat_id, "✅ Account verified! Please enter your password:")
                    return {"status": "awaiting_password"}
                else:
                    send_telegram_message(chat_id, "❌ Invalid account number. Try again.")
                    return {"status": "invalid_account"}

            elif text.startswith("/balance"):
                balance = get_balance(chat_id)
                send_telegram_message(chat_id, f"💰 Your current balance is: ₹{balance}")
                return {"status": "balance_checked"}

            elif text.startswith("/transaction"):
                response_text = "🔄 Checking your transactions..."
                send_telegram_message(chat_id, response_text)
                transactions = get_transactions(chat_id)
                send_telegram_message(chat_id, transactions)
                return {"status": "transactions_fetched"}

            elif text.startswith("/query"):
                response_text = "🔍 Please wait while we process your banking query..."
                send_telegram_message(chat_id, response_text)
                ai_response = call_gemini_api({"query": text})
                send_telegram_message(chat_id, ai_response)
                return {"status": "query_processed"}

            else:
                send_telegram_message(chat_id, "🤖 I didn't understand that command.")
    except Exception as e:
        print("❌ Error in webhook:", str(e))
    return {"status": "ok"}

# Telegram Messaging
def send_telegram_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    response = requests.post(url, json=payload)
    return response.json()

# Account Validation
def validate_account_number(account_number):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE account_number = %s", (account_number,))
            return cursor.fetchone() is not None

# Fetch Balance
def get_balance(chat_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT balance FROM users WHERE id = %s", (chat_id,))
            result = cursor.fetchone()
            return result[0] if result else "Unknown"

# Fetch Transactions
def get_transactions(chat_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT amount, transaction_type, date_time FROM transactions WHERE user_id = %s ORDER BY date_time DESC LIMIT 5", (chat_id,))
            transactions = cursor.fetchall()
            if not transactions:
                return "📉 No recent transactions found."
            return "\n".join([f"💳 {t[1]}: ₹{t[0]} on {t[2]}" for t in transactions])

# Gemini API Call with Retry Logic
def call_gemini_api(payload, retries=3):
    headers = {"Content-Type": "application/json"}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    for attempt in range(retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json()["content"]
        except requests.exceptions.RequestException:
            pass
        time.sleep(2 ** attempt)
    return "❌ Error processing query."

# Set Telegram Webhook
def set_telegram_webhook():
    webhook_url = f"{TELEGRAM_API_URL}setWebhook"
    response = requests.post(webhook_url, json={"url": TELEGRAM_WEBHOOK_URL})
    if response.status_code == 200:
        print("✅ Telegram webhook set successfully!")
    else:
        print("❌ Failed to set Telegram webhook:", response.text)

@app.get("/")
async def root():
    return {"message": "BankBot API is live!"}

if __name__ == "__main__":
    set_telegram_webhook()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
