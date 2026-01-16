
import psycopg2
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

def debug_dashboard():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Check vw_MonthlyRevenue definition
    print("--- View Definition ---")
    cur.execute("SELECT view_definition FROM information_schema.views WHERE table_name = 'vw_monthlyrevenue'")
    view_def = cur.fetchone()
    if view_def:
        print(view_def[0])
    else:
        print("View definition not found in information_schema")

    # Check vw_MonthlyRevenue Content
    print("\n--- vw_MonthlyRevenue Content ---")
    cur.execute('SELECT * FROM vw_MonthlyRevenue ORDER BY Year DESC, Month DESC')
    rows = cur.fetchall()
    
    # Get column names
    colnames = [desc[0] for desc in cur.description]
    print(f"Columns: {colnames}")
    
    for row in rows:
        print(dict(zip(colnames, row)))
        
    # Check current time in DB
    print("\n--- Current DB Time ---")
    cur.execute("SELECT CURRENT_TIMESTAMP, EXTRACT(YEAR FROM CURRENT_TIMESTAMP), EXTRACT(MONTH FROM CURRENT_TIMESTAMP)")
    print(cur.fetchone())

    # Check actual orders in Jan 2026
    print("\n--- Orders in Jan 2026 ---")
    cur.execute("SELECT COUNT(*), SUM(TotalAmount) FROM Orders WHERE EXTRACT(YEAR FROM OrderDate) = 2026 AND EXTRACT(MONTH FROM OrderDate) = 1")
    print(cur.fetchone())

    conn.close()

if __name__ == "__main__":
    debug_dashboard()
