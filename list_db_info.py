from app import create_app
from app.database import get_db_connection

app = create_app()
with app.app_context():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # List all views
        cursor.execute("SELECT table_name FROM information_schema.views WHERE table_schema = 'public'")
        views = [r[0] for r in cursor.fetchall()]
        print(f"Views in public schema: {views}")
        
        # Try to query conversations directly
        cursor.execute("SELECT * FROM Conversations LIMIT 1")
        conv = cursor.fetchone()
        if conv:
            # Get column names
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'conversations'")
            cols = [r[0] for r in cursor.fetchall()]
            print(f"Conversations column names: {cols}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
