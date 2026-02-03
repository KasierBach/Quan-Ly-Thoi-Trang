from app import create_app
from app.database import get_db_connection
import os

app = create_app()

def migrate():
    with app.app_context():
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            with open('migrate_chat.sql', 'r', encoding='utf-8') as f:
                sql = f.read()
                cur.execute(sql)
            conn.commit()
            print("Migration successful")
        except Exception as e:
            conn.rollback()
            print(f"Migration failed: {e}")
        finally:
            cur.close()
            conn.close()

if __name__ == "__main__":
    migrate()
