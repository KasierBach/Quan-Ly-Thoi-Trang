
from app import create_app
import psycopg2
from app.database import get_db_connection
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

app = create_app()

def check_schema():
    with app.app_context():
        conn = get_db_connection()
        cur = conn.cursor()
        
        print("--- Conversations Table ---")
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'conversations'")
        for row in cur.fetchall():
            print(row)
            
        print("\n--- Participants Table ---")
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'participants'")
        for row in cur.fetchall():
            print(row)
            
        print("\n--- Customers Table ---")
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'customers'")
        for row in cur.fetchall():
            print(row)
            
        # Check Participants Unique Constraint
        print("\n--- Participants Constraints ---")
        cur.execute("""
            SELECT conname, pg_get_constraintdef(c.oid) 
            FROM pg_constraint c 
            JOIN pg_namespace n ON n.oid = c.connamespace 
            WHERE contype = 'u' AND conrelid = 'participants'::regclass
        """)
        for row in cur.fetchall():
            print(row)
            
        cur.close()
        conn.close()

if __name__ == "__main__":
    try:
        check_schema()
    except Exception as e:
        print(f"Error: {e}")
