import os
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from auth_handler import user_sessions
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

router = APIRouter()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

class QueryRequest(BaseModel):
    user_input: str  # User's query

@router.post("/process-query")
def process_query(request: QueryRequest):
    """Handles user queries and retrieves transaction details if relevant"""
    if not user_sessions:
        raise HTTPException(status_code=403, detail="No active session. Please log in first.")

    # Get the last logged-in user's data
    last_logged_in_user = list(user_sessions.keys())[-1]
    user_data = user_sessions.get(last_logged_in_user, {})

    # Retrieve transaction details
    transactions = user_data.get("transactions", [])
    last_transaction = transactions[-1] if transactions else None

    transaction_details = (
        f"Transaction ID: {last_transaction['transaction_id']}, Amount: ₹{last_transaction['amount']}, "
        f"Type: {last_transaction['transaction_type']}, Date: {last_transaction['date_time']}, "
        f"Method: {last_transaction['method']}"
        if last_transaction else "No transactions found."
    )

    # Construct prompt for the Gemini API
    prompt_text = f"""
    You are a **smart banking assistant**. Your task is to answer user queries accurately.

    **User Query:** {request.user_input}  
    **User Details:** {user_data.get('customer', 'Unknown User')}

    {"**Last Transaction:** " + transaction_details if last_transaction else ""}

    **Response Guidelines:**
    1. Answer clearly and concisely.
    2. If the query is about transactions, use the stored session data.
    3. If the query is general (e.g., "How do I open an account?"), provide relevant information.
    4. Ensure the response is formatted properly.

    **Response Format:**  
    - **Greeting**
    - **Acknowledgment**
    - **Relevant Answer**
    - **Offer Further Assistance**
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    headers = {"Content-Type": "application/json"}

    # Send request to Gemini API
    response = requests.post(GEMINI_API_URL, headers=headers, json=payload)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Error in LLM API request.")
    
    try:
        api_response = response.json()
        generated_text = api_response["candidates"][0]["content"]["parts"][0]["text"]
        return {"response": generated_text}
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=500, detail="Invalid response format from Gemini API.")
