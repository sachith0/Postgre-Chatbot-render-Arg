import os
import time
import logging
import psycopg2
import requests
import traceback
from fastapi import FastAPI, Request, HTTPException, Depends
from dotenv import load_dotenv
from starlette.responses import JSONResponse, Response
from prometheus_client import Counter, Histogram, generate_latest
from auth_handler import router as auth_router
from query_handler import router as query_router
from speech_handler import router as speech_router
from image_handler import router as image_router

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")


# Validate environment variables
if not GEMINI_API_KEY:
    raise ValueError("❌ GEMINI_API_KEY is missing in .env file")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL is missing in .env file")

print(f"🔹 Using Database: PostgreSQL")

# Initialize FastAPI
app = FastAPI()

# Configure logging
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Prometheus Metrics
REQUEST_COUNT = Counter("api_requests_total", "Total API requests received")
REQUEST_LATENCY = Histogram("api_request_latency_seconds", "API request latency")

# Middleware: Log Requests & Track Response Time
@app.middleware("http")
async def log_requests(request: Request, call_next):
    REQUEST_COUNT.inc()
    start_time = time.time()
    logger.info(f"📩 Received {request.method} {request.url}")
    
    try:
        response = await call_next(request)
    except Exception as e:
        logger.error(f"❌ API Error: {str(e)}", exc_info=True)
        return JSONResponse(content={"error": "Internal Server Error"}, status_code=500)

    process_time = time.time() - start_time
    REQUEST_LATENCY.observe(process_time)
    logger.info(f"✅ Response: {response.status_code} | ⏱️ Time: {process_time:.4f} sec")
    return response

# Database Connection Function
def get_db_connection():
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"❌ Database connection error: {str(e)}")
        raise HTTPException(status_code=500, detail="Database connection failed")

# Automate Database Setup
def setup_database():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

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
        cursor.close()
        conn.close()
        print("✅ Database setup complete!")

    except Exception as e:
        logger.error(f"❌ Database setup failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Database setup failed")

setup_database()

# Expose Metrics
@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")

# Include Feature Routers
app.include_router(auth_router)
app.include_router(query_router)
app.include_router(speech_router)
app.include_router(image_router)

# Automated Gemini API Call with Retry Logic
def call_gemini_api(payload, retries=3):
    headers = {"Content-Type": "application/json"}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    for attempt in range(retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"⚠️ Gemini API failure (attempt {attempt+1}): {response.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Request failed (attempt {attempt+1}): {str(e)}")
        time.sleep(2 ** attempt)
    raise HTTPException(status_code=500, detail="Gemini API request failed after retries")

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"❌ Error on {request.method} {request.url}: {exc}")
    traceback.print_exc()
    return JSONResponse(content={"error": "Internal Server Error"}, status_code=500)

# Start API Server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
