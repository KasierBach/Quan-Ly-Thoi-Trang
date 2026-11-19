from dataclasses import dataclass, replace
from datetime import datetime
import hmac
import re
import secrets
import unicodedata
import uuid
from typing import Any, Optional

from flask import current_app, request, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import psycopg2

from app.validation import ValidationError, positive_int, required_text
from .base_service import BaseService


class ChatAccessError(PermissionError):
    def __init__(self, message='Không có quyền truy cập cuộc trò chuyện', status=403):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ChatIdentity:
    user_id: Optional[int]
    is_admin: bool = False
    name: str = 'Khách'
    guest_id: Optional[str] = None
    auth_version: Any = None
    guest_token: Optional[str] = None
    guest_binding: Optional[str] = None


@dataclass(frozen=True)
class ChatAccess:
    actor: ChatIdentity
    conversation_id: Optional[int] = None
    session_id: Optional[str] = None
    conversation_type: str = 'support'
    created_by: Optional[int] = None
    role: Optional[str] = None

    @property
    def room(self):
        return f'conv_{self.conversation_id}' if self.conversation_id else f'support_{self.session_id}'


def _guest_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='chat-guest-session-v1')


def issue_guest_credentials() -> dict[str, Any]:
    # Only the server chooses the ID and cookie binding. Legacy localStorage IDs are never adopted.
    sid = session.get('chat_guest_id')
    binding = session.get('chat_guest_binding')
    if not isinstance(sid, str) or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', sid):
        sid = str(uuid.uuid4())
        binding = None
    if not isinstance(binding, str) or len(binding) < 32:
        binding = secrets.token_urlsafe(32)
    if session.get('chat_guest_id') != sid:
        session['chat_guest_id'] = sid
    if session.get('chat_guest_binding') != binding:
        session['chat_guest_binding'] = binding
    token = _guest_serializer().dumps({'sid': sid, 'binding': binding})
    return {'session_id': sid, 'auth_token': token, 'expires_in': current_app.config.get('CHAT_GUEST_TOKEN_TTL', 3600)}


def _verify_guest(token, sid, binding):
    if (
        not isinstance(token, str)
        or not token
        or len(token) > 2048
        or not isinstance(sid, str)
        or not isinstance(binding, str)
    ):
        raise ChatAccessError('Cần phiên chat được máy chủ xác thực', 401)
    try:
        payload = _guest_serializer().loads(token, max_age=current_app.config.get('CHAT_GUEST_TOKEN_TTL', 3600))
    except (BadSignature, SignatureExpired) as exc:
        raise ChatAccessError('Phiên chat không hợp lệ hoặc đã hết hạn', 401) from exc
    if (
        not isinstance(payload, dict)
        or payload.get('sid') != sid
        or not isinstance(payload.get('binding'), str)
        or not hmac.compare_digest(payload['binding'], binding)
    ):
        raise ChatAccessError('Phiên chat không thuộc trình duyệt này', 401)


def refresh_identity(actor: ChatIdentity) -> ChatIdentity:
    if actor.user_id is None:
        _verify_guest(actor.guest_token, actor.guest_id, actor.guest_binding)
        return actor
    if not current_app.config.get('SESSION_REVALIDATION_ENABLED', True):
        return actor
    from .auth_service import AuthService

    state = AuthService.get_identity_state(actor.user_id)
    if state is None or state.AuthVersion != actor.auth_version:
        raise ChatAccessError('Phiên đăng nhập đã hết hiệu lực', 401)
    return replace(actor, is_admin=state.Role == 'admin', name=state.FullName)


def get_identity(auth_token=None) -> ChatIdentity:
    uid = session.get('user_id')
    if uid is not None:
        return refresh_identity(
            ChatIdentity(
                positive_int(uid, 'Tài khoản', 2147483647),
                is_admin=session.get('is_admin') is True,
                name=session.get('user_name') or 'Người dùng',
                guest_id=session.get('chat_guest_id'),
                auth_version=session.get('auth_version'),
            )
        )
    token = auth_token or request.headers.get('X-Chat-Token') or request.args.get('auth_token')
    actor = ChatIdentity(
        None, guest_id=session.get('chat_guest_id'), guest_binding=session.get('chat_guest_binding'), guest_token=token
    )
    return refresh_identity(actor)


def emoji_value(value):
    value = required_text(value, 'Biểu tượng', 16)
    if not any(unicodedata.category(char) == 'So' for char in value) or any(
        unicodedata.category(char) not in {'So', 'Sk', 'Mn', 'Me'} and char != '\u200d' for char in value
    ):
        raise ValidationError('Biểu tượng không hợp lệ')
    return value


def conversation_settings(value):
    if not isinstance(value, dict) or not value or set(value) - {'name', 'theme_color', 'default_emoji', 'avatar_url'}:
        raise ValidationError('Thiết lập cuộc trò chuyện không hợp lệ')
    cleaned = {}
    for key, item in value.items():
        if key == 'name':
            cleaned[key] = required_text(item, 'Tên cuộc trò chuyện', 100)
        elif key == 'theme_color':
            if not isinstance(item, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', item):
                raise ValidationError('Màu không hợp lệ')
            cleaned[key] = item
        elif key == 'default_emoji':
            cleaned[key] = emoji_value(item)
        else:
            if not isinstance(item, str) or not re.fullmatch(r'/uploads/avatars/[0-9a-f]{32}\.jpg', item):
                raise ValidationError('Ảnh đại diện không hợp lệ')
            cleaned[key] = item
    return cleaned


def participant_settings(value):
    if not isinstance(value, dict) or not value or set(value) - {'nickname', 'is_muted', 'role'}:
        raise ValidationError('Thiết lập thành viên không hợp lệ')
    cleaned = {}
    for key, item in value.items():
        if key == 'nickname':
            cleaned[key] = None if item in ('', None) else required_text(item, 'Biệt danh', 100)
        elif key == 'is_muted':
            if not isinstance(item, bool):
                raise ValidationError('Thông báo không hợp lệ')
            cleaned[key] = item
        else:
            if not isinstance(item, str) or item not in {'member', 'admin'}:
                raise ValidationError('Vai trò không hợp lệ')
            cleaned[key] = item
    return cleaned


class ConversationService(BaseService):
    @staticmethod
    def get_access(conversation_id=None, session_id=None, *, actor=None, permission='read', cursor=None) -> ChatAccess:
        actor = refresh_identity(actor) if actor is not None else get_identity()
        if conversation_id not in (None, '') and not re.fullmatch(r'[0-9]+', str(conversation_id)):
            session_id, conversation_id = conversation_id, None
        if conversation_id in (None, ''):
            sid = session_id or actor.guest_id
            if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', sid):
                raise ChatAccessError('Cần khởi tạo phiên chat', 401)
            if not actor.is_admin and sid != actor.guest_id:
                raise ChatAccessError()
            if permission not in {'read', 'send'}:
                raise ChatAccessError('Thao tác không hỗ trợ cho phiên khách')
            return ChatAccess(actor, session_id=sid)
        cid = positive_int(conversation_id, 'Cuộc trò chuyện', 2147483647)
        if actor.user_id is None:
            raise ChatAccessError('Cần đăng nhập', 401)
        if cursor is None:
            conn = ConversationService.get_connection()
            try:
                with conn.cursor() as db_cursor:
                    return ConversationService.get_access(cid, actor=actor, permission=permission, cursor=db_cursor)
            finally:
                conn.close()
        if cursor is None:
            raise RuntimeError('Conversation authorization requires a database cursor')
        cursor.execute(
            """
            SELECT c.id, c.type, c.created_by, p.role
            FROM Conversations c
            LEFT JOIN Participants p ON p.conversation_id = c.id AND p.user_id = %s
            WHERE c.id = %s
        """,
            (actor.user_id, cid),
        )
        row = cursor.fetchone()
        # Administrators serve support only; the site role does not unlock private/group messages.
        if row is None or (not row.role and not (actor.is_admin and row.type == 'support')):
            raise ChatAccessError()
        if permission in {'manage', 'pin'} and not (
            row.created_by == actor.user_id or row.role == 'admin' or (actor.is_admin and row.type == 'support')
        ):
            raise ChatAccessError('Cần quyền quản lý cuộc trò chuyện')
        if permission in {'read_receipt', 'call'} and not row.role:
            raise ChatAccessError()
        if permission == 'call' and row.type != 'private':
            raise ChatAccessError('Chỉ hỗ trợ cuộc gọi một-một', 409)
        return ChatAccess(actor, cid, conversation_type=row.type, created_by=row.created_by, role=row.role)

    @staticmethod
    def create_conversation(
        conversation_type='group', name=None, created_by=None, avatar_url=None, participant_ids=None, *, actor=None
    ) -> dict[str, Any]:
        actor = actor or get_identity()
        if actor.user_id is None:
            raise ChatAccessError('Cần đăng nhập', 401)
        if created_by is not None and positive_int(created_by, 'Người tạo') != actor.user_id:
            raise ChatAccessError()
        if conversation_type != 'group':
            raise ValidationError('Dùng API trò chuyện trực tiếp cho cuộc trò chuyện một-một')
        name = required_text(name, 'Tên nhóm', 100)
        if avatar_url is not None:
            avatar_url = conversation_settings({'avatar_url': avatar_url})['avatar_url']
        if participant_ids is None:
            participant_ids = []
        if not isinstance(participant_ids, list) or len(participant_ids) > 50:
            raise ValidationError('Danh sách thành viên không hợp lệ')
        members = {positive_int(uid, 'Thành viên', 2147483647) for uid in participant_ids} | {actor.user_id}
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                for uid in members:
                    cursor.execute('SELECT CustomerID FROM Customers WHERE CustomerID = %s', (uid,))
                    if cursor.fetchone() is None:
                        raise ValidationError('Thành viên không tồn tại')
                cursor.execute(
                    'INSERT INTO Conversations (type, name, created_by, avatar_url) VALUES (%s, %s, %s, %s) RETURNING id',
                    ('group', name, actor.user_id, avatar_url),
                )
                cid = cursor.fetchone().id
                for uid in sorted(members):
                    cursor.execute(
                        'INSERT INTO Participants (conversation_id, user_id, role) VALUES (%s, %s, %s)',
                        (cid, uid, 'admin' if uid == actor.user_id else 'member'),
                    )
            conn.commit()
            return ConversationService.success({'id': cid, 'name': name, 'type': 'group'})
        except (ValidationError, ChatAccessError):
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            return ConversationService.handle_error(exc, 'Không thể tạo cuộc trò chuyện')
        finally:
            conn.close()

    @staticmethod
    def create_direct_conversation(target_uid, *, actor=None) -> dict[str, Any]:
        actor = actor or get_identity()
        target_uid = positive_int(target_uid, 'Thành viên', 2147483647)
        if actor.user_id is None:
            raise ChatAccessError('Cần đăng nhập', 401)
        if target_uid == actor.user_id:
            raise ValidationError('Không thể trò chuyện trực tiếp với chính mình')
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT CustomerID FROM Customers WHERE CustomerID = %s', (target_uid,))
                if cursor.fetchone() is None:
                    raise ValidationError('Thành viên không tồn tại')
                # Serialize this pair so two concurrent requests cannot create duplicate direct rooms.
                cursor.execute(
                    'SELECT pg_advisory_xact_lock(%s, %s)',
                    (min(actor.user_id, target_uid), max(actor.user_id, target_uid)),
                )
                cursor.execute(
                    """
                    SELECT c.id FROM Conversations c
                    JOIN Participants p1 ON c.id = p1.conversation_id
                    JOIN Participants p2 ON c.id = p2.conversation_id
                    WHERE c.type = 'private' AND p1.user_id = %s AND p2.user_id = %s
                      AND (SELECT COUNT(*) FROM Participants WHERE conversation_id = c.id) = 2
                    ORDER BY c.id LIMIT 1
                """,
                    (actor.user_id, target_uid),
                )
                row = cursor.fetchone()
                if row is not None:
                    cid = row.id
                else:
                    cursor.execute(
                        "INSERT INTO Conversations (type, created_by) VALUES ('private', %s) RETURNING id",
                        (actor.user_id,),
                    )
                    cid = cursor.fetchone().id
                    cursor.execute(
                        'INSERT INTO Participants (conversation_id, user_id, role) VALUES (%s, %s, %s), (%s, %s, %s)',
                        (cid, actor.user_id, 'admin', cid, target_uid, 'member'),
                    )
            conn.commit()
            return ConversationService.success({'conversation': {'id': cid, 'type': 'private'}})
        except (ValidationError, ChatAccessError):
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            return ConversationService.handle_error(exc, 'Không thể tạo cuộc trò chuyện')
        finally:
            conn.close()

    @staticmethod
    def get_conversation(conversation_id, *, actor=None):
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                ConversationService.get_access(conversation_id, actor=actor, cursor=cursor)
                cursor.execute(
                    """
                    SELECT c.*,
                        (SELECT content FROM Messages WHERE conversation_id = c.id AND NOT is_deleted ORDER BY id DESC LIMIT 1) AS last_message,
                        (SELECT created_at FROM Messages WHERE conversation_id = c.id AND NOT is_deleted ORDER BY id DESC LIMIT 1) AS last_message_at
                    FROM Conversations c WHERE c.id = %s
                """,
                    (conversation_id,),
                )
                row = cursor.fetchone()
                return ConversationService._serialize(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def _serialize(row) -> dict[str, Any]:
        result = dict(row)
        for key, value in result.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
        return result

    @staticmethod
    def get_user_conversations(user_id, *, actor=None) -> list[dict[str, Any]]:
        actor = actor or get_identity()
        uid = positive_int(user_id, 'Tài khoản', 2147483647)
        if actor.user_id != uid:
            raise ChatAccessError()
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT c.*, p.role, p.last_read_at, p.nickname AS my_nickname,
                        (SELECT content FROM Messages WHERE conversation_id = c.id AND NOT is_deleted ORDER BY id DESC LIMIT 1) AS last_message,
                        (SELECT created_at FROM Messages WHERE conversation_id = c.id AND NOT is_deleted ORDER BY id DESC LIMIT 1) AS last_message_at,
                        CASE WHEN c.type = 'private' THEN (
                            SELECT COALESCE(p2.nickname, u.FullName) FROM Participants p2 JOIN Customers u ON p2.user_id = u.CustomerID
                            WHERE p2.conversation_id = c.id AND p2.user_id != %s ORDER BY p2.id LIMIT 1
                        ) ELSE NULL END AS partner_display_name
                    FROM Conversations c JOIN Participants p ON c.id = p.conversation_id
                    WHERE p.user_id = %s ORDER BY last_message_at DESC NULLS LAST, c.id DESC
                """,
                    (uid, uid),
                )
                results = []
                for row in cursor.fetchall():
                    conv = ConversationService._serialize(row)
                    conv['name'] = conv.get('name') or conv.get('partner_display_name') or 'Cuộc trò chuyện'
                    conv['is_online'] = False
                    results.append(conv)
                return results
        finally:
            conn.close()

    @staticmethod
    def get_guest_conversations(*, actor=None) -> list[dict[str, Any]]:
        actor = actor or get_identity()
        if not actor.is_admin:
            raise ChatAccessError()
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT ON (session_id) session_id, created_at AS last_time, content AS last_message
                    FROM Messages WHERE session_id IS NOT NULL AND conversation_id IS NULL AND NOT is_deleted
                    ORDER BY session_id, id DESC
                """)
                rows = sorted(cursor.fetchall(), key=lambda row: row.last_time, reverse=True)
                return [
                    {
                        'id': row.session_id,
                        'session_id': row.session_id,
                        'name': f'Khách {row.session_id[:8]}',
                        'type': 'support',
                        'last_message': row.last_message,
                        'last_message_at': row.last_time.isoformat(),
                        'is_online': False,
                    }
                    for row in rows
                ]
        finally:
            conn.close()

    @staticmethod
    def get_direct_conversation(uid1, uid2, *, actor=None):
        actor = actor or get_identity()
        if actor.user_id != positive_int(uid1, 'Tài khoản'):
            raise ChatAccessError()
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT c.id FROM Conversations c JOIN Participants p1 ON c.id = p1.conversation_id
                    JOIN Participants p2 ON c.id = p2.conversation_id
                    WHERE c.type = 'private' AND p1.user_id = %s AND p2.user_id = %s
                      AND (SELECT COUNT(*) FROM Participants WHERE conversation_id = c.id) = 2 LIMIT 1
                """,
                    (uid1, positive_int(uid2, 'Thành viên')),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def add_participant(cid, uid, role='member', *, actor=None) -> dict[str, Any]:
        uid = positive_int(uid, 'Thành viên', 2147483647)
        if role != 'member':
            raise ValidationError('Thành viên mới phải có vai trò member')
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                access = ConversationService.get_access(cid, actor=actor, permission='manage', cursor=cursor)
                if access.conversation_type != 'group':
                    raise ValidationError('Chỉ có thể thêm thành viên vào nhóm')
                cursor.execute('SELECT CustomerID FROM Customers WHERE CustomerID = %s', (uid,))
                if cursor.fetchone() is None:
                    raise ValidationError('Thành viên không tồn tại')
                cursor.execute(
                    'INSERT INTO Participants (conversation_id, user_id, role) VALUES (%s, %s, %s) ON CONFLICT (conversation_id, user_id) DO NOTHING',
                    (cid, uid, role),
                )
            conn.commit()
            return ConversationService.success()
        except (ValidationError, ChatAccessError):
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            return ConversationService.handle_error(exc)
        finally:
            conn.close()

    @staticmethod
    def get_participants(cid, *, actor=None) -> list[dict[str, Any]]:
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                access = ConversationService.get_access(cid, actor=actor, cursor=cursor)
                cursor.execute(
                    """
                    SELECT p.user_id AS id, c.FullName AS name, c.avatar_url AS avatar, p.role, p.nickname,
                           CASE WHEN p.user_id = %s THEN p.is_muted ELSE NULL END AS is_muted
                    FROM Participants p JOIN Customers c ON p.user_id = c.CustomerID
                    WHERE p.conversation_id = %s ORDER BY p.id
                """,
                    (access.actor.user_id, cid),
                )
                return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def search_users(exclude_uid, query, limit=10, *, actor=None) -> list[dict[str, Any]]:
        actor = actor or get_identity()
        if actor.user_id != positive_int(exclude_uid, 'Tài khoản'):
            raise ChatAccessError('Cần đăng nhập', 401)
        query = required_text(query, 'Tìm kiếm', 100)
        limit = positive_int(limit, 'Giới hạn', 50)
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT CustomerID AS id, FullName AS name, avatar_url AS avatar
                    FROM Customers WHERE CustomerID != %s AND (FullName ILIKE %s OR Email ILIKE %s)
                    ORDER BY CustomerID LIMIT %s
                """,
                    (exclude_uid, f'%{query}%', f'%{query}%', limit),
                )
                return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_suggested_users(user_id, *, actor=None) -> list[dict[str, Any]]:
        actor = actor or get_identity()
        if actor.user_id != user_id or actor.user_id is None:
            raise ChatAccessError('Cần đăng nhập', 401)
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT CustomerID AS id, FullName AS name, avatar_url AS avatar FROM Customers WHERE CustomerID != %s ORDER BY CustomerID LIMIT 10',
                    (user_id,),
                )
                return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def leave_conversation(cid, uid, *, actor=None) -> bool:
        actor = actor or get_identity()
        if actor.user_id != positive_int(uid, 'Tài khoản'):
            raise ChatAccessError()
        conn = ConversationService.get_connection()
        cleanup = []
        try:
            with conn.cursor() as cursor:
                access = ConversationService.get_access(cid, actor=actor, permission='read_receipt', cursor=cursor)
                cursor.execute('SELECT id FROM Conversations WHERE id = %s FOR UPDATE', (cid,))
                cursor.execute('DELETE FROM Participants WHERE conversation_id = %s AND user_id = %s', (cid, uid))
                cursor.execute(
                    'SELECT user_id FROM Participants WHERE conversation_id = %s ORDER BY CASE WHEN role = %s THEN 0 ELSE 1 END, id LIMIT 1',
                    (cid, 'admin'),
                )
                successor = cursor.fetchone()
                if successor is None:
                    cursor.execute(
                        'SELECT a.storage_name FROM Attachments a JOIN Messages m ON a.message_id = m.id WHERE m.conversation_id = %s',
                        (cid,),
                    )
                    cleanup = [row.storage_name for row in cursor.fetchall()]
                    cursor.execute('DELETE FROM Conversations WHERE id = %s', (cid,))
                elif access.created_by == uid:
                    cursor.execute('UPDATE Conversations SET created_by = %s WHERE id = %s', (successor.user_id, cid))
                    cursor.execute(
                        "UPDATE Participants SET role = 'admin' WHERE conversation_id = %s AND user_id = %s",
                        (cid, successor.user_id),
                    )
            conn.commit()
        except ChatAccessError:
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            ConversationService.handle_error(exc)
            return False
        finally:
            conn.close()
        from .attachment_service import AttachmentService

        AttachmentService.cleanup_files(cleanup)
        return True

    @staticmethod
    def mark_as_read(cid, uid, *, actor=None) -> bool:
        actor = actor or get_identity()
        if actor.user_id != positive_int(uid, 'Tài khoản'):
            raise ChatAccessError()
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                ConversationService.get_access(cid, actor=actor, permission='read_receipt', cursor=cursor)
                cursor.execute(
                    'UPDATE Participants SET last_read_at = NOW() WHERE conversation_id = %s AND user_id = %s',
                    (cid, uid),
                )
                updated = cursor.rowcount == 1
            conn.commit()
            return updated
        except ChatAccessError:
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            ConversationService.handle_error(exc)
            return False
        finally:
            conn.close()

    @staticmethod
    def update_conversation_settings(conversation_id, settings, *, actor=None) -> bool:
        settings = conversation_settings(settings)
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                ConversationService.get_access(conversation_id, actor=actor, permission='manage', cursor=cursor)
                fields = ', '.join(f'{key} = %s' for key in settings)
                cursor.execute(
                    f'UPDATE Conversations SET {fields}, updated_at = NOW() WHERE id = %s',
                    (*settings.values(), conversation_id),
                )
                updated = cursor.rowcount == 1
            conn.commit()
            return updated
        except ChatAccessError:
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            ConversationService.handle_error(exc)
            return False
        finally:
            conn.close()

    @staticmethod
    def update_participant_settings(conversation_id, user_id, settings, *, actor=None) -> bool:
        actor = actor or get_identity()
        user_id = positive_int(user_id, 'Thành viên', 2147483647)
        settings = participant_settings(settings)
        permission = 'manage' if user_id != actor.user_id or 'role' in settings else 'read_receipt'
        conn = ConversationService.get_connection()
        try:
            with conn.cursor() as cursor:
                access = ConversationService.get_access(
                    conversation_id, actor=actor, permission=permission, cursor=cursor
                )
                if 'role' in settings and (access.conversation_type != 'group' or user_id == access.created_by):
                    raise ChatAccessError('Không thể đổi quyền của người sở hữu hoặc phòng riêng')
                cursor.execute(
                    'SELECT id FROM Participants WHERE conversation_id = %s AND user_id = %s',
                    (conversation_id, user_id),
                )
                if cursor.fetchone() is None:
                    raise ChatAccessError()
                fields = ', '.join(f'{key} = %s' for key in settings)
                cursor.execute(
                    f'UPDATE Participants SET {fields} WHERE conversation_id = %s AND user_id = %s',
                    (*settings.values(), conversation_id, user_id),
                )
                updated = cursor.rowcount == 1
            conn.commit()
            return updated
        except ChatAccessError:
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            ConversationService.handle_error(exc)
            return False
        finally:
            conn.close()
