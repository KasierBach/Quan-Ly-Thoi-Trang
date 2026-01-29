
from app.database import get_db_connection

class ChatService:
    @staticmethod
    def send_message(sender_type, content, session_id, user_id=None):
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO messages (sender_type, content, session_id, user_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id, created_at
            """, (sender_type, content, session_id, user_id))
            conn.commit()
            result = cur.fetchone()
            return result
        except Exception as e:
            conn.rollback()
            print(f"Error sending message: {e}")
            return None
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def get_messages(session_id, user_id=None, limit=50):
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # Ưu tiên lấy theo user_id nếu có, fallback sang session_id
            if user_id:
                query = """
                    SELECT * FROM messages 
                    WHERE user_id = %s OR session_id = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                """
                params = (user_id, session_id, limit)
            else:
                query = """
                    SELECT * FROM messages 
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                """
                params = (session_id, limit)
                
            cur.execute(query, params)
            rows = cur.fetchall()
            messages = []
            for row in rows:
                messages.append({
                    'id': row['id'],
                    'sender_type': row['sender_type'],
                    'content': row['content'],
                    'created_at': row['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
                    'is_read': row['is_read']
                })
            return messages
        except Exception as e:
            print(f"Error getting messages: {e}")
            return []
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def get_all_conversations():
        """Dành cho admin để xem tất cả hội thoại"""
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # Lấy tin nhắn mới nhất của mỗi session/user
            query = """
                SELECT DISTINCT ON (session_id) 
                    session_id, user_id, content, created_at, sender_type
                FROM messages
                ORDER BY session_id, created_at DESC
            """
            cur.execute(query)
            rows = cur.fetchall()
            conversations = []
            for row in rows:
                conversations.append({
                    'session_id': row['session_id'],
                    'user_id': row['user_id'],
                    'last_message': row['content'],
                    'last_time': row['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
                    'last_sender': row['sender_type']
                })
            # Sort by time
            conversations.sort(key=lambda x: x['last_time'], reverse=True)
            return conversations
        except Exception as e:
            print(f"Error getting conversations: {e}")
            return []
        finally:
            cur.close()
            conn.close()
