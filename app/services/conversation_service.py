from .base_service import BaseService
from datetime import datetime
from typing import Optional, List, Dict, Any
import psycopg2

class ConversationService(BaseService):
    @staticmethod
    def create_conversation(
        conversation_type: str = 'support',
        name: Optional[str] = None,
        created_by: Optional[int] = None,
        avatar_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new conversation (private, group, or support)."""
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO Conversations (type, name, created_by, avatar_url)
                VALUES (%s, %s, %s, %s) RETURNING id
            ''', (conversation_type, name, created_by, avatar_url))
            conversation_id = cursor.fetchone().id
            
            # Add creator as participant in the SAME transaction
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
        """Get a single conversation by ID with summary stats."""
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM vw_ConversationSummary WHERE conversation_id = %s', (conversation_id,))
            return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def get_user_conversations(user_id: int) -> List[Dict[str, Any]]:
        """Get all conversations for a specific user."""
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT c.*, p.role, p.last_read_at,
                       (SELECT content FROM Messages WHERE conversation_id = c.id ORDER BY created_at DESC LIMIT 1) as last_message,
                       (SELECT created_at FROM Messages WHERE conversation_id = c.id ORDER BY created_at DESC LIMIT 1) as last_message_at,
                       CASE WHEN c.type = 'private' THEN (
                           SELECT u.last_seen 
                           FROM Participants p2 
                           JOIN Customers u ON p2.user_id = u.CustomerID 
                           WHERE p2.conversation_id = c.id AND p2.user_id != %s
                           LIMIT 1
                       ) ELSE NULL END as partner_last_seen
                FROM Conversations c
                JOIN Participants p ON c.id = p.conversation_id
                WHERE p.user_id = %s
                ORDER BY last_message_at DESC NULLS LAST
            ''', (user_id, user_id))
            
            conversations = []
            for row in cursor.fetchall():
                conv = dict(row)
                # Calculate is_online
                conv['is_online'] = False
                if conv.get('partner_last_seen'):
                    diff = datetime.now() - conv['partner_last_seen']
                    if diff.total_seconds() < 300: # 5 minutes
                        conv['is_online'] = True
                conversations.append(conv)
            return conversations
        finally:
            conn.close()

    @staticmethod
    def get_direct_conversation(user_id1: int, user_id2: int) -> Optional[Dict[str, Any]]:
        """Find an existing 1-on-1 private conversation between two users."""
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT c.id
                FROM Conversations c
                JOIN Participants p1 ON c.id = p1.conversation_id
                JOIN Participants p2 ON c.id = p2.conversation_id
                WHERE c.type = 'private' 
                AND p1.user_id = %s 
                AND p2.user_id = %s
                LIMIT 1
            ''', (user_id1, user_id2))
            return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def get_or_create_support_conversation(session_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Support chat handler: maintains session-level continuity."""
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            # Try to find by user_id first if logged in
            if user_id:
                cursor.execute("SELECT id FROM Conversations WHERE created_by = %s AND type = 'support' LIMIT 1", (user_id,))
                res = cursor.fetchone()
                if res: return ConversationService.success({'id': res.id})

            # Create new if not found
            name = f"Support {session_id[:8]}"
            cursor.execute('''
                INSERT INTO Conversations (type, name, created_by)
                VALUES ('support', %s, %s) RETURNING id
            ''', (name, user_id))
            conv_id = cursor.fetchone().id
            
            if user_id:
                cursor.execute('''
                    INSERT INTO Participants (conversation_id, user_id, role)
                    VALUES (%s, %s, %s)
                ''', (conv_id, user_id, 'admin'))
            
            conn.commit()
            return ConversationService.success({'id': conv_id})
        except Exception as e:
            conn.rollback()
            return ConversationService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def add_participant(conversation_id: int, user_id: int, role: str = 'member') -> Dict[str, Any]:
        """Add a participant to a chat room."""
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO Participants (conversation_id, user_id, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (conversation_id, user_id) DO NOTHING
            ''', (conversation_id, user_id, role))
            conn.commit()
            return ConversationService.success()
        except Exception as e:
            conn.rollback()
            return ConversationService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def get_participants(conversation_id: int) -> List[Dict[str, Any]]:
        """List all members of a conversation."""
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT p.user_id as id, c.FullName as name, c.Email as email, p.role, p.nickname, p.is_muted
                FROM Participants p
                JOIN Customers c ON p.user_id = c.CustomerID
                WHERE p.conversation_id = %s
            ''', (conversation_id,))
            return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def get_suggested_users(exclude_user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """Get a few random/recent users for discovery."""
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT CustomerID as id, FullName as name, Email as email, avatar_url as avatar
                FROM Customers
                WHERE CustomerID != %s
                ORDER BY last_seen DESC NULLS LAST, CustomerID ASC
                LIMIT %s
            ''', (exclude_user_id, limit))
            return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def search_users(exclude_user_id: int, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search users by name or email."""
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT CustomerID as id, FullName as name, Email as email, avatar_url as avatar
                FROM Customers
                WHERE CustomerID != %s
                AND (FullName ILIKE %s OR Email ILIKE %s)
                LIMIT %s
            ''', (exclude_user_id, f'%{query}%', f'%{query}%', limit))
            return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def leave_conversation(conversation_id: int, user_id: int) -> bool:
        """Remove a user from a conversation (Delete chat for user)."""
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            # Delete participant
            cursor.execute('''
                DELETE FROM Participants 
                WHERE conversation_id = %s AND user_id = %s
            ''', (conversation_id, user_id))
            
            # Check if conversation is empty
            cursor.execute('SELECT COUNT(*) FROM Participants WHERE conversation_id = %s', (conversation_id,))
            count = cursor.fetchone()[0]
            
            # If empty, delete conversation (optional, depends on policy)
            if count == 0:
                cursor.execute('DELETE FROM Conversations WHERE id = %s', (conversation_id,))
            
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    @staticmethod
    def mark_as_read(conversation_id: int, user_id: int) -> bool:
        """Update last_read_at timestamp."""
        conn = ConversationService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE Participants 
                SET last_read_at = CURRENT_TIMESTAMP 
                WHERE conversation_id = %s AND user_id = %s
            ''', (conversation_id, user_id))
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

