from datetime import datetime, timedelta
import re
from typing import Any
from urllib.parse import urlsplit

import psycopg2

from app.validation import ValidationError, positive_int, required_text
from . import attachment_storage
from .base_service import BaseService
from .conversation_service import ChatAccessError, ConversationService, emoji_value, get_identity, refresh_identity


class ChatService(BaseService):
    @staticmethod
    def validate_message(content, message_type='text', attachment=None):
        content = required_text(content, 'Tin nhắn', 4000)
        if not isinstance(message_type, str):
            raise ValidationError('Loại tin nhắn không hợp lệ')
        if message_type == 'sticker':
            parsed = urlsplit(content)
            if (
                parsed.scheme != 'https'
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
                or not (
                    (
                        parsed.netloc == 'cdnjs.cloudflare.com'
                        and re.fullmatch(r'/ajax/libs/twemoji/14\.0\.2/72x72/[0-9a-f-]+\.png', parsed.path)
                    )
                    or (
                        parsed.netloc == 'media.giphy.com'
                        and re.fullmatch(r'/media/[A-Za-z0-9]+/giphy\.gif', parsed.path)
                    )
                )
            ):
                raise ValidationError('Sticker không hợp lệ')
        elif message_type in {'image', 'video', 'audio', 'file'}:
            if attachment is None or attachment.get('file_type') != message_type:
                raise ValidationError('Phương tiện phải được tải lên qua API tệp')
        elif message_type != 'text':
            raise ValidationError('Loại tin nhắn không hợp lệ')
        return content

    @staticmethod
    def send_message(
        sender_type,
        content,
        session_id=None,
        user_id=None,
        conversation_id=None,
        message_type='text',
        reply_to_id=None,
        *,
        actor=None,
        attachment=None,
    ) -> dict[str, Any]:
        actor = actor or get_identity()
        if user_id is not None and positive_int(user_id, 'Người gửi') != actor.user_id:
            raise ChatAccessError()
        content = ChatService.validate_message(content, message_type, attachment)
        reply_to_id = positive_int(reply_to_id, 'Tin nhắn trả lời', 2147483647) if reply_to_id is not None else None
        conn = ChatService.get_connection()
        try:
            with conn.cursor() as cursor:
                access = ConversationService.get_access(
                    conversation_id, session_id, actor=actor, permission='send', cursor=cursor
                )
                sender_type = 'admin' if access.actor.is_admin else 'user'
                parent_info = {}
                if reply_to_id is not None:
                    cursor.execute(
                        """
                        SELECT m.content, m.sender_type, c.FullName AS sender_name
                        FROM Messages m LEFT JOIN Customers c ON m.user_id = c.CustomerID
                        WHERE m.id = %s AND NOT m.is_deleted AND
                            ((%s IS NOT NULL AND m.conversation_id = %s) OR
                             (%s IS NULL AND m.conversation_id IS NULL AND m.session_id = %s))
                    """,
                        (
                            reply_to_id,
                            access.conversation_id,
                            access.conversation_id,
                            access.conversation_id,
                            access.session_id,
                        ),
                    )
                    parent = cursor.fetchone()
                    if parent is None:
                        raise ChatAccessError('Tin nhắn trả lời không thuộc cuộc trò chuyện')
                    parent_info = {
                        'parent_content': parent.content,
                        'parent_sender_type': parent.sender_type,
                        'parent_sender_name': parent.sender_name
                        or ('Admin' if parent.sender_type == 'admin' else 'Khách'),
                    }
                message_session = access.session_id or f'user_{access.actor.user_id}'
                cursor.execute(
                    """
                    INSERT INTO Messages (sender_type, content, session_id, user_id, conversation_id, message_type, reply_to_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id, created_at
                """,
                    (
                        sender_type,
                        content,
                        message_session,
                        access.actor.user_id,
                        access.conversation_id,
                        message_type,
                        reply_to_id,
                    ),
                )
                row = cursor.fetchone()
                attachments = []
                if attachment is not None:
                    attachments.append(attachment_storage.insert_attachment(cursor, row.id, attachment))
            conn.commit()
            return ChatService.success(
                {
                    'id': row.id,
                    'content': content,
                    'sender_type': sender_type,
                    'sender': sender_type,
                    'sender_id': access.actor.user_id,
                    'user_id': access.actor.user_id,
                    'sender_name': access.actor.name,
                    'message_type': message_type,
                    'timestamp': row.created_at.isoformat(),
                    'conversation_id': access.conversation_id,
                    'session_id': access.session_id,
                    'reply_to_id': reply_to_id,
                    'attachments': attachments,
                    **parent_info,
                }
            )
        except (ChatAccessError, ValidationError):
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            return ChatService.handle_error(exc, 'Không thể gửi tin nhắn')
        finally:
            conn.close()

    @staticmethod
    def get_messages(
        session_id=None, user_id=None, conversation_id=None, limit=50, before_id=None, *, actor=None
    ) -> list[dict[str, Any]]:
        actor = actor or get_identity()
        if user_id is not None and positive_int(user_id, 'Tài khoản') != actor.user_id:
            raise ChatAccessError()
        limit = positive_int(limit, 'Giới hạn', 100)
        before_id = positive_int(before_id, 'Tin nhắn trước', 2147483647) if before_id is not None else None
        conn = ChatService.get_connection()
        try:
            with conn.cursor() as cursor:
                access = ConversationService.get_access(conversation_id, session_id, actor=actor, cursor=cursor)
                query = """
                    SELECT m.*, c.FullName AS sender_name, c.avatar_url AS sender_avatar,
                           p.content AS parent_content, p.sender_type AS parent_sender_type,
                           pc.FullName AS parent_sender_name,
                           (SELECT json_agg(json_build_object('emoji', r.emoji, 'user_id', r.user_id))
                            FROM Reactions r WHERE r.message_id = m.id) AS reactions,
                           (SELECT json_agg(json_build_object('id', a.id, 'file_url', a.file_url,
                                'file_name', a.file_name, 'file_type', a.file_type, 'mime_type', a.mime_type))
                            FROM Attachments a WHERE a.message_id = m.id AND a.storage_name IS NOT NULL) AS attachments
                    FROM Messages m LEFT JOIN Customers c ON m.user_id = c.CustomerID
                    LEFT JOIN Messages p ON m.reply_to_id = p.id AND NOT p.is_deleted AND
                        ((m.conversation_id IS NOT NULL AND p.conversation_id = m.conversation_id) OR
                         (m.conversation_id IS NULL AND p.conversation_id IS NULL AND p.session_id = m.session_id))
                    LEFT JOIN Customers pc ON p.user_id = pc.CustomerID
                    WHERE NOT m.is_deleted
                """
                params = []
                if access.conversation_id is not None:
                    query += ' AND m.conversation_id = %s'
                    params.append(access.conversation_id)
                else:
                    # Never OR by sender: it leaks that user's private and unrelated support messages.
                    query += ' AND m.conversation_id IS NULL AND m.session_id = %s'
                    params.append(access.session_id)
                if before_id is not None:
                    query += ' AND m.id < %s'
                    params.append(before_id)
                query += ' ORDER BY m.id DESC LIMIT %s'
                params.append(limit)
                cursor.execute(query, tuple(params))
                return [ChatService._serialize(row) for row in reversed(cursor.fetchall())]
        finally:
            conn.close()

    @staticmethod
    def _serialize(row) -> dict[str, Any]:
        result = ConversationService._serialize(row)
        result['timestamp'] = result.get('created_at')
        return result

    @staticmethod
    def get_message_access(message_id, *, actor=None, permission='read', conversation_id=None, cursor=None):
        actor = actor or get_identity()
        mid = positive_int(message_id, 'Tin nhắn', 2147483647)
        if cursor is None:
            conn = ChatService.get_connection()
            try:
                with conn.cursor() as db_cursor:
                    return ChatService.get_message_access(
                        mid, actor=actor, permission=permission, conversation_id=conversation_id, cursor=db_cursor
                    )
            finally:
                conn.close()
        if cursor is None:
            raise RuntimeError('Message authorization requires a database cursor')
        cursor.execute(
            'SELECT id, conversation_id, session_id, user_id, sender_type, is_deleted FROM Messages WHERE id = %s',
            (mid,),
        )
        row = cursor.fetchone()
        if row is None or row.is_deleted:
            raise ChatAccessError('Tin nhắn không tồn tại', 404)
        access = ConversationService.get_access(
            row.conversation_id,
            row.session_id,
            actor=actor,
            permission='pin' if permission == 'pin' else 'read',
            cursor=cursor,
        )
        if conversation_id is not None and access.conversation_id != positive_int(conversation_id, 'Cuộc trò chuyện'):
            raise ChatAccessError('Tin nhắn không thuộc cuộc trò chuyện')
        if permission == 'reaction' and access.actor.user_id is None:
            raise ChatAccessError('Cần đăng nhập', 401)
        if permission == 'recall':
            is_owner = (
                row.user_id == access.actor.user_id
                if row.user_id is not None
                else access.actor.user_id is None
                and row.sender_type == 'user'
                and row.session_id == access.actor.guest_id
            )
            if not is_owner:
                raise ChatAccessError('Chỉ người gửi có thể thu hồi')
        return access

    @staticmethod
    def recall_message(message_id, user_id=None, *, actor=None) -> bool:
        actor = actor or get_identity()
        if user_id is not None and user_id != actor.user_id:
            raise ChatAccessError()
        conn = ChatService.get_connection()
        cleanup = []
        try:
            with conn.cursor() as cursor:
                ChatService.get_message_access(message_id, actor=actor, permission='recall', cursor=cursor)
                cursor.execute(
                    'UPDATE Messages SET is_deleted = TRUE, deleted_at = NOW() WHERE id = %s AND NOT is_deleted RETURNING id',
                    (message_id,),
                )
                updated = cursor.fetchone() is not None
                cursor.execute('DELETE FROM PinnedMessages WHERE message_id = %s', (message_id,))
                cursor.execute('DELETE FROM Reactions WHERE message_id = %s', (message_id,))
                cleanup = attachment_storage.delete_records(cursor, message_id)
            conn.commit()
        except (ChatAccessError, ValidationError):
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            ChatService.handle_error(exc)
            return False
        finally:
            conn.close()
        attachment_storage.cleanup_files(cleanup)
        return updated

    @staticmethod
    def delete_session_messages(session_id, *, actor=None) -> bool:
        actor = refresh_identity(actor) if actor is not None else get_identity()
        if not actor.is_admin:
            raise ChatAccessError()
        access = ConversationService.get_access(session_id=session_id, actor=actor)
        conn = ChatService.get_connection()
        cleanup = []
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT a.storage_name FROM Attachments a JOIN Messages m ON m.id = a.message_id WHERE m.session_id = %s AND m.conversation_id IS NULL',
                    (access.session_id,),
                )
                cleanup = [row.storage_name for row in cursor.fetchall()]
                cursor.execute(
                    'DELETE FROM Messages WHERE session_id = %s AND conversation_id IS NULL', (access.session_id,)
                )
            conn.commit()
        except psycopg2.Error as exc:
            conn.rollback()
            ChatService.handle_error(exc)
            return False
        finally:
            conn.close()
        attachment_storage.cleanup_files(cleanup)
        return True

    @staticmethod
    def add_reaction(message_id, user_id, emoji, *, actor=None) -> bool:
        return ChatService._reaction(message_id, user_id, emoji, actor=actor)

    @staticmethod
    def remove_reaction(message_id, user_id, emoji, *, actor=None) -> bool:
        return ChatService._reaction(message_id, user_id, emoji, remove=True, actor=actor)

    @staticmethod
    def _reaction(message_id, user_id, emoji, *, remove=False, actor=None) -> bool:
        actor = actor or get_identity()
        if user_id != actor.user_id or actor.user_id is None:
            raise ChatAccessError('Cần đăng nhập', 401)
        emoji = emoji_value(emoji)
        conn = ChatService.get_connection()
        try:
            with conn.cursor() as cursor:
                ChatService.get_message_access(message_id, actor=actor, permission='reaction', cursor=cursor)
                if remove:
                    cursor.execute(
                        'DELETE FROM Reactions WHERE message_id = %s AND user_id = %s AND emoji = %s',
                        (message_id, user_id, emoji),
                    )
                else:
                    cursor.execute(
                        'INSERT INTO Reactions (message_id, user_id, emoji) VALUES (%s, %s, %s) ON CONFLICT (message_id, user_id, emoji) DO NOTHING',
                        (message_id, user_id, emoji),
                    )
            conn.commit()
            return True
        except ChatAccessError:
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            ChatService.handle_error(exc)
            return False
        finally:
            conn.close()

    @staticmethod
    def get_reactions(message_id, *, actor=None) -> list[dict[str, Any]]:
        conn = ChatService.get_connection()
        try:
            with conn.cursor() as cursor:
                ChatService.get_message_access(message_id, actor=actor, cursor=cursor)
                cursor.execute('SELECT emoji, user_id FROM Reactions WHERE message_id = %s ORDER BY id', (message_id,))
                return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def pin_message(conversation_id, message_id, user_id, *, actor=None) -> bool:
        return ChatService._pin(conversation_id, message_id, user_id=user_id, actor=actor)

    @staticmethod
    def unpin_message(conversation_id, message_id, *, actor=None) -> bool:
        return ChatService._pin(conversation_id, message_id, remove=True, actor=actor)

    @staticmethod
    def _pin(conversation_id, message_id, user_id=None, *, remove=False, actor=None) -> bool:
        actor = actor or get_identity()
        if user_id is not None and user_id != actor.user_id:
            raise ChatAccessError()
        conn = ChatService.get_connection()
        try:
            with conn.cursor() as cursor:
                access = ChatService.get_message_access(
                    message_id, actor=actor, permission='pin', conversation_id=conversation_id, cursor=cursor
                )
                if remove:
                    cursor.execute(
                        'DELETE FROM PinnedMessages WHERE conversation_id = %s AND message_id = %s',
                        (access.conversation_id, message_id),
                    )
                else:
                    cursor.execute(
                        'INSERT INTO PinnedMessages (conversation_id, message_id, pinned_by) VALUES (%s, %s, %s) ON CONFLICT (conversation_id, message_id) DO NOTHING',
                        (access.conversation_id, message_id, access.actor.user_id),
                    )
            conn.commit()
            return True
        except (ChatAccessError, ValidationError):
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            ChatService.handle_error(exc)
            return False
        finally:
            conn.close()

    @staticmethod
    def mark_as_read(conversation_id, user_id, *, actor=None) -> bool:
        return ConversationService.mark_as_read(conversation_id, user_id, actor=actor)

    @staticmethod
    def update_last_seen(user_id, *, actor=None) -> bool:
        actor = actor or get_identity()
        if actor.user_id is None or actor.user_id != user_id:
            raise ChatAccessError()
        conn = ChatService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE Customers SET last_seen = NOW() WHERE CustomerID = %s', (user_id,))
            conn.commit()
            return True
        except psycopg2.Error as exc:
            conn.rollback()
            ChatService.handle_error(exc)
            return False
        finally:
            conn.close()

    @staticmethod
    def get_user_status(user_id, *, actor=None) -> dict[str, Any]:
        actor = actor or get_identity()
        if actor.user_id is None:
            raise ChatAccessError('Cần đăng nhập', 401)
        target_uid = positive_int(user_id, 'Tài khoản', 2147483647)
        conn = ChatService.get_connection()
        try:
            with conn.cursor() as cursor:
                if target_uid != actor.user_id:
                    cursor.execute(
                        """
                        SELECT 1 FROM Participants mine JOIN Participants other ON mine.conversation_id = other.conversation_id
                        WHERE mine.user_id = %s AND other.user_id = %s LIMIT 1
                    """,
                        (actor.user_id, target_uid),
                    )
                    if cursor.fetchone() is None:
                        raise ChatAccessError()
                cursor.execute('SELECT last_seen FROM Customers WHERE CustomerID = %s', (target_uid,))
                row = cursor.fetchone()
                if not row or not row.last_seen:
                    return {'online': False, 'last_seen': None}
                now = datetime.now(row.last_seen.tzinfo)
                return {
                    'online': timedelta(0) <= now - row.last_seen < timedelta(minutes=5),
                    'last_seen': row.last_seen.isoformat(),
                }
        finally:
            conn.close()

    @staticmethod
    def get_pinned_messages(conversation_id, *, actor=None) -> list[dict[str, Any]]:
        conn = ChatService.get_connection()
        try:
            with conn.cursor() as cursor:
                access = ConversationService.get_access(conversation_id, actor=actor, cursor=cursor)
                cursor.execute(
                    """
                    SELECT m.*, c.FullName AS sender_name FROM Messages m JOIN PinnedMessages pm ON m.id = pm.message_id
                    LEFT JOIN Customers c ON m.user_id = c.CustomerID
                    WHERE pm.conversation_id = %s AND m.conversation_id = %s AND NOT m.is_deleted ORDER BY pm.pinned_at DESC
                """,
                    (access.conversation_id, access.conversation_id),
                )
                return [ChatService._serialize(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_attachments(conversation_id, file_type=None, *, actor=None) -> list[dict[str, Any]]:
        if file_type is not None and (
            not isinstance(file_type, str) or file_type not in {'image', 'video', 'audio', 'file'}
        ):
            raise ValidationError('Loại tệp không hợp lệ')
        conn = ChatService.get_connection()
        try:
            with conn.cursor() as cursor:
                access = ConversationService.get_access(conversation_id, actor=actor, cursor=cursor)
                query = """
                    SELECT a.id, a.file_url, a.file_name, a.file_type, a.file_size, a.mime_type, m.created_at
                    FROM Attachments a JOIN Messages m ON a.message_id = m.id
                    WHERE m.conversation_id = %s AND NOT m.is_deleted AND a.storage_name IS NOT NULL
                """
                params: list[Any] = [access.conversation_id]
                if file_type:
                    query += ' AND a.file_type = %s'
                    params.append(file_type)
                query += ' ORDER BY m.id DESC, a.id DESC LIMIT 200'
                cursor.execute(query, tuple(params))
                return [ConversationService._serialize(row) for row in cursor.fetchall()]
        finally:
            conn.close()
