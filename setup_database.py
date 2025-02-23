import os
import json
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import psycopg2
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

class DatabaseManager:
    def __init__(self):
        self.engine = create_engine(DATABASE_URL)
        self.conn = None

    def connect(self):
        try:
            self.conn = psycopg2.connect(DATABASE_URL)
            print("✅ Connected to PostgreSQL database.")
            return self.conn
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            raise

    def setup_tables(self):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    # Create users table with ID column
                    cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        customer_id VARCHAR(20),
                        name VARCHAR(100) NOT NULL,
                        account_number VARCHAR(20) UNIQUE NOT NULL,
                        ifsc_code VARCHAR(11) NOT NULL,
                        account_city VARCHAR(50),
                        account_type VARCHAR(20),
                        status VARCHAR(20) DEFAULT 'Active',
                        contact VARCHAR(15) NOT NULL,
                        password VARCHAR(100) DEFAULT '1234567',
                        created_at DATE,
                        id SERIAL,
                        PRIMARY KEY (customer_id)
                    );
                    """)

                    # Create transactions table
                    cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        transaction_id VARCHAR(20) PRIMARY KEY,
                        customer_id VARCHAR(20) REFERENCES users(customer_id),
                        account_number VARCHAR(20) NOT NULL,
                        date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        amount INTEGER NOT NULL,
                        transaction_type VARCHAR(20) CHECK (transaction_type IN ('Debit', 'Credit')),
                        method VARCHAR(50) NOT NULL,
                        description TEXT,
                        balance_after_transaction INTEGER NOT NULL
                    );
                    """)

                    # Create queries table
                    cursor.execute("""
                    CREATE TABLE IF NOT EXISTS queries (
                        id SERIAL PRIMARY KEY,
                        user_id VARCHAR(20),
                        query TEXT
                    );
                    """)

                    # Create user sessions table
                    cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_sessions (
                        chat_id BIGINT PRIMARY KEY,
                        user_data JSONB,
                        state VARCHAR(50),
                        expires_at TIMESTAMP NOT NULL
                    );
                    """)

                    # Create temporary data table
                    cursor.execute("""
                    CREATE TABLE IF NOT EXISTS temp_data (
                        chat_id BIGINT,
                        key VARCHAR(50),
                        value TEXT,
                        expires_at TIMESTAMP NOT NULL,
                        PRIMARY KEY (chat_id, key)
                    );
                    """)

                    conn.commit()
                    print("✅ All tables created successfully!")

        except Exception as e:
            print(f"❌ Error creating tables: {e}")
            raise

    def load_sample_data(self):
        try:
            # Load and process customer data
            customers_df = pd.read_csv("1000_customers_data.csv")
            if not customers_df.empty:
                # Set default password
                if 'password' not in customers_df.columns:
                    customers_df['password'] = '1234567'
                if 'status' not in customers_df.columns:
                    customers_df['status'] = 'Active'
                
                customers_df.to_sql(
                    'users',
                    self.engine,
                    if_exists='append',
                    index=False,
                    method='multi'
                )
                print(f"✅ Inserted {len(customers_df)} customers.")
            
            # Load and process transaction data
            transactions_df = pd.read_csv("100000_transactiondata.csv")
            if not transactions_df.empty:
                transactions_df.to_sql(
                    'transactions',
                    self.engine,
                    if_exists='append',
                    index=False,
                    method='multi'
                )
                print(f"✅ Inserted {len(transactions_df)} transactions.")

        except Exception as e:
            print(f"❌ Error loading sample data: {e}")
            raise

class SessionManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def store_session(self, chat_id: int, user_data: dict, state: str = "authenticated"):
        with self.db_manager.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_sessions (chat_id, user_data, state, expires_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (chat_id) 
                    DO UPDATE SET 
                        user_data = EXCLUDED.user_data,
                        state = EXCLUDED.state,
                        expires_at = EXCLUDED.expires_at
                """, (
                    chat_id,
                    json.dumps(user_data),
                    state,
                    datetime.now() + timedelta(hours=1)
                ))
                conn.commit()

    def get_session(self, chat_id: int):
        with self.db_manager.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT user_data, state
                    FROM user_sessions 
                    WHERE chat_id = %s AND expires_at > NOW()
                """, (chat_id,))
                result = cursor.fetchone()
                if result:
                    return {
                        'user_data': json.loads(result[0]),
                        'state': result[1]
                    }
                return None

class UserManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def verify_user(self, account_number: str, password: str):
        with self.db_manager.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT customer_id, name, password, account_number, 
                           account_type, account_city, status
                    FROM users 
                    WHERE account_number = %s AND status = 'Active'
                """, (account_number,))
                user = cursor.fetchone()
                
                if user and user[2] == password:  # Simple password comparison
                    return {
                        'customer_id': user[0],
                        'name': user[1],
                        'account_number': user[3],
                        'account_type': user[4],
                        'account_city': user[5],
                        'status': user[6]
                    }
                return None

    def get_transactions(self, customer_id: str, limit: int = 5):
        with self.db_manager.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT transaction_id, date_time, amount, 
                           transaction_type, method, description,
                           balance_after_transaction
                    FROM transactions 
                    WHERE customer_id = %s 
                    ORDER BY date_time DESC 
                    LIMIT %s
                """, (customer_id, limit))
                return cursor.fetchall()

def main():
    # Initialize database manager
    db_manager = DatabaseManager()
    
    # Setup database tables
    db_manager.setup_tables()
    
    # Load sample data
    db_manager.load_sample_data()
    
    print("✅ Database setup completed successfully!")

if __name__ == "__main__":
    main()
