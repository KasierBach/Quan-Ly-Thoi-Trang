from .base_service import BaseService
from datetime import datetime
from typing import Optional, List, Dict, Any
import json

class ChatService(BaseService):
    """
    Service for message-level operations: sending, listing, reactions, and pinning.
    Delegates conversation and attachment management to specialized services.
    """

    @staticmethod
    def send_message(
        sender_type: str,
        content: str,
        session_id: str,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        message_type: str = 'text',
        reply_to_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Send a message and return the created record."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO Messages (
                    sender_type, content, session_id, user_id, 
                    conversation_id, message_type, reply_to_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
            ''', (sender_type, content, session_id, user_id, 
                  conversation_id, message_type, reply_to_id))
            row = cursor.fetchone()
            
            parent_info = {}
            if reply_to_id:
                cursor.execute('SELECT content, sender_type FROM Messages WHERE id = %s', (reply_to_id,))
                p_row = cursor.fetchone()
                if p_row:
                    parent_info = {'parent_content': p_row.content, 'parent_sender_type': p_row.sender_type}

            conn.commit()
            return ChatService.success({
                'id': row.id,
                'content': content,
                'sender_type': sender_type,
                'timestamp': row.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'conversation_id': conversation_id,
                **parent_info
            })
        except Exception as e:
            conn.rollback()
            return ChatService.handle_error(e, "Lỗi khi gửi tin nhắn")
        finally:
            conn.close()

    @staticmethod
    def get_messages(
        session_id: str,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        limit: int = 50,
        before_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch message history with attachments and reactions."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            query = '''
                SELECT m.*, c.FullName as sender_name, c.avatar_url as sender_avatar,
                       p.content as parent_content, p.sender_type as parent_sender_type,
                       (SELECT json_agg(json_build_object('emoji', r.emoji, 'user_id', r.user_id))
                        FROM Reactions r WHERE r.message_id = m.id) as reactions,
                       (SELECT json_agg(json_build_object(
                           'id', a.id, 'file_url', a.file_url, 'file_name', a.file_name,
                           'file_type', a.file_type, 'thumbnail_url', a.thumbnail_url
                       )) FROM Attachments a WHERE a.message_id = m.id) as attachments
                FROM Messages m
                LEFT JOIN Customers c ON m.user_id = c.CustomerID
                LEFT JOIN Messages p ON m.reply_to_id = p.id
                WHERE m.is_deleted = FALSE
            '''
            params = []
            if conversation_id:
                query += " AND m.conversation_id = %s"
                params.append(conversation_id)
            else:
                query += " AND (m.session_id = %s OR m.user_id = %s)"
                params.extend([session_id, user_id])

            if before_id:
                query += " AND m.id < %s"
                params.append(before_id)

            query += " ORDER BY m.created_at ASC LIMIT %s"
            params.append(limit)

            cursor.execute(query, params)
            messages = []
            for row in cursor.fetchall():
                msg = dict(row)
                if msg.get('created_at'):
                    msg['created_at'] = msg['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                messages.append(msg)
            return messages
        finally:
            conn.close()

    @staticmethod
    def recall_message(message_id: int, user_id: int) -> bool:
        """Soft delete a message (Sender only) and physically delete attachments."""
        from .attachment_service import AttachmentService
        from flask import current_app

        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            # 1. Check ownership
            cursor.execute('SELECT id FROM Messages WHERE id = %s AND user_id = %s AND is_deleted = FALSE', (message_id, user_id))
            if not cursor.fetchone():
                return False

            # 2. Delete physical files
            AttachmentService.delete_attachments_by_message_id(message_id, current_app.root_path)

            # 3. Soft delete
            cursor.execute('''
                UPDATE Messages SET is_deleted = TRUE, deleted_at = NOW()
                WHERE id = %s AND user_id = %s AND is_deleted = FALSE
                RETURNING id
            ''', (message_id, user_id))
            conn.commit()
            return cursor.fetchone() is not None
        except Exception as e:
            conn.rollback()
            print(f"Error recalling message: {e}")
            return False
        finally:
            conn.close()

    @staticmethod
    def delete_session_messages(session_id: str) -> bool:
        """Physically delete all messages for a guest session (used by admins)."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            # Also delete attachments if any (joining Messages)
            cursor.execute('''
                DELETE FROM Attachments WHERE message_id IN (
                    SELECT id FROM Messages WHERE session_id = %s AND conversation_id IS NULL
                )
            ''', (session_id,))
            
            cursor.execute('''
                DELETE FROM Messages WHERE session_id = %s AND conversation_id IS NULL
            ''', (session_id,))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"Error deleting session messages: {e}")
            return False
        finally:
            conn.close()

    @staticmethod
    def add_reaction(message_id: int, user_id: int, emoji: str) -> bool:
        """Add emoji reaction to a message."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO Reactions (message_id, user_id, emoji)
                VALUES (%s, %s, %s)
                ON CONFLICT (message_id, user_id, emoji) DO NOTHING
            ''', (message_id, user_id, emoji))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            return False
        finally:
            conn.close()

    @staticmethod
    def remove_reaction(message_id: int, user_id: int, emoji: str) -> bool:
        """Remove emoji reaction from a message."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                DELETE FROM Reactions 
                WHERE message_id = %s AND user_id = %s AND emoji = %s
            ''', (message_id, user_id, emoji))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            return False
        finally:
            conn.close()

    @staticmethod
    def pin_message(conversation_id: int, message_id: int, user_id: int) -> bool:
        """Pin a message to a conversation."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO PinnedMessages (conversation_id, message_id, pinned_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (conversation_id, message_id) DO NOTHING
            ''', (conversation_id, message_id, user_id))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            return False
        finally:
            conn.close()

    @staticmethod
    def unpin_message(conversation_id: int, message_id: int) -> bool:
        """Unpin a message from a conversation."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                DELETE FROM PinnedMessages 
                WHERE conversation_id = %s AND message_id = %s
            ''', (conversation_id, message_id))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            return False
        finally:
            conn.close()

    @staticmethod
    def mark_as_read(conversation_id: int, user_id: int) -> bool:
        """Mark last read timestamp for a participant."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE Participants SET last_read_at = NOW()
                WHERE conversation_id = %s AND user_id = %s
            ''', (conversation_id, user_id))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            return False
        finally:
            conn.close()

    @staticmethod
    def update_last_seen(user_id: int) -> bool:
        """Update user's last seen timestamp."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('UPDATE Customers SET last_seen = NOW() WHERE CustomerID = %s', (user_id,))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            return False
        finally:
            conn.close()

    @staticmethod
    def get_user_status(user_id: int) -> Dict[str, Any]:
        """Get user's online status and last seen time."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT last_seen FROM Customers WHERE CustomerID = %s', (user_id,))
            row = cursor.fetchone()
            if not row or not row.last_seen:
                return {'online': False, 'last_seen': None}
            
            # Online if last_seen is within 5 minutes
            from datetime import timedelta
            is_online = datetime.now() - row.last_seen < timedelta(minutes=5)
            return {
                'online': is_online,
                'last_seen': row.last_seen.strftime('%Y-%m-%d %H:%M:%S')
            }
        finally:
            conn.close()
    @staticmethod
    def get_pinned_messages(conversation_id: int) -> List[Dict[str, Any]]:
        """Get all pinned messages for a conversation."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT m.*, c.FullName as sender_name, c.avatar_url as sender_avatar
                FROM Messages m
                JOIN PinnedMessages pm ON m.id = pm.message_id
                LEFT JOIN Customers c ON m.user_id = c.CustomerID
                WHERE pm.conversation_id = %s
                ORDER BY pm.pinned_at DESC
            ''', (conversation_id,))
            pinned = []
            for row in cursor.fetchall():
                msg = dict(row)
                if msg.get('created_at'):
                    msg['created_at'] = msg['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                pinned.append(msg)
            return pinned
        finally:
            conn.close()
    @staticmethod
    def get_attachments(conversation_id: int, file_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all attachments for a conversation, optionally filtered by type."""
        conn = ChatService.get_connection()
        cursor = conn.cursor()
        try:
            query = '''
                SELECT a.*, m.created_at
                FROM Attachments a
                JOIN Messages m ON a.message_id = m.id
                WHERE m.conversation_id = %s AND m.is_deleted = FALSE
            '''
            params = [conversation_id]
            if file_type:
                query += " AND a.file_type = %s"
                params.append(file_type)
            
            query += " ORDER BY m.created_at DESC"
            cursor.execute(query, params)
            
            attachments = []
            for row in cursor.fetchall():
                att = dict(row)
                if att.get('created_at'):
                    att['created_at'] = att['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                attachments.append(att)
            return attachments
        finally:
            conn.close()
