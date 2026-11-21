"""Real Flask/Socket.IO transports with deterministic service-boundary doubles.

The production identity, conversation ACL, message ACL, upload decoder, CSRF and
socket handlers run here. Persistence doubles make no claim about SQL behavior;
that is independently exercised in integration/test_chat_database.py.
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
import uuid

from flask import Flask, session
from flask_wtf.csrf import generate_csrf
from itsdangerous.timed import TimestampSigner
import psycopg2
import pytest

from app import socketio
from app.database import CaseInsensitiveRecord
from app.services.attachment_service import AttachmentService
from app.services.auth_service import AuthService
from app.services.base_service import BaseService
from app.services.chat_service import ChatService
from app.services.conversation_service import (
    ChatAccessError,
    ConversationService,
    get_identity,
)
from app.sockets import ChatSocketHandlers
from app.validation import ValidationError, positive_int


CALL_ID = 'call_0123456789abcdef'
OFFER = {'type': 'offer', 'sdp': 'v=0\r\no=synthetic-offer'}
ANSWER = {'type': 'answer', 'sdp': 'v=0\r\no=synthetic-answer'}
ICE = {'candidate': 'candidate:synthetic', 'sdpMid': '0', 'sdpMLineIndex': 0}
_REAL_ACCESS = ConversationService.get_access
_REAL_MESSAGE_ACCESS = ChatService.get_message_access


class CapturedTimer:
    """Capture the production timeout callback without starting a real thread."""

    def __init__(self, interval, function, args=(), kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.function(*self.args, **self.kwargs)


class ChatHarness:
    def __init__(self, app, monkeypatch):
        self.app = app
        self.handlers = app.extensions['chat_socket_handlers']
        self.sockets = []
        self.sids = {}
        self.timers = []
        self.now = 100.0
        self.handlers.clock = lambda: self.now
        self.states = {
            uid: CaseInsensitiveRecord(
                CustomerID=uid,
                FullName=f'Current User {uid}',
                AuthVersion=1,
                Role='admin' if uid == 2 else 'customer',
                DarkModeEnabled=False,
            )
            for uid in [1, 2, 3]
        }
        self.conversations = {
            1: {'type': 'support', 'created_by': 1, 'members': {1: 'owner', 2: 'admin'}},
            2: {'type': 'private', 'created_by': 1, 'members': {1: 'owner', 3: 'member'}},
            3: {'type': 'group', 'created_by': 1, 'members': {1: 'admin', 3: 'member'}},
        }
        self.messages = {
            1: self.message(1, 1, 1, 'Support question'),
            2: self.message(2, 1, 2, 'Support answer', sender_type='admin'),
            3: self.message(3, 2, 3, 'Private message'),
        }
        self.attachments = {}
        self.operations = []
        self.next_id = 10
        self.app.config['SESSION_REVALIDATION_ENABLED'] = True
        monkeypatch.setattr(AuthService, 'get_identity_state', lambda uid, **kwargs: self.states.get(int(uid)))
        monkeypatch.setattr(ConversationService, 'get_access', self.access)
        monkeypatch.setattr(ChatService, 'get_message_access', self.message_access)
        self.send = Mock(side_effect=self.send_message)
        monkeypatch.setattr(ChatService, 'send_message', self.send)
        monkeypatch.setattr(ChatService, 'get_messages', self.history)
        monkeypatch.setattr(ConversationService, 'get_conversation', self.get_conversation)
        monkeypatch.setattr(ConversationService, 'get_publication_targets', self.publication_targets)
        monkeypatch.setattr(ConversationService, 'get_participants', self.participants)
        monkeypatch.setattr(ChatService, 'update_last_seen', lambda uid, **kwargs: True)
        monkeypatch.setattr(ChatService, 'get_reactions', self.reactions)
        monkeypatch.setattr(ChatService, 'add_reaction', self.add_reaction)
        monkeypatch.setattr(ChatService, 'remove_reaction', self.remove_reaction)
        monkeypatch.setattr(ChatService, 'pin_message', self.pin)
        monkeypatch.setattr(ChatService, 'unpin_message', self.unpin)
        monkeypatch.setattr(ChatService, 'recall_message', self.recall)
        monkeypatch.setattr(ChatService, 'get_pinned_messages', self.pinned)
        monkeypatch.setattr(ChatService, 'get_attachments', self.attachment_list)
        monkeypatch.setattr(AttachmentService, 'get_attachment', self.get_attachment)
        monkeypatch.setattr(ConversationService, 'mark_as_read', self.read)
        monkeypatch.setattr(ConversationService, 'leave_conversation', self.leave)
        monkeypatch.setattr(ConversationService, 'update_conversation_settings', self.settings)
        monkeypatch.setattr(ConversationService, 'update_participant_settings', self.participant_settings)

        def timer(interval, function, args=(), kwargs=None):
            captured = CapturedTimer(interval, function, args, kwargs)
            self.timers.append(captured)
            return captured

        monkeypatch.setattr('app.sockets.Timer', timer)

    @staticmethod
    def message(mid, cid, uid, content, *, session_id=None, sender_type='user'):
        return CaseInsensitiveRecord(
            id=mid,
            conversation_id=cid,
            session_id=session_id,
            user_id=uid,
            content=content,
            sender_type=sender_type,
            sender_id=uid,
            sender_name=f'Current User {uid}',
            message_type='text',
            is_deleted=False,
            attachments=[],
            reactions=[],
        )

    def access(self, conversation_id=None, session_id=None, *, actor=None, permission='read', cursor=None):
        actor = actor or get_identity()
        row = None
        if str(conversation_id).isdigit():
            cid = int(conversation_id)
            conv = self.conversations.get(cid)
            if conv:
                row = CaseInsensitiveRecord(
                    id=cid, type=conv['type'], created_by=conv['created_by'], role=conv['members'].get(actor.user_id)
                )
        row_cursor = MagicMock()
        row_cursor.fetchone.return_value = row
        return _REAL_ACCESS(conversation_id, session_id, actor=actor, permission=permission, cursor=row_cursor)

    def message_access(self, mid, *, actor=None, permission='read', conversation_id=None, cursor=None):
        row_cursor = MagicMock()
        row_cursor.fetchone.return_value = self.messages.get(int(mid))
        return _REAL_MESSAGE_ACCESS(
            mid, actor=actor, permission=permission, conversation_id=conversation_id, cursor=row_cursor
        )

    def send_message(
        self,
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
    ):
        actor = actor or get_identity()
        if user_id is not None and user_id != actor.user_id:
            raise ChatAccessError()
        content = ChatService.validate_message(content, message_type, attachment)
        access = self.access(conversation_id, session_id, actor=actor, permission='send')
        if reply_to_id is not None:
            reply_to_id = positive_int(reply_to_id, 'reply')
            parent = self.messages.get(reply_to_id)
            if (
                not parent
                or parent.is_deleted
                or parent.conversation_id != access.conversation_id
                or (access.conversation_id is None and parent.session_id != access.session_id)
            ):
                raise ChatAccessError('Tin nhắn trả lời không thuộc cuộc trò chuyện')
        mid = self.next_id
        self.next_id += 1
        row = self.message(
            mid,
            access.conversation_id,
            access.actor.user_id,
            content,
            session_id=access.session_id,
            sender_type='admin' if access.actor.is_admin else 'user',
        )
        row['sender_name'] = access.actor.name
        row['reply_to_id'] = reply_to_id
        row['message_type'] = message_type
        row['timestamp'] = datetime(2026, 11, 17, 12, 0).isoformat()
        if attachment:
            aid = mid + 100
            item = {**attachment, 'id': aid, 'file_url': f'/api/chat/attachments/{aid}', 'message_id': mid}
            self.attachments[aid] = item
            row['attachments'] = [{key: value for key, value in item.items() if key != 'storage_name'}]
        self.messages[mid] = row
        return {'success': True, 'message': 'sent', **row}

    def history(self, session_id=None, user_id=None, conversation_id=None, limit=50, before_id=None, *, actor=None):
        access = self.access(conversation_id, session_id, actor=actor)
        rows = [
            dict(row)
            for row in self.messages.values()
            if not row.is_deleted
            and row.conversation_id == access.conversation_id
            and (access.conversation_id is not None or row.session_id == access.session_id)
            and (before_id is None or row.id < before_id)
        ]
        return sorted(rows, key=lambda row: row['id'])[-limit:]

    def get_conversation(self, cid, *, actor=None):
        access = self.access(cid, actor=actor)
        return {'id': access.conversation_id, 'type': access.conversation_type}

    def publication_targets(self, cid):
        conv = self.conversations[int(cid)]
        user_ids = set(conv['members'])
        if conv['type'] == 'support':
            user_ids.update(uid for uid, state in self.states.items() if state.Role == 'admin')
        return [
            {'user_id': uid, 'auth_version': self.states[uid].AuthVersion}
            for uid in sorted(user_ids)
            if uid in self.states
        ]

    def participants(self, cid, *, actor=None):
        self.access(cid, actor=actor)
        return [
            {'id': uid, 'name': self.states[uid].FullName, 'role': role}
            for uid, role in self.conversations[int(cid)]['members'].items()
        ]

    def reactions(self, mid, *, actor=None):
        self.message_access(mid, actor=actor)
        return list(self.messages[mid].reactions)

    def add_reaction(self, mid, uid, emoji, *, actor=None):
        from app.services.conversation_service import emoji_value

        access = self.message_access(mid, actor=actor, permission='reaction')
        assert uid == access.actor.user_id
        emoji = emoji_value(emoji)
        self.operations.append(('add_reaction', mid, uid, emoji))
        self.messages[mid].reactions.append({'user_id': uid, 'emoji': emoji})
        return True

    def remove_reaction(self, mid, uid, emoji, *, actor=None):
        from app.services.conversation_service import emoji_value

        self.message_access(mid, actor=actor, permission='reaction')
        emoji_value(emoji)
        self.operations.append(('remove_reaction', mid, uid, emoji))
        self.messages[mid]['reactions'] = [
            r for r in self.messages[mid].reactions if r != {'user_id': uid, 'emoji': emoji}
        ]
        return True

    def pin(self, cid, mid, uid, *, actor=None):
        access = self.message_access(mid, actor=actor, permission='pin', conversation_id=cid)
        assert uid == access.actor.user_id
        self.operations.append(('pin', cid, mid, uid))
        return True

    def unpin(self, cid, mid, *, actor=None):
        self.message_access(mid, actor=actor, permission='pin', conversation_id=cid)
        self.operations.append(('unpin', cid, mid))
        return True

    def recall(self, mid, *, actor=None):
        self.message_access(mid, actor=actor, permission='recall')
        self.messages[mid]['is_deleted'] = True
        self.operations.append(('recall', mid))
        return True

    def pinned(self, cid, *, actor=None):
        self.access(cid, actor=actor)
        return []

    def read(self, cid, uid, *, actor=None):
        access = self.access(cid, actor=actor, permission='read_receipt')
        assert uid == access.actor.user_id
        self.operations.append(('read', cid, uid))
        return True

    def leave(self, cid, uid, *, actor=None):
        self.access(cid, actor=actor, permission='read_receipt')
        self.conversations[int(cid)]['members'].pop(uid)
        self.operations.append(('leave', cid, uid))
        return True

    def settings(self, cid, settings, *, actor=None):
        self.access(cid, actor=actor, permission='manage')
        self.operations.append(('settings', cid, settings))
        return True

    def participant_settings(self, cid, uid, settings, *, actor=None):
        actor = actor or get_identity()
        permission = 'manage' if uid != actor.user_id or 'role' in settings else 'read_receipt'
        self.access(cid, actor=actor, permission=permission)
        if uid == actor.user_id and 'role' in settings:
            raise ChatAccessError('Không thể tự cấp quyền')
        self.operations.append(('participant_settings', cid, uid, settings))
        return True

    def attachment_list(self, cid, file_type=None, *, actor=None):
        self.access(cid, actor=actor)
        if file_type is not None and file_type not in {'image', 'audio', 'video', 'file'}:
            raise ValidationError('Loại tệp không hợp lệ')
        return [
            item for item in self.attachments.values() if self.messages[item['message_id']].conversation_id == int(cid)
        ]

    def get_attachment(self, aid, *, actor=None):
        item = self.attachments.get(aid)
        if not item:
            raise ChatAccessError('Tệp không tồn tại', 404)
        self.message_access(item['message_id'], actor=actor)
        if not item.get('storage_name'):
            raise ChatAccessError('Tệp cần được tải lên lại', 404)
        return item

    def browser(self, uid=None, *, cookie_role=None, version=1):
        browser = self.app.test_client()
        if uid is not None:
            role = cookie_role or ('admin' if uid == 2 else 'customer')
            with browser.session_transaction() as cookie:
                cookie.update(
                    user_id=uid, user_name='Cookie Name', role=role, is_admin=role == 'admin', auth_version=version
                )
        return browser

    def guest(self):
        browser = self.browser()
        response = browser.post('/api/chat/guest-session')
        assert response.status_code == 200
        return browser, response.get_json()

    def connect(self, uid=None, *, browser=None, auth=None):
        browser = browser or self.browser(uid)
        before = set(self.handlers.clients)
        connection = socketio.test_client(self.app, flask_test_client=browser, auth=auth)
        self.sockets.append(connection)
        added = set(self.handlers.clients) - before
        if added:
            assert len(added) == 1
            self.sids[connection] = added.pop()
        return connection

    def join(self, connection, cid):
        result = connection.emit('join_conversation', {'conversation_id': cid}, callback=True)
        assert result['success'] is True
        connection.get_received()

    def close(self):
        for connection in self.sockets:
            if connection.is_connected():
                connection.disconnect()
        self.handlers.close()


@pytest.fixture(autouse=True)
def forbid_database(monkeypatch):
    def refused():
        pytest.fail('A no-DB chat contract test attempted an unplanned database connection')

    monkeypatch.setattr(BaseService, 'get_connection', staticmethod(refused))


@pytest.fixture
def chat(app, monkeypatch):
    harness = ChatHarness(app, monkeypatch)
    try:
        yield harness
    finally:
        harness.close()


def packets(connection, event):
    return [packet['args'][0] for packet in connection.get_received() if packet['name'] == event]


def signal(connection, event, **data):
    return connection.emit(event, {'conversation_id': 2, 'call_id': CALL_ID, **data}, callback=True)


def ring(chat, caller, **data):
    return signal(caller, 'call_user', offer=OFFER, target_user_id=3, isVideo=False, **data)


def active_pair(chat):
    caller, callee = chat.connect(1), chat.connect(3)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    assert signal(callee, 'answer_call', answer=ANSWER)['success'] is True
    caller.get_received()
    return caller, callee


def csrf_for(app, browser):
    with browser.session_transaction() as cookie:
        prior = dict(cookie)
    with app.test_request_context():
        session.update(prior)
        token = generate_csrf()
        raw = session['csrf_token']
    with browser.session_transaction() as cookie:
        cookie['csrf_token'] = raw
    return token


def test_guest_bootstrap_ignores_client_uuid_and_sets_no_store(chat):
    browser = chat.browser()
    response = browser.post('/api/chat/guest-session', json={'session_id': 'attacker-selected'})
    assert response.status_code == 200
    issued = response.get_json()
    assert uuid.UUID(issued['session_id']).version == 4
    assert issued['session_id'] != 'attacker-selected'
    assert response.headers['Cache-Control'] == 'no-store'
    renewed = browser.post('/api/chat/guest-session').get_json()
    assert renewed['session_id'] == issued['session_id']
    assert browser.get('/api/chat/history', headers={'X-Chat-Token': renewed['auth_token']}).status_code == 200


def test_guest_bootstrap_requires_real_csrf_token_when_enabled(chat):
    chat.app.config['WTF_CSRF_ENABLED'] = True
    browser = chat.browser()
    assert browser.post('/api/chat/guest-session').status_code == 400
    with browser.session_transaction() as cookie:
        assert 'chat_guest_id' not in cookie
    token = csrf_for(chat.app, browser)
    response = browser.post('/api/chat/guest-session', headers={'X-CSRFToken': token})
    assert response.status_code == 200
    assert response.get_json()['auth_token']


def test_guest_token_replay_with_no_cookie_or_another_signed_cookie_is_denied(chat):
    owner, issued = chat.guest()
    other, other_issued = chat.guest()
    no_cookie = chat.browser()
    headers = {'X-Chat-Token': issued['auth_token']}
    assert owner.get('/api/chat/history', headers=headers).status_code == 200
    assert no_cookie.get('/api/chat/history', headers=headers).status_code == 401
    assert other.get('/api/chat/history', headers=headers).status_code == 401
    assert other_issued['session_id'] != issued['session_id']
    assert other.get('/api/chat/history', headers={'X-Chat-Token': other_issued['auth_token']}).status_code == 200


def test_guest_uuid_scope_tampering_and_expired_token_are_denied_over_http(chat, monkeypatch):
    now = [1_000_000]
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: now[0])
    chat.app.config['CHAT_GUEST_TOKEN_TTL'] = 10
    browser, issued = chat.guest()
    headers = {'X-Chat-Token': issued['auth_token']}
    tampered = browser.get('/api/chat/history', query_string={'session_id': str(uuid.uuid4())}, headers=headers)
    assert tampered.status_code == 403
    now[0] += 11
    assert browser.get('/api/chat/history', headers=headers).status_code == 401


def test_http_sender_identity_cannot_be_supplied_by_json(chat):
    browser = chat.browser(1, cookie_role='admin')
    response = browser.post(
        '/api/chat/send',
        json={
            'content': 'hello',
            'conversation_id': 2,
            'user_id': 2,
            'sender_type': 'admin',
            'sender_name': 'Attacker',
            'session_id': 'another-guest',
        },
    )
    assert response.status_code == 200
    message = response.get_json()
    assert message['user_id'] == message['sender_id'] == 1
    assert message['sender_name'] == 'Current User 1'
    assert message['sender_type'] == 'user'
    assert message['conversation_id'] == 2
    assert message['session_id'] is None
    assert chat.send.call_args.kwargs['actor'].user_id == 1


@pytest.mark.parametrize('missing', [False, True])
def test_http_auth_version_revocation_or_deleted_account_denies_before_send(chat, missing):
    browser = chat.browser(1)
    if missing:
        del chat.states[1]
    else:
        chat.states[1]['AuthVersion'] = 2
    response = browser.post('/api/chat/send', json={'conversation_id': 2, 'content': 'must not send'})
    assert response.status_code == 401
    chat.send.assert_not_called()
    with browser.session_transaction() as cookie:
        assert 'user_id' not in cookie


def test_http_current_role_demotes_stale_admin_and_can_promote_current_customer(chat):
    admin = chat.browser(2)
    chat.states[2]['Role'] = 'customer'
    denied = admin.post('/api/chat/admin/send', json={'conversation_id': 1, 'content': 'not admin'})
    assert denied.status_code == 403
    chat.send.assert_not_called()
    customer = chat.browser(1)
    chat.states[1]['Role'] = 'admin'
    allowed = customer.post('/api/chat/admin/send', json={'conversation_id': 1, 'content': 'support reply'})
    assert allowed.status_code == 200
    assert allowed.get_json()['sender_type'] == 'admin'
    assert allowed.get_json()['sender_name'] == 'Current User 1'


@pytest.mark.parametrize(
    'method,path,payload',
    [
        ('get', '/api/chat/history?conversation_id=2', None),
        ('get', '/api/conversations/2', None),
        ('get', '/api/conversations/2/participants', None),
        ('get', '/api/chat/conversations/2/pinned', None),
        ('get', '/api/conversations/2/attachments', None),
        ('get', '/api/chat/messages/3/reactions', None),
        ('post', '/api/chat/send', {'conversation_id': 2, 'content': 'denied'}),
        ('post', '/api/chat/messages/3/reactions', {'emoji': '\U0001f44d'}),
        ('post', '/api/chat/messages/3/recall', {}),
        ('post', '/api/chat/pin', {'conversation_id': 2, 'message_id': 3}),
        ('post', '/api/conversations/2/read', {}),
        ('post', '/api/conversations/2/participants', {'user_id': 2}),
        ('patch', '/api/conversations/2/settings', {'name': 'stolen'}),
        ('patch', '/api/conversations/2/participants/3', {'nickname': 'stolen'}),
    ],
)
def test_site_admin_is_not_an_implicit_private_participant(chat, method, path, payload, monkeypatch):
    monkeypatch.setattr(
        ConversationService,
        'add_participant',
        lambda cid, uid, **kwargs: chat.access(cid, permission='manage', **kwargs),
    )
    response = chat.browser(2).open(path, method=method.upper(), json=payload)
    assert response.status_code == 403
    assert response.get_json()['success'] is False
    assert chat.operations == []


def test_site_admin_can_serve_support_but_not_unrelated_group(chat):
    admin = chat.browser(2)
    assert admin.get('/api/chat/history?conversation_id=1').status_code == 200
    assert admin.get('/api/chat/history?conversation_id=3').status_code == 403
    response = admin.post('/api/chat/admin/send', json={'conversation_id': 1, 'content': 'support only'})
    assert response.status_code == 200
    assert response.get_json()['user_id'] == 2


@pytest.mark.parametrize('payload', [[], None, 'text', 12])
def test_http_send_requires_json_object(chat, payload):
    response = chat.browser(1).post('/api/chat/send', json=payload)
    assert response.status_code == 400
    chat.send.assert_not_called()


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'limit=bad', 'before_id=0', 'before_id=bad'])
def test_history_validates_pagination_before_querying_service(chat, query):
    response = chat.browser(1).get(f'/api/chat/history?conversation_id=2&{query}')
    assert response.status_code == 400


def test_reply_must_belong_to_same_conversation_or_exact_guest_scope(chat):
    browser = chat.browser(1)
    denied = browser.post('/api/chat/send', json={'conversation_id': 2, 'content': 'reply', 'reply_to_id': 1})
    assert denied.status_code == 403
    allowed = browser.post('/api/chat/send', json={'conversation_id': 2, 'content': 'reply', 'reply_to_id': 3})
    assert allowed.status_code == 200
    assert allowed.get_json()['reply_to_id'] == 3
    guest, issued = chat.guest()
    other, other_issued = chat.guest()
    parent = guest.post(
        '/api/chat/send', headers={'X-Chat-Token': issued['auth_token']}, json={'content': 'guest parent'}
    )
    assert parent.status_code == 200
    foreign = other.post(
        '/api/chat/send',
        headers={'X-Chat-Token': other_issued['auth_token']},
        json={'content': 'steal parent', 'reply_to_id': parent.get_json()['id']},
    )
    assert foreign.status_code == 403


def test_read_reaction_pin_recall_use_actual_user_and_required_permissions(chat):
    member, owner = chat.browser(3), chat.browser(1)
    reaction = member.post('/api/chat/messages/3/reactions', json={'emoji': '\U0001f44d', 'user_id': 1})
    assert reaction.status_code == 200
    assert ('add_reaction', 3, 3, '\U0001f44d') in chat.operations
    assert member.delete('/api/chat/messages/3/reactions?emoji=%F0%9F%91%8D').status_code == 200
    assert member.post('/api/conversations/2/read', json={'user_id': 1}).status_code == 200
    assert ('read', 2, 3) in chat.operations
    assert member.post('/api/chat/pin', json={'conversation_id': 2, 'message_id': 3}).status_code == 403
    assert owner.post('/api/chat/pin', json={'conversation_id': 1, 'message_id': 3}).status_code == 403
    assert owner.post('/api/chat/pin', json={'conversation_id': 2, 'message_id': 3}).status_code == 200
    assert owner.post('/api/chat/messages/3/recall').status_code == 403
    assert member.post('/api/chat/messages/3/recall').status_code == 200
    assert owner.get('/api/chat/messages/3/reactions').status_code == 404


def test_guest_support_read_is_noop_but_guest_mutation_requires_user_or_sender(chat):
    browser, issued = chat.guest()
    headers = {'X-Chat-Token': issued['auth_token']}
    assert browser.post(f'/api/conversations/{issued["session_id"]}/read', headers=headers).status_code == 200
    assert chat.operations == []
    message = browser.post('/api/chat/send', json={'content': 'guest'}, headers=headers).get_json()
    assert (
        browser.post(
            f'/api/chat/messages/{message["id"]}/reactions', json={'emoji': '\U0001f44d'}, headers=headers
        ).status_code
        == 401
    )
    assert browser.post(f'/api/chat/messages/{message["id"]}/recall', headers=headers).status_code == 200


@pytest.mark.parametrize(
    'path,payload',
    [
        ('/api/conversations/2/participants/me', {'role': 'admin'}),
        ('/api/conversations/2/participants/3', {'role': 'admin'}),
        ('/api/conversations/2/participants/1', {'nickname': 'stolen'}),
        ('/api/conversations/2/settings', {'name': 'stolen'}),
    ],
)
def test_member_cannot_self_promote_or_manage_other_participant(chat, path, payload):
    response = chat.browser(3).patch(path, json=payload)
    assert response.status_code == 403
    assert chat.operations == []


def test_private_upload_authorizes_before_decoder_or_write(chat, monkeypatch):
    decoder = Mock(wraps=AttachmentService.prepare_upload)
    monkeypatch.setattr(AttachmentService, 'prepare_upload', decoder)
    response = chat.browser(2).post(
        '/api/chat/upload',
        data={'conversation_id': '2', 'file': (BytesIO(b'not a real image'), 'image.png')},
        content_type='multipart/form-data',
    )
    assert response.status_code == 403
    decoder.assert_not_called()
    chat.send.assert_not_called()
    assert not Path(chat.app.config['UPLOAD_ROOT']).exists()


@pytest.mark.parametrize('failure,status', [('result', 503), ('database', 503), ('access', 403)])
def test_private_upload_cleans_written_file_after_send_failure(chat, monkeypatch, failure, status):
    def failed_send(*args, **kwargs):
        assert AttachmentService.storage_path(kwargs['attachment']['storage_name']).is_file()
        if failure == 'result':
            return {'success': False, 'message': 'synthetic unavailable'}
        if failure == 'database':
            raise psycopg2.OperationalError('synthetic private database detail')
        raise ChatAccessError('membership removed during upload')

    monkeypatch.setattr(ChatService, 'send_message', failed_send)
    response = chat.browser(1).post(
        '/api/chat/upload',
        data={'conversation_id': '2', 'file': (BytesIO(b'hello'), 'message.txt')},
        content_type='multipart/form-data',
    )
    assert response.status_code == status
    assert list((Path(chat.app.config['UPLOAD_ROOT']) / 'chat').glob('*')) == []
    assert len(chat.messages) == 3
    assert 'synthetic private database detail' not in response.get_data(as_text=True)


def uploaded(chat):
    browser = chat.browser(1)
    response = browser.post(
        '/api/chat/upload',
        data={'conversation_id': '2', 'file': (BytesIO(b'private attachment'), 'document.txt', 'text/html')},
        content_type='multipart/form-data',
    )
    assert response.status_code == 200
    return browser, response.get_json()


def test_successful_private_upload_returns_guarded_url_and_private_download_headers(chat):
    browser, result = uploaded(chat)
    assert result['status'] == 'success'
    assert result['file_type'] == 'file'
    assert result['file_url'].startswith('/api/chat/attachments/')
    assert 'storage_name' not in result['message']['attachments'][0]
    response = browser.get(result['file_url'])
    try:
        assert response.status_code == 200
        assert response.data == b'private attachment'
        assert response.mimetype == 'text/plain'
        assert 'attachment;' in response.headers['Content-Disposition']
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['Content-Security-Policy'] == "default-src 'none'; sandbox"
        assert response.headers['Referrer-Policy'] == 'no-referrer'
    finally:
        response.close()


def test_attachment_download_denies_nonparticipant_before_send_file(chat, monkeypatch):
    _, result = uploaded(chat)
    sender = Mock()
    monkeypatch.setattr('app.routes.chat.send_file', sender)
    response = chat.browser(2).get(result['file_url'])
    assert response.status_code == 403
    sender.assert_not_called()


def test_attachment_metadata_traversal_is_rejected_and_legacy_or_missing_files_not_exposed(chat, tmp_path):
    browser, result = uploaded(chat)
    aid = int(result['file_url'].rsplit('/', 1)[1])
    item = chat.attachments[aid]
    outside = tmp_path / 'outside.txt'
    outside.write_bytes(b'outside secret')
    original = item['storage_name']
    item['storage_name'] = '../outside.txt'
    assert browser.get(result['file_url']).status_code == 400
    assert outside.read_bytes() == b'outside secret'
    item['storage_name'] = None
    assert browser.get(result['file_url']).status_code == 404
    item['storage_name'] = original
    with chat.app.app_context():
        AttachmentService.storage_path(original).unlink()
    assert browser.get(result['file_url']).status_code == 404


@pytest.mark.parametrize('bad_csrf', [None, 'unsigned', 'different-browser'])
def test_socket_connect_requires_csrf_bound_to_current_flask_session(chat, bad_csrf):
    chat.app.config['WTF_CSRF_ENABLED'] = True
    browser = chat.browser(1)
    if bad_csrf == 'different-browser':
        token = csrf_for(chat.app, chat.browser(3))
    else:
        token = bad_csrf
    connection = chat.connect(browser=browser, auth={'csrf_token': token})
    assert connection.is_connected() is False
    assert chat.handlers.clients == {}
    assert chat.handlers.joined == {}
    valid = chat.connect(browser=browser, auth={'csrf_token': csrf_for(chat.app, browser)})
    assert valid.is_connected() is True


def test_socket_connect_rejects_unsigned_guest_cookie_replay_and_revoked_account(chat):
    assert chat.connect(auth={'auth_token': 'unsigned'}).is_connected() is False
    owner, issued = chat.guest()
    replay = chat.connect(browser=chat.browser(), auth={'auth_token': issued['auth_token']})
    assert replay.is_connected() is False
    guest = chat.connect(browser=owner, auth={'auth_token': issued['auth_token']})
    assert guest.is_connected() is True
    assert chat.handlers.joined[chat.sids[guest]] == {f'support_{issued["session_id"]}'}
    chat.states[1]['AuthVersion'] = 2
    assert chat.connect(1).is_connected() is False


def test_socket_guest_join_denies_foreign_scope_and_private_conversation(chat):
    browser, issued = chat.guest()
    connection = chat.connect(browser=browser, auth={'auth_token': issued['auth_token']})
    for payload, status in [
        ({'conversation_id': 2, 'room': 'conv_2'}, 401),
        ({'session_id': str(uuid.uuid4()), 'room': f'support_{issued["session_id"]}'}, 403),
    ]:
        # Each 401 deliberately revokes that connection; use a new signed-cookie connection.
        if not connection.is_connected():
            connection = chat.connect(browser=browser, auth={'auth_token': issued['auth_token']})
        result = connection.emit('join_conversation', payload, callback=True)
        assert result['success'] is False
        assert result['status'] == status
    assert chat.handlers.joined[chat.sids[connection]] == {f'support_{issued["session_id"]}'}


def test_socket_join_denies_private_admin_even_with_room_and_user_id_spoof(chat):
    admin = chat.connect(2)
    result = admin.emit('join_conversation', {'conversation_id': 2, 'room': 'conv_1', 'user_id': 1}, callback=True)
    assert result['success'] is False
    assert result['status'] == 403
    assert 'conv_2' not in chat.handlers.joined[chat.sids[admin]]
    assert packets(admin, 'error')[0]['status'] == 403


def test_socket_private_message_delivery_is_scoped_and_never_global_admin_broadcast(chat):
    sender, peer, admin = chat.connect(1), chat.connect(3), chat.connect(2)
    chat.join(sender, 2)
    chat.join(peer, 2)
    chat.join(admin, 1)
    result = sender.emit(
        'send_message',
        {
            'conversation_id': 2,
            'content': 'private',
            'room': 'conv_1',
            'target_user_id': 2,
            'sender_id': 2,
            'sender_name': 'Spoofed',
        },
        callback=True,
    )
    assert result['success'] is True
    assert result['user_id'] == 1
    sent = sender.get_received()
    assert any(packet['name'] == 'message_sent' for packet in sent)
    assert any(packet['name'] == 'new_message' for packet in sent)
    incoming = packets(peer, 'new_message')
    assert len(incoming) == 1
    assert incoming[0]['conversation_id'] == 2
    assert incoming[0]['sender_name'] == 'Current User 1'
    assert incoming[0]['sender_id'] == 1
    assert 'success' not in incoming[0]
    assert admin.get_received() == []


def test_socket_support_delivery_only_reaches_owner_and_current_admin(chat):
    owner_browser, owner_token = chat.guest()
    other_browser, other_token = chat.guest()
    owner = chat.connect(browser=owner_browser, auth={'auth_token': owner_token['auth_token']})
    other = chat.connect(browser=other_browser, auth={'auth_token': other_token['auth_token']})
    admin, unrelated = chat.connect(2), chat.connect(3)
    response = owner.emit(
        'send_message', {'content': 'support question', 'session_id': owner_token['session_id']}, callback=True
    )
    assert response['success'] is True
    assert packets(admin, 'new_message')[0]['session_id'] == owner_token['session_id']
    assert other.get_received() == []
    assert unrelated.get_received() == []
    chat.states[2]['Role'] = 'customer'
    assert owner.emit('typing', {'session_id': owner_token['session_id']}, callback=True)['success'] is True
    assert admin.get_received() == []


def test_socket_typing_uses_authoritative_identity_scope_and_excludes_sender(chat):
    sender, peer, admin = chat.connect(1), chat.connect(3), chat.connect(2)
    chat.join(sender, 2)
    chat.join(peer, 2)
    for event, expected in [('typing', 'typing'), ('stop_typing', 'stop_typing')]:
        response = sender.emit(
            event, {'conversation_id': 2, 'user_id': 2, 'user_name': 'Spoofed', 'room': 'conv_1'}, callback=True
        )
        assert response['success'] is True
        payload = packets(peer, expected)[0]
        assert payload['user_id'] == 1
        assert payload['user_name'] == 'Current User 1'
        assert payload['is_admin'] is False
        assert payload['conversation_id'] == 2
        assert sender.get_received() == []
        assert admin.get_received() == []


@pytest.mark.parametrize('event', ['admin_reply', 'admin_typing', 'admin_stop_typing'])
def test_socket_admin_events_recheck_current_role_each_time(chat, event):
    connection = chat.connect(2)
    chat.states[2]['Role'] = 'customer'
    result = connection.emit(event, {'conversation_id': 1, 'content': 'denied'}, callback=True)
    assert result['success'] is False
    assert result['status'] == 403
    assert connection.is_connected()
    assert chat.handlers.clients[chat.sids[connection]].is_admin is False
    chat.send.assert_not_called()


def test_socket_stale_sender_is_disconnected_before_any_mutation(chat):
    sender, peer = chat.connect(1), chat.connect(3)
    chat.join(peer, 2)
    chat.states[1]['AuthVersion'] = 2
    response = sender.emit('send_message', {'conversation_id': 2, 'content': 'stale'}, callback=True)
    assert response['status'] == 401
    assert sender.is_connected() is False
    assert chat.sids[sender] not in chat.handlers.clients
    chat.send.assert_not_called()
    assert peer.get_received() == []


def test_socket_stale_recipient_is_revoked_without_revoking_valid_sender(chat):
    sender, peer = chat.connect(1), chat.connect(3)
    chat.join(sender, 2)
    chat.join(peer, 2)
    chat.states[3]['AuthVersion'] = 2
    result = sender.emit('send_message', {'conversation_id': 2, 'content': 'fresh'}, callback=True)
    assert result['success'] is True
    assert sender.is_connected() is True
    assert peer.is_connected() is False
    assert chat.sids[peer] not in chat.handlers.clients
    assert packets(sender, 'new_message')[0]['content'] == 'fresh'


def test_socket_membership_removed_after_join_drops_room_and_denies_sender(chat):
    sender, removed = chat.connect(1), chat.connect(3)
    chat.join(sender, 2)
    chat.join(removed, 2)
    del chat.conversations[2]['members'][3]
    assert (
        sender.emit('send_message', {'conversation_id': 2, 'content': 'after removal'}, callback=True)['success']
        is True
    )
    assert removed.get_received() == []
    assert 'conv_2' not in chat.handlers.joined[chat.sids[removed]]
    denied = removed.emit('send_message', {'conversation_id': 2, 'content': 'not member'}, callback=True)
    assert denied['status'] == 403
    assert removed.is_connected() is True


def test_http_leave_immediately_evicts_all_user_tabs_and_ends_bound_call(chat):
    browser = chat.browser(3)
    sender = chat.connect(1)
    peer = chat.connect(browser=browser)
    other_tab = chat.connect(browser=browser)
    chat.join(peer, 2)
    chat.join(other_tab, 2)
    assert ring(chat, sender)['success'] is True
    peer.get_received()
    assert browser.post('/api/conversations/2/leave').status_code == 200
    assert chat.handlers.calls == {}
    assert packets(sender, 'call_ended')[0]['reason'] == 'left_conversation'
    assert 'conv_2' not in chat.handlers.joined[chat.sids[peer]]
    assert 'conv_2' not in chat.handlers.joined[chat.sids[other_tab]]
    assert (
        sender.emit('send_message', {'conversation_id': 2, 'content': 'after leave'}, callback=True)['success'] is True
    )
    assert peer.get_received() == []
    assert other_tab.get_received() == []


@pytest.mark.parametrize('payload', [None, [], 'text', 1])
def test_socket_rejects_nonobject_events_with_validation_ack(chat, payload):
    connection = chat.connect(1)
    result = connection.emit('send_message', payload, callback=True)
    assert result['success'] is False
    assert result['status'] == 400
    chat.send.assert_not_called()
    assert packets(connection, 'error')[0]['status'] == 400


@pytest.mark.parametrize('failure', ['result', 'database'])
def test_socket_send_failure_emits_safe_error_without_delivery_or_sent_ack(chat, monkeypatch, failure):
    connection, peer = chat.connect(1), chat.connect(3)
    chat.join(peer, 2)
    if failure == 'result':
        monkeypatch.setattr(
            ChatService, 'send_message', lambda *args, **kwargs: {'success': False, 'message': 'unavailable'}
        )
    else:

        def failed(*args, **kwargs):
            raise psycopg2.OperationalError('secret database connection detail')

        monkeypatch.setattr(ChatService, 'send_message', failed)
    result = connection.emit('send_message', {'conversation_id': 2, 'content': 'failure'}, callback=True)
    assert result['success'] is False
    received = connection.get_received()
    assert [packet['name'] for packet in received] == ['error']
    assert received[0]['args'][0]['status'] == 503
    assert 'secret database' not in str(received)
    assert peer.get_received() == []
    assert connection.is_connected()


@pytest.mark.parametrize(
    'event,payload,expected_event,uid',
    [
        ('add_reaction', {'message_id': 3, 'emoji': '\U0001f44d', 'user_id': 2}, 'reaction_update', 3),
        ('remove_reaction', {'message_id': 3, 'emoji': '\U0001f44d', 'user_id': 2}, 'reaction_update', 3),
        ('pin_message', {'message_id': 3}, 'message_pinned', 1),
        ('unpin_message', {'message_id': 3}, 'message_unpinned', 1),
        ('mark_read', {'user_id': 2}, 'messages_read', 3),
        ('update_conversation_settings', {'settings': {'name': 'New group'}}, 'conversation_settings_updated', 1),
        ('recall_message', {'message_id': 3}, 'message_recalled', 3),
    ],
)
def test_socket_mutations_are_authorized_and_broadcast_only_in_message_scope(chat, event, payload, expected_event, uid):
    actor = chat.connect(uid)
    peer = chat.connect(1 if uid == 3 else 3)
    admin = chat.connect(2)
    chat.join(actor, 2)
    chat.join(peer, 2)
    result = actor.emit(event, {'conversation_id': 2, 'room': 'conv_1', **payload}, callback=True)
    assert result['success'] is True
    delivered = packets(peer, expected_event)
    assert len(delivered) == 1
    assert delivered[0]['conversation_id'] == 2
    if 'user_id' in delivered[0]:
        assert delivered[0]['user_id'] == uid
    assert admin.get_received() == []
    assert chat.operations


@pytest.mark.parametrize(
    'event,payload,service,method',
    [
        ('add_reaction', {'message_id': 3, 'emoji': '\U0001f44d'}, ChatService, 'add_reaction'),
        ('remove_reaction', {'message_id': 3, 'emoji': '\U0001f44d'}, ChatService, 'remove_reaction'),
        ('recall_message', {'message_id': 3}, ChatService, 'recall_message'),
        ('pin_message', {'message_id': 3}, ChatService, 'pin_message'),
        ('unpin_message', {'message_id': 3}, ChatService, 'unpin_message'),
        ('mark_read', {}, ConversationService, 'mark_as_read'),
        (
            'update_conversation_settings',
            {'settings': {'name': 'No update'}},
            ConversationService,
            'update_conversation_settings',
        ),
        (
            'update_participant_settings',
            {'user_id': 3, 'settings': {'nickname': 'No update'}},
            ConversationService,
            'update_participant_settings',
        ),
    ],
)
def test_socket_mutation_false_result_returns_503_without_broadcast(chat, monkeypatch, event, payload, service, method):
    actor_uid = 3 if event == 'recall_message' else 1
    actor, peer = chat.connect(actor_uid), chat.connect(1 if actor_uid == 3 else 3)
    chat.join(actor, 2)
    chat.join(peer, 2)
    monkeypatch.setattr(service, method, lambda *args, **kwargs: False)

    result = actor.emit(event, {'conversation_id': 2, **payload}, callback=True)

    assert result['success'] is False and result['status'] == 503
    assert [packet['name'] for packet in actor.get_received()] == ['error']
    assert peer.get_received() == []
    assert actor.is_connected()


def test_socket_owner_cannot_change_own_role_after_manage_authorization(chat):
    owner = chat.connect(1)
    result = owner.emit(
        'update_participant_settings',
        {'conversation_id': 2, 'user_id': 1, 'settings': {'role': 'member'}},
        callback=True,
    )
    assert result['success'] is False and result['status'] == 403
    assert chat.operations == []


@pytest.mark.parametrize(
    'event,payload',
    [
        ('add_reaction', {'message_id': 1, 'emoji': '\U0001f44d'}),
        ('recall_message', {'message_id': 1}),
        ('pin_message', {'message_id': 1}),
        ('mark_read', {}),
        ('update_conversation_settings', {'settings': {'name': 'stolen'}}),
    ],
)
def test_socket_permission_denial_does_not_mutate_or_broadcast(chat, event, payload):
    outsider, peer = chat.connect(2), chat.connect(3)
    chat.join(peer, 2)
    result = outsider.emit(event, {'conversation_id': 2, **payload}, callback=True)
    assert result['success'] is False
    assert result['status'] == 403
    assert chat.operations == []
    assert peer.get_received() == []


def test_socket_mute_settings_are_personal_and_cannot_self_promote(chat):
    member, peer = chat.connect(3), chat.connect(1)
    chat.join(member, 2)
    chat.join(peer, 2)
    result = member.emit(
        'update_participant_settings', {'conversation_id': 2, 'settings': {'is_muted': True}}, callback=True
    )
    assert result['success'] is True
    assert packets(member, 'participant_settings_updated')[0]['settings'] == {'is_muted': True}
    assert peer.get_received() == []
    denied = member.emit(
        'update_participant_settings', {'conversation_id': 2, 'settings': {'role': 'admin'}}, callback=True
    )
    assert denied['status'] == 403
    assert len(chat.operations) == 1
    assert peer.get_received() == []


def test_socket_nickname_is_shared_but_mute_is_stripped_from_public_update(chat):
    member, peer = chat.connect(3), chat.connect(1)
    chat.join(member, 2)
    chat.join(peer, 2)
    response = member.emit(
        'update_participant_settings',
        {'conversation_id': 2, 'settings': {'nickname': 'New nickname', 'is_muted': True}},
        callback=True,
    )
    assert response['success'] is True
    assert packets(peer, 'participant_settings_updated')[0]['settings'] == {'nickname': 'New nickname'}
    own = packets(member, 'participant_settings_updated')
    assert any(packet['settings'] == {'nickname': 'New nickname', 'is_muted': True} for packet in own)


def test_single_peer_offer_binds_two_sids_and_only_one_recipient_tab(chat):
    caller, callee, extra_tab, admin = chat.connect(1), chat.connect(3), chat.connect(3), chat.connect(2)
    result = ring(chat, caller)
    assert result == {'success': True, 'call_id': CALL_ID}
    call = chat.handlers.calls[CALL_ID]
    assert call['sids'] == (chat.sids[caller], chat.sids[callee])
    assert call['user_ids'] == (1, 3)
    assert call['phase'] == 'ringing'
    assert call['awaiting_answer'] == chat.sids[callee]
    incoming = packets(callee, 'incoming_call')
    assert len(incoming) == 1
    assert incoming[0]['offer'] == OFFER
    assert incoming[0]['sender_id'] == 1
    assert incoming[0]['sender_name'] == 'Current User 1'
    assert incoming[0]['call_id'] == CALL_ID
    assert incoming[0]['conversation_id'] == 2
    assert incoming[0]['isVideo'] is False
    assert extra_tab.get_received() == []
    assert admin.get_received() == []
    assert chat.timers[0].started and chat.timers[0].daemon
    assert chat.timers[0].interval == 30
    assert ring(chat, caller)['success'] is True
    assert callee.get_received() == []
    assert len(chat.timers) == 1


@pytest.mark.parametrize(
    'data',
    [
        {'call_id': 'short'},
        {'call_id': 'x' * 65},
        {'call_id': '../' + 'x' * 16},
        {'offer': None},
        {'offer': {'type': 'answer', 'sdp': 'wrong type'}},
        {'offer': {'type': 'offer', 'sdp': ''}},
        {'offer': {'type': 'offer', 'sdp': 'x' * 65537}},
        {'isVideo': 1},
        {'isVideo': 'true'},
    ],
)
def test_call_offer_and_call_id_validation_prevents_ring(chat, data):
    caller, callee = chat.connect(1), chat.connect(3)
    payload = {'conversation_id': 2, 'call_id': CALL_ID, 'offer': OFFER, 'isVideo': True, **data}
    result = caller.emit('call_user', payload, callback=True)
    assert result['success'] is False
    assert result['status'] == 400
    assert chat.handlers.calls == {}
    assert callee.get_received() == []
    assert chat.timers == []


@pytest.mark.parametrize('cid,uid,status', [(1, 1, 409), (3, 1, 409), (2, 2, 403)])
def test_calls_require_private_two_member_conversation_not_support_group_or_site_admin(chat, cid, uid, status):
    caller = chat.connect(uid)
    callee = chat.connect(3)
    result = caller.emit('call_user', {'conversation_id': cid, 'call_id': CALL_ID, 'offer': OFFER}, callback=True)
    assert result['status'] == status
    assert chat.handlers.calls == {}
    assert callee.get_received() == []


def test_call_cannot_choose_nonparticipant_target_or_accept_three_member_private_room(chat):
    caller, callee, admin = chat.connect(1), chat.connect(3), chat.connect(2)
    denied = signal(caller, 'call_user', offer=OFFER, target_user_id=2)
    assert denied['status'] == 403
    chat.conversations[2]['members'][2] = 'member'
    malformed_private = signal(caller, 'call_user', offer=OFFER)
    assert malformed_private['status'] == 409
    assert chat.handlers.calls == {}
    assert callee.get_received() == []
    assert admin.get_received() == []


def test_call_offline_peer_and_busy_participant_are_explicit_conflicts(chat):
    caller = chat.connect(1)
    offline = ring(chat, caller)
    assert offline['status'] == 409
    assert chat.handlers.calls == {}
    callee = chat.connect(3)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    busy = signal(caller, 'call_user', offer=OFFER, call_id='call_second0123456789')
    assert busy['status'] == 409
    assert len(chat.handlers.calls) == 1
    assert callee.get_received() == []
    reused = signal(callee, 'call_user', offer=OFFER, target_user_id=1)
    assert reused['status'] == 409


@pytest.mark.parametrize(
    'event,extra',
    [
        ('answer_call', {'answer': ANSWER}),
        ('reject_call', {}),
        ('end_call', {}),
        ('ice_candidate', {'candidate': ICE}),
        ('call_resume', {}),
        ('stream_status', {'is_streaming': True}),
        ('call_chat_message', {'text': 'private'}),
        ('media_status', {'type': 'mic', 'enabled': True}),
    ],
)
def test_call_signals_are_bound_to_two_sids_not_same_user_other_tab(chat, event, extra):
    caller, callee, other_tab, admin = chat.connect(1), chat.connect(3), chat.connect(3), chat.connect(2)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    for attacker in [other_tab, admin]:
        result = signal(attacker, event, **extra)
        assert result['success'] is False
        assert result['status'] == 409
        assert result['call_id'] == CALL_ID
        assert caller.get_received() == []
        assert callee.get_received() == []
    assert chat.handlers.calls[CALL_ID]['phase'] == 'ringing'


@pytest.mark.parametrize('change', [{'conversation_id': 1}, {'call_id': 'call_other0123456789'}])
def test_call_signals_cannot_retarget_scope_or_unknown_call_id(chat, change):
    caller, callee = chat.connect(1), chat.connect(3)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    denied = signal(callee, 'ice_candidate', candidate=ICE, **change)
    assert denied['status'] == 409
    assert caller.get_received() == []
    assert chat.handlers.calls[CALL_ID]['phase'] == 'ringing'


def test_only_awaited_callee_can_answer_and_duplicate_answer_does_not_signal(chat):
    caller, callee = chat.connect(1), chat.connect(3)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    assert signal(caller, 'answer_call', answer=ANSWER)['status'] == 409
    assert callee.get_received() == []
    caller.get_received()
    assert signal(callee, 'answer_call', answer=ANSWER)['success'] is True
    answered = packets(caller, 'call_answered')
    assert len(answered) == 1
    assert answered[0]['answer'] == ANSWER
    assert answered[0]['sender_id'] == 3
    assert answered[0]['sender_name'] == 'Current User 3'
    assert chat.handlers.calls[CALL_ID]['phase'] == 'active'
    assert chat.handlers.calls[CALL_ID]['awaiting_answer'] is None
    assert chat.timers[0].cancelled
    assert signal(callee, 'answer_call', answer=ANSWER)['status'] == 409
    assert caller.get_received() == []
    chat.timers[0].fire()  # A callback racing cancellation must not terminate an active call.
    assert CALL_ID in chat.handlers.calls


@pytest.mark.parametrize(
    'candidate',
    [
        None,
        {},
        {'candidate': ''},
        {'candidate': 'x' * 2049},
        {'candidate': 'ok', 'sdpMLineIndex': True},
        {'candidate': 'ok', 'sdpMLineIndex': -1},
        {'candidate': 'ok', 'sdpMLineIndex': 101},
        {'candidate': 'ok', 'sdpMLineIndex': '0'},
        {'candidate': 'ok', 'sdpMid': 'x' * 101},
    ],
)
def test_ice_payload_is_validated_without_relay(chat, candidate):
    caller, callee = chat.connect(1), chat.connect(3)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    result = signal(caller, 'ice_candidate', candidate=candidate)
    assert result['status'] == 400
    assert callee.get_received() == []
    assert CALL_ID in chat.handlers.calls


def test_ice_is_relayed_only_to_bound_peer_and_strips_untrusted_fields(chat):
    caller, callee, other_tab = chat.connect(1), chat.connect(3), chat.connect(3)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    response = signal(caller, 'ice_candidate', candidate={**ICE, 'user_id': 2, 'room': 'conv_1'}, target_user_id=2)
    assert response['success'] is True
    remote = packets(callee, 'remote_ice_candidate')[0]
    assert remote['candidate'] == ICE
    assert remote['sender_id'] == 1
    assert remote['call_id'] == CALL_ID
    assert other_tab.get_received() == []


@pytest.mark.parametrize(
    'event,extra',
    [
        ('call_resume', {}),
        ('stream_status', {'is_streaming': True}),
        ('call_chat_message', {'text': 'hidden until answered'}),
        ('media_status', {'type': 'mic', 'enabled': False}),
    ],
)
def test_active_only_call_signals_are_not_delivered_while_ringing(chat, event, extra):
    caller, callee = chat.connect(1), chat.connect(3)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    assert signal(caller, event, **extra)['status'] == 409
    assert callee.get_received() == []


@pytest.mark.parametrize(
    'event,extra,expected',
    [
        ('call_resume', {}, {}),
        ('stream_status', {'is_streaming': True}, {'is_streaming': True}),
        (
            'call_chat_message',
            {'text': '  private call text  ', 'timestamp': 'spoofed'},
            {'text': 'private call text', 'timestamp': None},
        ),
        ('media_status', {'type': 'cam', 'enabled': False}, {'type': 'cam', 'enabled': False}),
    ],
)
def test_active_call_media_and_chat_signals_stay_peer_only(chat, event, extra, expected):
    caller, callee = active_pair(chat)
    other_tab, admin = chat.connect(3), chat.connect(2)
    response = signal(caller, event, target_user_id=2, user_id=2, sender_name='Spoofed', **extra)
    assert response['success'] is True
    remote = packets(callee, event)
    assert len(remote) == 1
    assert remote[0]['sender_id'] == 1
    assert remote[0]['sender_name'] == 'Current User 1'
    for key, value in expected.items():
        assert remote[0][key] == value
    assert other_tab.get_received() == []
    assert admin.get_received() == []


@pytest.mark.parametrize(
    'event,extra',
    [
        ('stream_status', {'is_streaming': 1}),
        ('media_status', {'type': 'screen', 'enabled': True}),
        ('media_status', {'type': 'mic', 'enabled': 'true'}),
        ('call_chat_message', {'text': 'x' * 1001}),
        ('call_chat_message', {'text': None}),
    ],
)
def test_active_call_payload_validation_does_not_relay(chat, event, extra):
    caller, callee = active_pair(chat)
    assert signal(caller, event, **extra)['status'] == 400
    assert callee.get_received() == []


def test_call_resume_reoffer_has_one_outstanding_answer_and_preserves_same_two_sids(chat):
    caller, callee = active_pair(chat)
    sids = chat.handlers.calls[CALL_ID]['sids']
    result = signal(callee, 'call_user', offer=OFFER, isResume=True, isVideo=True)
    assert result['success'] is True
    incoming = packets(caller, 'incoming_call')[0]
    assert incoming['isResume'] is True
    assert incoming['sender_id'] == 3
    assert chat.handlers.calls[CALL_ID]['awaiting_answer'] == chat.sids[caller]
    assert signal(callee, 'call_user', offer=OFFER, isResume=True)['status'] == 409
    assert caller.get_received() == []
    assert signal(caller, 'answer_call', answer=ANSWER)['success'] is True
    assert packets(callee, 'call_answered')[0]['sender_id'] == 1
    assert chat.handlers.calls[CALL_ID]['sids'] == sids
    assert chat.handlers.calls[CALL_ID]['awaiting_answer'] is None
    assert len(chat.timers) == 1


def test_unsupported_livestream_group_watching_is_explicitly_denied(chat):
    caller, callee = active_pair(chat)
    result = signal(caller, 'request_stream', streamer_id=3)
    assert result['status'] == 409
    assert callee.get_received() == []


def test_only_ringing_callee_can_reject_and_rejection_cancels_timer(chat):
    caller, callee = chat.connect(1), chat.connect(3)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    assert signal(caller, 'reject_call')['status'] == 409
    caller.get_received()
    assert signal(callee, 'reject_call')['success'] is True
    assert packets(caller, 'call_rejected')[0]['reason'] == 'declined'
    assert chat.handlers.calls == {}
    assert chat.timers[0].cancelled
    assert signal(callee, 'end_call')['status'] == 409


@pytest.mark.parametrize('ending_uid', [1, 3])
def test_either_bound_peer_can_end_active_call_without_global_delivery(chat, ending_uid):
    caller, callee = active_pair(chat)
    admin = chat.connect(2)
    ending, peer = (caller, callee) if ending_uid == 1 else (callee, caller)
    assert signal(ending, 'end_call')['success'] is True
    assert packets(peer, 'call_ended')[0]['reason'] == 'ended'
    assert admin.get_received() == []
    assert chat.handlers.calls == {}
    assert signal(ending, 'ice_candidate', candidate=ICE)['status'] == 409


def test_ringing_call_times_out_without_any_further_client_event(chat):
    caller, callee = chat.connect(1), chat.connect(3)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    chat.timers[0].fire()
    assert packets(caller, 'call_ended')[0]['reason'] == 'timeout'
    assert packets(callee, 'call_ended')[0]['reason'] == 'timeout'
    assert chat.handlers.calls == {}
    assert chat.timers[0].cancelled
    assert signal(callee, 'answer_call', answer=ANSWER)['status'] == 409


def test_late_answer_expires_ring_using_monotonic_clock(chat):
    caller, callee = chat.connect(1), chat.connect(3)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    chat.now += 31
    response = signal(callee, 'answer_call', answer=ANSWER)
    assert response['status'] == 409
    assert packets(caller, 'call_ended')[0]['reason'] == 'timeout'
    assert chat.handlers.calls == {}


@pytest.mark.parametrize('disconnect_uid', [1, 3])
def test_disconnect_removes_bound_call_and_notifies_only_remaining_peer(chat, disconnect_uid):
    caller, callee = active_pair(chat)
    other_tab = chat.connect(3)
    leaving, remaining = (caller, callee) if disconnect_uid == 1 else (callee, caller)
    leaving.disconnect()
    assert chat.sids[leaving] not in chat.handlers.clients
    assert chat.sids[leaving] not in chat.handlers.joined
    assert chat.handlers.calls == {}
    assert packets(remaining, 'call_ended')[0]['reason'] == 'disconnected'
    assert other_tab.get_received() == []


def test_call_stale_recipient_revokes_that_sid_not_valid_sender(chat):
    caller, callee = active_pair(chat)
    chat.states[3]['AuthVersion'] = 2
    result = signal(caller, 'ice_candidate', candidate=ICE)
    assert result['success'] is False
    assert result['status'] == 409
    assert caller.is_connected() is True
    assert callee.is_connected() is False
    assert chat.handlers.calls == {}
    assert packets(caller, 'call_ended')[0]['reason'] == 'access_revoked'


def test_call_membership_removal_invalidates_existing_signaling(chat):
    caller, callee = active_pair(chat)
    del chat.conversations[2]['members'][3]
    result = signal(caller, 'media_status', type='mic', enabled=True)
    assert result['status'] == 409
    assert caller.is_connected() and callee.is_connected()
    assert packets(callee, 'call_ended')[0]['reason'] == 'access_revoked'
    assert chat.handlers.calls == {}


def test_close_cancels_timers_and_app_handler_state_is_not_shared(chat):
    caller, callee = chat.connect(1), chat.connect(3)
    assert ring(chat, caller)['success'] is True
    callee.get_received()
    other_app = Flask('isolated-chat-test')
    other = ChatSocketHandlers(Mock(), other_app)
    other.clients['isolated'] = SimpleNamespace(user_id=99)
    chat.handlers.close()
    assert chat.timers[0].cancelled
    assert chat.handlers.calls == chat.handlers.clients == chat.handlers.joined == {}
    chat.timers[0].fire()
    assert caller.get_received() == []
    assert callee.get_received() == []
    assert other.clients['isolated'].user_id == 99
    assert other.calls == {}
    other.close()
