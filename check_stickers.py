from app import create_app
from app.database import get_db_connection

app = create_app()
with app.app_context():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, content, message_type, created_at FROM Messages ORDER BY created_at DESC LIMIT 5")
    for row in cur.fetchall():
        print(f"ID: {row.id}, Type: {row.message_type}, Content: {row.content}")
    conn.close()
