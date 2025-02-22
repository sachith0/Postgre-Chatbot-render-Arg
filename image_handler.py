from fastapi import APIRouter, HTTPException, UploadFile, File
import os
import io
import logging
import requests
import psycopg2
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
from auth_handler import user_sessions  # Import session storage

router = APIRouter()

# Load Environment Variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
DATABASE_URL = os.getenv("DATABASE_URL")
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "agr_logs.log")

# Configure Logging
logging.basicConfig(filename=LOG_FILE_PATH, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Database Connection Function
def get_db_connection():
    """Establish a connection to PostgreSQL."""
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logging.error(f"Database connection failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Database connection error.")

# Extract Text from Image (OCR)
def extract_text_from_image(image_bytes: bytes) -> str:
    """Extracts text from an image using OCR with preprocessing."""
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("L")  # Convert to grayscale
        image = ImageEnhance.Contrast(image).enhance(2.0).filter(ImageFilter.SHARPEN)
        return pytesseract.image_to_string(image, lang="hin+eng+kan+tam+ben").strip()
    except Exception as e:
        logging.error(f"Image processing error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Image processing error: {str(e)}")

# Detect Transaction-Related Queries
def is_transaction_query(text: str) -> bool:
    """Check if the extracted text contains transaction-related keywords."""
    keywords = {"transaction", "amount", "balance", "statement", "credited", "debited"}
    return any(word in text.lower() for word in keywords)

# Fetch Last Transaction from Database
def fetch_transaction_details():
    """Fetch the latest transaction details from the PostgreSQL database."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            SELECT transaction_id, amount, transaction_type, date_time, method 
            FROM transactions 
            ORDER BY date_time DESC 
            LIMIT 1;
        """
        cursor.execute(query)
        last_transaction = cursor.fetchone()
        cursor.close()
        conn.close()

        return {
            "transaction_id": last_transaction[0],
            "amount": last_transaction[1],
            "transaction_type": last_transaction[2],
            "date_time": last_transaction[3],
            "method": last_transaction[4]
        } if last_transaction else "No transactions found."
    except Exception as e:
        logging.error(f"Database query error: {str(e)}")
        return f"Error querying database: {str(e)}"

# Main API Endpoint
@router.post("/image-to-chatbot")
async def image_to_chatbot(image_file: UploadFile = File(...)):
    """Processes an image, extracts text, checks for transactions, and queries the AI assistant."""
    # Validate User Session
    if not user_sessions:
        raise HTTPException(status_code=403, detail="No active session. Please log in first.")
    
    last_logged_in_user = list(user_sessions.keys())[-1]
    user_data = user_sessions[last_logged_in_user]

    # Process Image & Extract Text
    extracted_text = extract_text_from_image(await image_file.read())
    
    # Check for transaction-related query
    transaction_details = fetch_transaction_details() if is_transaction_query(extracted_text) else "Not a transaction-related query."

    # Prepare API Request for Gemini
    payload = {
        "contents": [{
            "parts": [{
                "text": f"""
                You are a banking assistant. Answer concisely.

                **User Details:** {user_data['customer']}
                **Last Transaction:** {transaction_details}

                Here is a scanned bank document. Extract transaction details:

                **Extracted Text:**
                {extracted_text}
                """
            }]
        }]
    }

    # Send API Request to Gemini
    try:
        response = requests.post(GEMINI_API_URL, headers={"Content-Type": "application/json"}, json=payload)
        response.raise_for_status()
        llm_response = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
    except requests.exceptions.RequestException as e:
        logging.error(f"Gemini API request failed: {str(e)}")
        llm_response = f"LLM API Error: {str(e)}"

    # Return Final Response
    return {
        "extracted_text": extracted_text,
        "database_response": transaction_details,
        "llm_response": llm_response
    }
