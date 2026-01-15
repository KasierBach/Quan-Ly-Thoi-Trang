import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

try:
    conn = psycopg2.connect(DATABASE_URL)
    print("Connection successful!")
    cur = conn.cursor()
    
    tables = ['Categories', 'Products', 'Customers', 'Reviews', 'ProductComments', 'OrderDetails', 'Orders']
    print("Record counts per table:")
    for table in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            print(f"{table}: {count}")
        except Exception as e:
            print(f"{table}: Error {e}")
            conn.rollback()
    
    # Distribution of Reviews
    cur.execute("SELECT ProductID, COUNT(*) FROM Reviews GROUP BY ProductID ORDER BY ProductID")
    print("\nReviews per ProductID:")
    for row in cur.fetchall():
        print(f"Product {row[0]}: {row[1]} reviews")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
