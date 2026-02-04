from app import create_app
from app.database import get_db_connection
import json

app = create_app()
with app.app_context():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check First conversation from the view
        cursor.execute("SELECT * FROM vw_ConversationSummary LIMIT 1")
        res = cursor.fetchone()
        if res:
            conv = dict(res)
            print("vw_ConversationSummary result keys:")
            print(list(conv.keys()))
        else:
            print("No data in vw_ConversationSummary")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
