
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

def load_data():
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        sql_file_path = os.path.join(r"d:\SQL\dbmstestfileshit\thua 2.0\data", "postgresql_data_full.sql")
        
        print(f"Reading SQL file: {sql_file_path}")
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
            
        print("Executing SQL commands...")
        cur.execute(sql_content)
        
        conn.commit()
        print("Data loaded successfully!")
        
    except Exception as e:
        error_msg = f"Error loading data: {e}"
        print(error_msg)
        with open("load_error.txt", "w", encoding='utf-8') as f:
            f.write(str(e))
            if hasattr(e, 'pgerror'):
                f.write("\nPG ERROR:\n" + str(e.pgerror))
            if hasattr(e, 'diag'):
                f.write("\nDIAG:\n" + str(e.diag.message_primary))
                f.write("\nDETAIL:\n" + str(e.diag.message_detail))
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    load_data()
