import os
from sqlalchemy import create_engine, Column, String, Integer, TIMESTAMP, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# ✅ Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL is not set. Please check your .env file.")

# ✅ Connect to PostgreSQL
engine = create_engine(DATABASE_URL, echo=True)

# ✅ Set up SQLAlchemy Session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ✅ Define Models
class User(Base):
    __tablename__ = "users"
    
    customer_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    account_number = Column(String, unique=True, nullable=False)
    ifsc_code = Column(String, nullable=False)
    account_city = Column(String)
    account_type = Column(String)
    status = Column(String)
    contact = Column(String, nullable=False)
    password = Column(String, nullable=False)
    created_at = Column(TIMESTAMP, server_default="CURRENT_TIMESTAMP")

class Transaction(Base):
    __tablename__ = "transactions"
    
    transaction_id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey("users.customer_id", ondelete="CASCADE"))
    account_number = Column(String, nullable=False)
    date_time = Column(TIMESTAMP, server_default="CURRENT_TIMESTAMP")
    amount = Column(Integer, nullable=False)
    transaction_type = Column(String, nullable=False)
    method = Column(String, nullable=False)
    description = Column(String)
    balance_after_transaction = Column(Integer, nullable=False)

# ✅ Create Tables
Base.metadata.create_all(bind=engine)

# ✅ Dependency to get a database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
