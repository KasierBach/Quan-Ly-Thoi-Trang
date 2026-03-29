from .base_service import BaseService
from datetime import datetime
from typing import Optional, List, Dict, Any

class ConversationService(BaseService):
    @staticmethod
    def create_conversation(conversation_type: str = 'support', name: Optional[str] = None, 
                            created_by: Optional[int] = None, avatar_url: Optional[str] = None) -> Dict[str, Any]:
        """Create a new conversation (private, group, or support)."""
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO Conversations (type, name, created_by, avatar_url)
                    VALUES (%s, %s, %s, %s) RETURNING id
                ''', (conversation_type, name, created_by, avatar_url))
                conversation_id = cursor.fetchone().id
                
                if created_by:
                    cursor.execute('''
                        INSERT INTO Participants (conversation_id, user_id, role)
                        VALUES (%s, %s, %s)
                    ''', (conversation_id, created_by, 'admin'))
                
                conn.commit()
                return ConversationService.success({'id': conversation_id, 'name': name})
        except Exception as e:
            conn.rollback()
            return ConversationService.handle_error(e, "Lỗi khi tạo cuộc hội thoại")
        finally:
            conn.close()

    @staticmethod
    def get_conversation(conversation_id: int) -> Optional[Dict[str, Any]]:
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT c.*, 
                           (SELECT content FROM Messages WHERE conversation_id = c.id ORDER BY created_at DESC LIMIT 1) as last_message,
                           (SELECT created_at FROM Messages WHERE conversation_id = c.id ORDER BY created_at DESC LIMIT 1) as last_message_at
                    FROM Conversations c
                    WHERE c.id = %s
                ''', (conversation_id,))
                res = cursor.fetchone()
                if not res: return None
                
                conv = dict(res)
                for key in ['last_message_at', 'created_at', 'updated_at']:
                    if conv.get(key): conv[key] = conv[key].isoformat()
                return conv
        finally:
            conn.close()

    @staticmethod
    def get_user_conversations(user_id: int) -> List[Dict[str, Any]]:
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT c.*, p.role, p.last_read_at, p.nickname as my_nickname,
                           (SELECT content FROM Messages WHERE conversation_id = c.id ORDER BY created_at DESC LIMIT 1) as last_message,
                           (SELECT created_at FROM Messages WHERE conversation_id = c.id ORDER BY created_at DESC LIMIT 1) as last_message_at,
                           CASE WHEN c.type = 'private' THEN (
                               SELECT u.last_seen FROM Participants p2 JOIN Customers u ON p2.user_id = u.CustomerID 
                               WHERE p2.conversation_id = c.id AND p2.user_id != %s LIMIT 1
                           ) ELSE NULL END as partner_last_seen,
                           CASE WHEN c.type = 'private' THEN (
                               SELECT COALESCE(p2.nickname, u.FullName) FROM Participants p2 JOIN Customers u ON p2.user_id = u.CustomerID 
                               WHERE p2.conversation_id = c.id AND p2.user_id != %s LIMIT 1
                           ) ELSE NULL END as partner_display_name
                    FROM Conversations c
                    JOIN Participants p ON c.id = p.conversation_id
                    WHERE p.user_id = %s
                    ORDER BY last_message_at DESC NULLS LAST
                ''', (user_id, user_id, user_id))
                
                results = []
                for row in cursor.fetchall():
                    c = dict(row)
                    c['is_online'] = False
                    if c.get('partner_last_seen'):
                        if (datetime.now() - c['partner_last_seen']).total_seconds() < 300:
                            c['is_online'] = True
                        c['partner_last_seen'] = c['partner_last_seen'].isoformat()
                    if c.get('last_message_at'): c['last_message_at'] = c['last_message_at'].isoformat()
                    results.append(c)
                return results
        finally:
            conn.close()

    @staticmethod
    def get_guest_conversations() -> List[Dict[str, Any]]:
        """Fetch unique guest sessions for admin display."""
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT session_id, MAX(created_at) as last_time,
                           (SELECT content FROM Messages m2 WHERE m2.session_id = m.session_id ORDER BY created_at DESC LIMIT 1) as last_message
                    FROM Messages m
                    WHERE session_id IS NOT NULL AND conversation_id IS NULL
                    GROUP BY session_id
                    ORDER BY last_time DESC
                ''')
                return [{
                    'id': r.session_id, 'session_id': r.session_id, 'name': f"Khách {r.session_id[:8]}",
                    'type': 'support', 'last_message': r.last_message,
                    'last_message_at': r.last_time.isoformat() if r.last_time else None,
                    'is_online': True
                } for r in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_direct_conversation(uid1, uid2):
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT c.id FROM Conversations c
                    JOIN Participants p1 ON c.id = p1.conversation_id
                    JOIN Participants p2 ON c.id = p2.conversation_id
                    WHERE c.type = 'private' AND p1.user_id = %s AND p2.user_id = %s LIMIT 1
                ''', (uid1, uid2))
                return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def add_participant(cid, uid, role='member'):
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('INSERT INTO Participants (conversation_id, user_id, role) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING', (cid, uid, role))
                conn.commit()
                return ConversationService.success()
        except Exception as e:
            conn.rollback()
            return ConversationService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def get_participants(cid):
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT p.user_id as id, c.FullName as name, c.Email as email, p.role, p.nickname, p.is_muted
                    FROM Participants p JOIN Customers c ON p.user_id = c.CustomerID
                    WHERE p.conversation_id = %s
                ''', (cid,))
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def search_users(exclude_uid, query, limit=10):
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT CustomerID as id, FullName as name, Email as email, avatar_url as avatar
                    FROM Customers WHERE CustomerID != %s AND (FullName ILIKE %s OR Email ILIKE %s) LIMIT %s
                ''', (exclude_uid, f'%{query}%', f'%{query}%', limit))
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def leave_conversation(cid, uid):
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM Participants WHERE conversation_id = %s AND user_id = %s', (cid, uid))
                cursor.execute('SELECT COUNT(*) FROM Participants WHERE conversation_id = %s', (cid,))
                if cursor.fetchone()[0] == 0:
                    cursor.execute('DELETE FROM Conversations WHERE id = %s', (cid,))
                conn.commit()
                return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    @staticmethod
    def mark_as_read(cid, uid):
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE Participants SET last_read_at = NOW() WHERE conversation_id = %s AND user_id = %s', (cid, uid))
                conn.commit()
                return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    @staticmethod
    def update_conversation_settings(conversation_id: int, settings: Dict[str, Any]) -> bool:
        """Update global conversation settings like theme_color or default_emoji."""
        if not settings: return False
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            fields = []
            values = []
            for k, v in settings.items():
                if k in ['theme_color', 'default_emoji', 'name', 'avatar_url']:
                    fields.append(f"{k} = %s")
                    values.append(v)
            
            if not fields: return False
            values.append(conversation_id)
            
            cursor.execute(f'''
                UPDATE Conversations 
                SET {", ".join(fields)}, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', tuple(values))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    @staticmethod
    def update_participant_settings(conversation_id: int, user_id: int, settings: Dict[str, Any]) -> bool:
        """Update participant-specific settings like nickname or is_muted."""
        if not settings: return False
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            fields = []
            values = []
            for k, v in settings.items():
                if k in ['nickname', 'is_muted', 'role']:
                    fields.append(f"{k} = %s")
                    values.append(v)
            
            if not fields: return False
            values.extend([conversation_id, user_id])
            
            cursor.execute(f'''
                UPDATE Participants 
                SET {", ".join(fields)}
                WHERE conversation_id = %s AND user_id = %s
            ''', tuple(values))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

