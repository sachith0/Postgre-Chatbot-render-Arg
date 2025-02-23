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

# Environment validation
if not all([GEMINI_API_KEY, DATABASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_URL]):
    raise ValueError("Missing required environment variables")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"

# Initialize FastAPI
app = FastAPI()

# Prometheus Metrics
REQUEST_COUNT = Counter("api_requests_total", "Total API requests received")
REQUEST_LATENCY = Histogram("api_request_latency_seconds", "API request latency")

class DatabaseManager:
    @staticmethod
    def get_connection():
        try:
            return psycopg2.connect(DATABASE_URL)
        except Exception as e:
            print(f"Database connection failed: {str(e)}")
            raise HTTPException(status_code=500, detail="Database connection failed")

    @staticmethod
    def setup_tables():
        try:
            with DatabaseManager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        customer_id SERIAL PRIMARY KEY,
                        name VARCHAR(100) NOT NULL,
                        account_number VARCHAR(20) UNIQUE NOT NULL,
                        ifsc_code VARCHAR(11) NOT NULL,
                        account_city VARCHAR(50) NOT NULL,
                        account_type VARCHAR(20) NOT NULL,
                        status VARCHAR(20) DEFAULT 'ACTIVE',
                        contact VARCHAR(15) NOT NULL,
                        password TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """)
                    
                    cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        transaction_id SERIAL PRIMARY KEY,
                        customer_id INTEGER REFERENCES users(customer_id),
                        account_number VARCHAR(20) NOT NULL,
                        date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        amount DECIMAL(10,2) NOT NULL,
                        transaction_type VARCHAR(20) NOT NULL,
                        method VARCHAR(20) NOT NULL,
                        description TEXT,
                        balance_after_transaction DECIMAL(10,2) NOT NULL
                    );
                    """)
                conn.commit()
            print("Database setup complete")
        except Exception as e:
            print(f"Database setup failed: {str(e)}")
            raise

class UserManager:
    @staticmethod
    def get_user_by_account(account_number: str):
        with DatabaseManager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT customer_id, name, account_number, ifsc_code,
                           account_city, account_type, status, contact,
                           password, created_at
                    FROM users 
                    WHERE account_number = %s AND status = 'ACTIVE'
                """, (account_number,))
                result = cursor.fetchone()
                if result:
                    return {
                        "customer_id": result[0],
                        "name": result[1],
                        "account_number": result[2],
                        "ifsc_code": result[3],
                        "account_city": result[4],
                        "account_type": result[5],
                        "status": result[6],
                        "contact": result[7],
                        "password": result[8],
                        "created_at": result[9].isoformat()
                    }
        return None

    @staticmethod
    def get_user_transactions(customer_id: int, limit: int = 5):
        with DatabaseManager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM transactions 
                    WHERE customer_id = %s 
                    ORDER BY date_time DESC 
                    LIMIT %s
                """, (customer_id, limit))
                return cursor.fetchall()

class TelegramHandler:
    @staticmethod
    def send_message(chat_id: int, text: str):
        url = f"{TELEGRAM_API_URL}sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        return requests.post(url, json=payload).json()

    @staticmethod
    def format_transaction_message(transactions):
        if not transactions:
            return "No recent transactions found."
        
        message = "Recent Transactions:\n\n"
        for t in transactions:
            message += (
                f"Transaction ID: {t[0]}\n"
                f"Amount: ₹{t[4]}\n"
                f"Type: {t[5]}\n"
                f"Method: {t[6]}\n"
                f"Description: {t[7]}\n"
                f"Balance: ₹{t[8]}\n"
                f"Date: {t[3].strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            )
        return message

@app.middleware("http")
async def log_requests(request: Request, call_next):
    REQUEST_COUNT.inc()
    start_time = time.time()
    try:
        response = await call_next(request)
    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return JSONResponse(content={"error": "Internal Server Error"}, status_code=500)
    process_time = time.time() - start_time
    REQUEST_LATENCY.observe(process_time)
    return response

@app.post("/webhook")
async def telegram_webhook(update: dict):
    try:
        if "message" not in update:
            return {"status": "no_message"}

        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "").strip()
        
        if text == "/start":
            TelegramHandler.send_message(chat_id, 
                "Welcome to BankBot!\nPlease enter your account number:")
            return {"status": "awaiting_account"}

        if text.isnumeric():
            user = UserManager.get_user_by_account(text)
            if user:
                TelegramHandler.send_message(chat_id, 
                    "Account verified! Please enter your password:")
                return {"status": "awaiting_password"}
            else:
                TelegramHandler.send_message(chat_id, 
                    "Invalid account number. Please try again.")
                return {"status": "invalid_account"}

        if text.startswith("/transactions"):
            user = UserManager.get_user_by_account(str(chat_id))
            if user:
                transactions = UserManager.get_user_transactions(user["customer_id"])
                message = TelegramHandler.format_transaction_message(transactions)
                TelegramHandler.send_message(chat_id, message)
                return {"status": "transactions_fetched"}

        if text.startswith("/query"):
            query = text.replace("/query", "").strip()
            if query:
                response = call_gemini_api({"text": query})
                TelegramHandler.send_message(chat_id, response)
                return {"status": "query_processed"}

        TelegramHandler.send_message(chat_id, 
            "I didn't understand that command. Please try again.")
        return {"status": "unknown_command"}

    except Exception as e:
        print(f"Error in webhook: {str(e)}")
        traceback.print_exc()
        TelegramHandler.send_message(chat_id, 
            "An error occurred. Please try again.")
        return {"status": "error"}

def call_gemini_api(payload, retries=3):
    headers = {"Content-Type": "application/json"}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    for attempt in range(retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json()["content"]
        except requests.exceptions.RequestException:
            if attempt == retries - 1:
                return "Error processing query. Please try again later."
        time.sleep(2 ** attempt)
    return "Service temporarily unavailable."

# Include API Feature Routers
app.include_router(auth_router)
app.include_router(query_router)
app.include_router(speech_router)
app.include_router(image_router)

@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")

@app.get("/")
async def root():
    return {"message": "BankBot API is running"}

if __name__ == "__main__":
    DatabaseManager.setup_tables()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
