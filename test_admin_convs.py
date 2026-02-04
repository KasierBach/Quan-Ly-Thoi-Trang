from app import create_app
from app.services.conversation_service import ConversationService
from app.database import get_db_connection
import json

app = create_app()
with app.app_context():
    uid = 1 # Admin
    is_admin = True
    
    try:
        # Part 1: Regular conversations
        conversations = ConversationService.get_user_conversations(uid)
        result = []
        for conv in conversations:
            result.append(conv)
            
        # Part 2: Admin specific guest sessions (from chat.py)
        if is_admin:
            conn = get_db_connection()
            cursor = conn.cursor()
            # Fetch all unique session_ids from messages that are NOT linked to a conversation
            cursor.execute('''
                SELECT DISTINCT session_id 
                FROM Messages 
                WHERE conversation_id IS NULL AND session_id IS NOT NULL
            ''')
            sessions = [row[0] for row in cursor.fetchall()]
            
            for sid in sessions:
                # Basic info for each guest session
                cursor.execute('''
                    SELECT content, created_at 
                    FROM Messages 
                    WHERE session_id = %s 
                    ORDER BY created_at DESC LIMIT 1
                ''', (sid,))
                last_msg = cursor.fetchone()
                
                if last_msg:
                    result.append({
                        'id': sid,
                        'name': f'Guest ({sid[:8]})',
                        'last_message': last_msg[0],
                        'last_message_at': last_msg[1].isoformat() if last_msg[1] else None,
                        'is_support': True,
                        'is_online': False # Placeholder
                    })
            conn.close()
            
        print(json.dumps({'conversations': result}, indent=2, default=str))
    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()
