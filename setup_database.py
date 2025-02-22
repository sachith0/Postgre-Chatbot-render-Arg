from sqlalchemy import create_engine, text
import pandas as pd
import os
from dotenv import load_dotenv
import sqlite3

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL is not set. Please check your .env file.")

# Connect to PostgreSQL
try:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        print("✅ Connected to PostgreSQL database.")
except Exception as e:
    raise ConnectionError(f"❌ Database connection failed: {e}")

# Define Table Creation Queries
users_table_query = """
CREATE TABLE IF NOT EXISTS users (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    account_number TEXT UNIQUE NOT NULL,
    ifsc_code TEXT NOT NULL,
    account_city TEXT,
    account_type TEXT,
    status TEXT,
    contact TEXT NOT NULL,
    password TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

transactions_table_query = """
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES users(customer_id) ON DELETE CASCADE,
    account_number TEXT NOT NULL,
    date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    amount INTEGER CHECK (amount >= 0),
    transaction_type TEXT CHECK (transaction_type IN ('debit', 'credit')),
    method TEXT NOT NULL,
    description TEXT,
    balance_after_transaction INTEGER NOT NULL
);
"""

# Execute Queries
try:
    with engine.connect() as connection:
        connection.execute(text(users_table_query))
        connection.execute(text(transactions_table_query))
        print("✅ Tables created successfully!")
except Exception as e:
    raise RuntimeError(f"❌ Error creating tables: {e}")

# Load Data from CSV
CUSTOMERS_CSV = "1000_customers_data.csv"
TRANSACTIONS_CSV = "100000_transactiondata.csv"

try:
    customers_df = pd.read_csv(CUSTOMERS_CSV)
    if not customers_df.empty:
        customers_df.to_sql("users", engine, if_exists="append", index=False, method="multi")
        print(f"✅ Inserted {len(customers_df)} customers.")
    else:
        print("⚠️ Customers CSV is empty. No data inserted.")
except Exception as e:
    print(f"❌ Error inserting customers data: {e}")

try:
    transactions_df = pd.read_csv(TRANSACTIONS_CSV)
    if not transactions_df.empty:
        transactions_df.to_sql("transactions", engine, if_exists="append", index=False, method="multi")
        print(f"✅ Inserted {len(transactions_df)} transactions.")
    else:
        print("⚠️ Transactions CSV is empty. No data inserted.")
except Exception as e:
    print(f"❌ Error inserting transactions data: {e}")

# SQLite Database Setup
DB_PATH = "banking_data.db"

try:
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()

    # Create 'users' table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        customer_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        account_number TEXT UNIQUE NOT NULL,
        ifsc_code TEXT NOT NULL,
        account_city TEXT,
        account_type TEXT,
        status TEXT,
        contact TEXT NOT NULL,
        password TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Create 'transactions' table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        transaction_id TEXT PRIMARY KEY,
        customer_id TEXT REFERENCES users(customer_id) ON DELETE CASCADE,
        account_number TEXT NOT NULL,
        date_time TEXT DEFAULT CURRENT_TIMESTAMP,
        amount INTEGER CHECK (amount >= 0),
        transaction_type TEXT CHECK (transaction_type IN ('debit', 'credit')),
        method TEXT NOT NULL,
        description TEXT,
        balance_after_transaction INTEGER NOT NULL
    )
    ''')
    
    db.commit()
    print("✅ SQLite tables created successfully.")

    # Insert customer data into SQLite
    customers_df = pd.read_csv(CUSTOMERS_CSV)
    if not customers_df.empty:
        customers_df.to_sql("users", db, if_exists="replace", index=False)
        print(f"✅ Inserted {len(customers_df)} customers into SQLite.")
    else:
        print("⚠️ Customers CSV is empty. No data inserted into SQLite.")

    # Insert transaction data into SQLite
    transactions_df = pd.read_csv(TRANSACTIONS_CSV)
    if not transactions_df.empty:
        transactions_df.to_sql("transactions", db, if_exists="replace", index=False)
        print(f"✅ Inserted {len(transactions_df)} transactions into SQLite.")
    else:
        print("⚠️ Transactions CSV is empty. No data inserted into SQLite.")
    
    db.close()
    print("✅ SQLite database setup completed successfully.")

except Exception as e:
    print(f"❌ Error setting up SQLite database: {e}")
