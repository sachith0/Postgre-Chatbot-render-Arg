from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import SessionLocal, User, Transaction
from fastapi.encoders import jsonable_encoder
import datetime
import traceback

router = APIRouter()

# In-memory session storage (For demonstration, use Redis in production)
user_sessions = {}

class LoginRequest(BaseModel):
    account_number: str
    password: str

# Dependency: Get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Authenticates user and stores session data."""
    try:
        # ✅ Fetch user by account number
        user = db.query(User).filter(User.account_number == request.account_number.strip()).first()
        
        if not user or str(user.password).strip() != str(request.password).strip():
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # ✅ Fetch all transactions for the user
        transactions = db.query(Transaction).filter(Transaction.account_number == user.account_number).all()
        
        # ✅ Store user session data
        user_sessions[user.account_number] = {
            "customer": jsonable_encoder(user),
            "transactions": jsonable_encoder(transactions),
            "login_time": datetime.datetime.now().isoformat()
        }
        
        return {
            "status": "success",
            "message": f"Welcome {user.name}!",
            "user_data": user_sessions[user.account_number]
        }
    
    except Exception as e:
        error_details = traceback.format_exc()  # Get full error trace
        print(f"❌ ERROR in /login:\n{error_details}")  # Log full error
        raise HTTPException(status_code=500, detail="Internal Server Error")
