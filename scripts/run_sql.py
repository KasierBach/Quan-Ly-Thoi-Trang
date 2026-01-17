import psycopg2
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def execute_sql(sql_file):
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("Error: DATABASE_URL not found in environment")
        return
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        
    if not os.path.exists(sql_file):
        print(f"Error: SQL file '{sql_file}' not found")
        return

    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        cursor = conn.cursor()
        
        print(f"--- Executing {sql_file} ---")
        with open(sql_file, "r", encoding="utf-8") as f:
            sql = f.read()
            cursor.execute(sql)
            
        print("Success: SQL execution completed!")
        conn.close()
    except Exception as e:
        print(f"Error executing SQL: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_sql.py <path_to_sql_file>")
        print("Example: python run_sql.py data/postgresql_data_full.sql")
    else:
        execute_sql(sys.argv[1])
