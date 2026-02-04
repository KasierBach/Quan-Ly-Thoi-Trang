from app import create_app
from app.database import get_db_connection

app = create_app()
with app.app_context():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check Conversations table
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'conversations'")
        cols = [r[0] for r in cursor.fetchall()]
        print(f"Conversations columns: {cols}")
        
        # Check vw_ConversationSummary
        try:
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'vw_conversationsummary'")
            cols_vw = [r[0] for r in cursor.fetchall()]
            print(f"vw_ConversationSummary columns: {cols_vw}")
        except:
            print("vw_ConversationSummary not found or error")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
