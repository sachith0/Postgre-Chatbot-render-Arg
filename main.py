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
        
        # Get current user state from database
        user_state = get_user_state(chat_id)
        
        if text == "/start":
            # Clear any existing session
            clear_user_session(chat_id)
            TelegramHandler.send_message(chat_id, 
                "Welcome to BankBot!\nPlease enter your account number:")
            set_user_state(chat_id, "awaiting_account")
            return {"status": "awaiting_account"}

        # Handle account number input
        if user_state == "awaiting_account":
            user = UserManager.get_user_by_account(text)
            if user:
                store_temp_data(chat_id, "account_number", text)
                set_user_state(chat_id, "awaiting_password")
                TelegramHandler.send_message(chat_id, 
                    "Account verified! Please enter your password:")
                return {"status": "awaiting_password"}
            else:
                TelegramHandler.send_message(chat_id, 
                    "Invalid account number. Please try again or type /start to restart.")
                return {"status": "invalid_account"}

        # Handle password verification
        if user_state == "awaiting_password":
            account_number = get_temp_data(chat_id, "account_number")
            if not account_number:
                TelegramHandler.send_message(chat_id, 
                    "Session expired. Please type /start to begin again.")
                return {"status": "session_expired"}

            user = UserManager.get_user_by_account(account_number)
            if user and verify_password(text, user["password"]):
                set_user_state(chat_id, "authenticated")
                store_user_session(chat_id, user)
                
                welcome_msg = (
                    f"Authentication successful!\n\n"
                    f"Welcome {user['name']}\n"
                    f"Account: {user['account_number']}\n"
                    f"Type: {user['account_type']}\n\n"
                    "Available commands:\n"
                    "/transactions - View recent transactions\n"
                    "/query - Ask any banking related questions"
                )
                TelegramHandler.send_message(chat_id, welcome_msg)
                return {"status": "authenticated"}
            else:
                TelegramHandler.send_message(chat_id, 
                    "Invalid password. Please type /start to try again.")
                clear_user_session(chat_id)
                return {"status": "invalid_password"}

        # Handle authenticated user commands
        if user_state == "authenticated":
            user_data = get_user_session(chat_id)
            if not user_data:
                TelegramHandler.send_message(chat_id, 
                    "Session expired. Please type /start to authenticate.")
                return {"status": "session_expired"}

            if text.startswith("/transactions"):
                transactions = UserManager.get_user_transactions(user_data["customer_id"])
                message = TelegramHandler.format_transaction_message(transactions)
                TelegramHandler.send_message(chat_id, message)
                return {"status": "transactions_fetched"}

            if text.startswith("/query"):
                query = text.replace("/query", "").strip()
                if query:
                    # Get user context for the query
                    context = {
                        "user_info": {
                            "name": user_data["name"],
                            "account_number": user_data["account_number"],
                            "account_type": user_data["account_type"],
                            "city": user_data["account_city"]
                        },
                        "transactions": UserManager.get_user_transactions(user_data["customer_id"])
                    }
                    
                    response = call_gemini_api({
                        "query": query,
                        "context": context
                    })
                    TelegramHandler.send_message(chat_id, response)
                    return {"status": "query_processed"}
                else:
                    TelegramHandler.send_message(chat_id, 
                        "Please provide your query after /query command")
                    return {"status": "empty_query"}

        # Handle unauthorized access
        TelegramHandler.send_message(chat_id, 
            "Please authenticate first using /start command")
        return {"status": "unauthorized"}

    except Exception as e:
        print(f"Error in webhook: {str(e)}")
        traceback.print_exc()
        TelegramHandler.send_message(chat_id, 
            "An error occurred. Please try again.")
        return {"status": "error"}

# Session management functions
def get_user_state(chat_id: int) -> str:
    with DatabaseManager.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT state FROM user_sessions 
                WHERE chat_id = %s AND expires_at > NOW()
            """, (chat_id,))
            result = cursor.fetchone()
            return result[0] if result else None

def set_user_state(chat_id: int, state: str):
    with DatabaseManager.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO user_sessions (chat_id, state, expires_at)
                VALUES (%s, %s, NOW() + INTERVAL '1 hour')
                ON CONFLICT (chat_id) 
                DO UPDATE SET state = EXCLUDED.state, 
                             expires_at = NOW() + INTERVAL '1 hour'
            """, (chat_id, state))
        conn.commit()

def store_temp_data(chat_id: int, key: str, value: str):
    with DatabaseManager.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO temp_data (chat_id, key, value, expires_at)
                VALUES (%s, %s, %s, NOW() + INTERVAL '5 minutes')
                ON CONFLICT (chat_id, key) 
                DO UPDATE SET value = EXCLUDED.value, 
                             expires_at = NOW() + INTERVAL '5 minutes'
            """, (chat_id, key, value))
        conn.commit()

def get_temp_data(chat_id: int, key: str) -> str:
    with DatabaseManager.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT value FROM temp_data 
                WHERE chat_id = %s AND key = %s AND expires_at > NOW()
            """, (chat_id, key))
            result = cursor.fetchone()
            return result[0] if result else None

def store_user_session(chat_id: int, user_data: dict):
    with DatabaseManager.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO user_sessions (chat_id, user_data, expires_at)
                VALUES (%s, %s, NOW() + INTERVAL '1 day')
                ON CONFLICT (chat_id) 
                DO UPDATE SET user_data = EXCLUDED.user_data, 
                             expires_at = NOW() + INTERVAL '1 day'
            """, (chat_id, json.dumps(user_data)))
        conn.commit()

def get_user_session(chat_id: int) -> dict:
    with DatabaseManager.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT user_data FROM user_sessions 
                WHERE chat_id = %s AND expires_at > NOW()
            """, (chat_id, ))
            result = cursor.fetchone()
            return json.loads(result[0]) if result else None

def clear_user_session(chat_id: int):
    with DatabaseManager.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                DELETE FROM user_sessions WHERE chat_id = %s
            """, (chat_id,))
            cursor.execute("""
                DELETE FROM temp_data WHERE chat_id = %s
            """, (chat_id,))
        conn.commit()

def verify_password(input_password: str, stored_password: str) -> bool:
    return input_password == stored_password  # Replace with proper password hashing

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
