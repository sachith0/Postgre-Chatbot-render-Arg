from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Transaction(Base):
    __tablename__ = 'transactions'

    transaction_id = Column(Integer, primary_key=True)
    customer_id = Column(Integer)
    account_number = Column(String)
    date_time = Column(String)
    amount = Column(Float)
    transaction_type = Column(String)
    method = Column(String)
    description = Column(String)
    balance_after_transaction = Column(Float)  # Ensure it matches the DB column name exactly
