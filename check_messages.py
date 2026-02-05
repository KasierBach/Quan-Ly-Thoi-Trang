from run import app
from app.database import get_db_connection
import json

with app.app_context():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, content, message_type, session_id, conversation_id, created_at FROM Messages WHERE message_type = 'image' ORDER BY created_at DESC LIMIT 5")
    rows = cursor.fetchall()
    
    messages = []
    for row in rows:
        messages.append({
            'id': row.id,
            'content': row.content,
            'message_type': row.message_type,
            'session_id': row.session_id,
            'conversation_id': row.conversation_id,
            'created_at': row.created_at.isoformat() if row.created_at else None
        })

    print(json.dumps(messages, indent=4))
    conn.close()
