"""Chat regressions against the guarded, disposable PostgreSQL test fixture.

These tests execute production services and inspect committed rows; no cursor
mock proves SQL behavior. Run serially only after acquiring the shared DB slot.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from threading import Barrier

from flask_wtf.csrf import generate_csrf
import pytest

from app import socketio
from app.database import CaseInsensitiveRecord
from app.services import attachment_storage
from app.services.attachment_service import AttachmentService
from app.services.chat_service import ChatService
from app.services.conversation_service import ChatAccessError, ChatIdentity


pytestmark = pytest.mark.integration
CALL_ID = 'db_call_0123456789abcdef'
OFFER = {'type': 'offer', 'sdp': 'v=0\r\no=disposable-test-offer'}
ANSWER = {'type': 'answer', 'sdp': 'v=0\r\no=disposable-test-answer'}
ICE = {'candidate': 'candidate:disposable-test', 'sdpMid': '0', 'sdpMLineIndex': 0}


def sign_in(client, uid=1, *, role=None, version=1):
    role = role or ('admin' if uid == 2 else 'customer')
    with client.session_transaction() as cookie:
        cookie.update(
            user_id=uid, user_name='Untrusted Cookie Name', role=role, is_admin=role == 'admin', auth_version=version
        )
    return client


def browser(app, uid=1, **kwargs):
    return sign_in(app.test_client(), uid, **kwargs)


def actor(uid=1, *, admin=False, version=1):
    return ChatIdentity(uid, is_admin=admin, name='Untrusted Actor Name', auth_version=version)


def one(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    connection.rollback()  # Do not hold a repeatable read/locks while services use pooled connections.
    return row


def rows(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        result = cursor.fetchall()
    connection.rollback()
    return result


def change(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
    connection.commit()


def send(client, content='New private message', cid=2, **extra):
    response = client.post('/api/chat/send', json={'conversation_id': cid, 'content': content, **extra})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['success'] is True
    return response.get_json()


def guest(app):
    client = app.test_client()
    response = client.post('/api/chat/guest-session')
    assert response.status_code == 200
    credentials = response.get_json()
    return client, credentials, {'X-Chat-Token': credentials['auth_token']}


def make_group(client):
    response = client.post(
        '/api/conversations', json={'type': 'group', 'name': 'Disposable group', 'participant_ids': [3]}
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()['id']


def upload(client, *, cid=2, raw=b'private file', name='private.txt', headers=None, sid=None):
    data = {'file': (BytesIO(raw), name)}
    if cid is not None:
        data['conversation_id'] = str(cid)
    if sid is not None:
        data['session_id'] = sid
    return client.post('/api/chat/upload', data=data, headers=headers or {}, content_type='multipart/form-data')


def attachment_row(connection, url):
    return one(connection, 'SELECT * FROM Attachments WHERE id = %s', (int(url.rsplit('/', 1)[1]),))


def received(connection, event):
    return [packet['args'][0] for packet in connection.get_received() if packet['name'] == event]


@pytest.fixture
def db_chat_sockets(db_app):
    connections = []
    handlers = db_app.extensions['chat_socket_handlers']

    def connect(uid=None, *, flask_client=None, auth=None):
        client = flask_client or browser(db_app, uid)
        before = set(handlers.clients)
        connection = socketio.test_client(db_app, flask_test_client=client, auth=auth)
        connections.append(connection)
        new = set(handlers.clients) - before
        sid = new.pop() if new else None
        return connection, client, sid

    try:
        yield connect
    finally:
        for connection in connections:
            if connection.is_connected():
                connection.disconnect()
        handlers.close()


def join(connection, cid=2):
    response = connection.emit('join_conversation', {'conversation_id': cid}, callback=True)
    assert response['success'] is True, response
    connection.get_received()


def call_signal(connection, event, **data):
    return connection.emit(event, {'conversation_id': 2, 'call_id': CALL_ID, **data}, callback=True)


def begin_call(caller):
    return call_signal(caller, 'call_user', offer=OFFER, target_user_id=3, isVideo=False)


@contextmanager
def download(client, url, **kwargs):
    response = client.get(url, **kwargs)
    try:
        yield response
    finally:
        response.close()


def test_seed_contract_uses_real_case_insensitive_rows_and_expected_private_members(db_connection):
    users = rows(db_connection, 'SELECT CustomerID, FullName, Role, auth_version FROM Customers ORDER BY CustomerID')
    assert all(isinstance(row, CaseInsensitiveRecord) for row in users)
    assert [(row.CustomerID, row.Role, row.auth_version) for row in users] == [
        (1, 'customer', 1),
        (2, 'admin', 1),
        (3, 'customer', 1),
    ]
    assert [
        row.user_id
        for row in rows(db_connection, 'SELECT user_id FROM Participants WHERE conversation_id=2 ORDER BY user_id')
    ] == [1, 3]
    assert [
        row.user_id
        for row in rows(db_connection, 'SELECT user_id FROM Participants WHERE conversation_id=1 ORDER BY user_id')
    ] == [1, 2]


def test_numeric_private_send_commits_authoritative_user_and_canonical_legacy_session(db_app, db_client, db_connection):
    sign_in(db_client, 1, role='admin')
    result = send(
        db_client,
        '  persisted private text  ',
        user_id=2,
        sender_type='admin',
        sender_name='Attacker',
        session_id='stolen',
    )
    stored = one(db_connection, 'SELECT * FROM Messages WHERE id=%s', (result['id'],))
    assert stored.content == result['content'] == 'persisted private text'
    assert stored.user_id == result['user_id'] == result['sender_id'] == 1
    assert stored.sender_type == result['sender_type'] == 'user'
    assert stored.conversation_id == result['conversation_id'] == 2
    assert stored.session_id == 'user_1'
    assert result['session_id'] is None
    assert result['sender_name'] == 'Test Customer'
    own = db_client.get('/api/chat/history?conversation_id=2').get_json()['messages']
    assert [message['id'] for message in own] == [3, result['id']]
    peer = browser(db_app, 3).get('/api/chat/history?conversation_id=2').get_json()['messages']
    assert [message['id'] for message in peer] == [3, result['id']]
    assert db_client.get('/api/chat/history?conversation_id=1').get_json()['messages'][0]['id'] == 1


@pytest.mark.parametrize(
    'method,path,payload',
    [
        ('GET', '/api/chat/history?conversation_id=2', None),
        ('GET', '/api/conversations/2', None),
        ('GET', '/api/conversations/2/participants', None),
        ('GET', '/api/chat/conversations/2/pinned', None),
        ('GET', '/api/conversations/2/attachments', None),
        ('GET', '/api/chat/messages/3/reactions', None),
        ('POST', '/api/chat/send', {'conversation_id': 2, 'content': 'forbidden'}),
        ('POST', '/api/chat/admin/send', {'conversation_id': 2, 'content': 'forbidden admin'}),
        ('POST', '/api/chat/messages/3/reactions', {'emoji': '\U0001f44d'}),
        ('DELETE', '/api/chat/messages/3/reactions?emoji=%F0%9F%91%8D', None),
        ('POST', '/api/chat/messages/3/recall', {}),
        ('POST', '/api/chat/pin', {'conversation_id': 2, 'message_id': 3}),
        ('POST', '/api/conversations/2/read', {}),
        ('POST', '/api/conversations/2/leave', {}),
        ('POST', '/api/conversations/2/participants', {'user_id': 2}),
        ('PATCH', '/api/conversations/2/settings', {'name': 'stolen'}),
        ('PATCH', '/api/conversations/2/participants/3', {'nickname': 'stolen'}),
    ],
)
def test_real_private_acl_denies_site_admin_on_every_read_and_mutation(db_client, db_connection, method, path, payload):
    sign_in(db_client, 2)
    response = db_client.open(path, method=method, json=payload)
    assert response.status_code == 403, response.get_json()
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 3
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Reactions').count == 0
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM PinnedMessages').count == 0
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Participants WHERE conversation_id=2').count == 2
    assert one(db_connection, 'SELECT is_deleted FROM Messages WHERE id=3').is_deleted is False


def test_support_admin_without_membership_can_serve_support_but_cannot_read_receipt(db_app, db_connection):
    change(db_connection, 'DELETE FROM Participants WHERE conversation_id=1 AND user_id=2')
    admin = browser(db_app, 2)
    assert [row['id'] for row in admin.get('/api/chat/history?conversation_id=1').get_json()['messages']] == [1, 2]
    result = admin.post('/api/chat/admin/send', json={'conversation_id': 1, 'content': 'actual support reply'})
    assert result.status_code == 200, result.get_json()
    stored = one(
        db_connection,
        'SELECT user_id, sender_type, conversation_id FROM Messages WHERE id=%s',
        (result.get_json()['id'],),
    )
    assert (stored.user_id, stored.sender_type, stored.conversation_id) == (2, 'admin', 1)
    assert admin.post('/api/conversations/1/read').status_code == 403
    assert browser(db_app, 3).get('/api/chat/history?conversation_id=1').status_code == 403


def test_group_management_requires_group_role_not_site_role_and_owner_can_promote(db_app, db_client, db_connection):
    sign_in(db_client, 1)
    cid = make_group(db_client)
    assert [
        (row.user_id, row.role)
        for row in rows(
            db_connection, 'SELECT user_id,role FROM Participants WHERE conversation_id=%s ORDER BY user_id', (cid,)
        )
    ] == [(1, 'admin'), (3, 'member')]
    member, admin = browser(db_app, 3), browser(db_app, 2)
    assert admin.get(f'/api/chat/history?conversation_id={cid}').status_code == 403
    assert member.patch(f'/api/conversations/{cid}/settings', json={'name': 'forbidden'}).status_code == 403
    assert member.patch(f'/api/conversations/{cid}/participants/me', json={'role': 'admin'}).status_code == 403
    assert db_client.patch(f'/api/conversations/{cid}/participants/3', json={'role': 'admin'}).status_code == 200
    assert (
        one(db_connection, 'SELECT role FROM Participants WHERE conversation_id=%s AND user_id=3', (cid,)).role
        == 'admin'
    )
    assert member.patch(f'/api/conversations/{cid}/settings', json={'name': 'permitted manager'}).status_code == 200
    assert one(db_connection, 'SELECT name FROM Conversations WHERE id=%s', (cid,)).name == 'permitted manager'
    assert member.patch(f'/api/conversations/{cid}/participants/1', json={'role': 'member'}).status_code == 403
    assert db_client.post(f'/api/conversations/{cid}/participants', json={'user_id': 2}).status_code == 200
    assert (
        one(db_connection, 'SELECT role FROM Participants WHERE conversation_id=%s AND user_id=2', (cid,)).role
        == 'member'
    )


def test_direct_conversation_reuses_pair_and_private_room_cannot_add_third_member(db_client, db_connection):
    sign_in(db_client, 1)
    for _ in range(2):
        response = db_client.post('/api/conversations/direct', json={'user_id': 3})
        assert response.status_code == 200
        assert response.get_json()['conversation'] == {'id': 2, 'type': 'private'}
    assert one(db_connection, "SELECT COUNT(*) AS count FROM Conversations WHERE type='private'").count == 1
    assert db_client.post('/api/conversations/2/participants', json={'user_id': 2}).status_code == 400
    assert db_client.post('/api/conversations/direct', json={'user_id': 1}).status_code == 400
    assert db_client.post('/api/conversations/direct', json={'user_id': 999}).status_code == 400
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Participants WHERE conversation_id=2').count == 2


def test_new_direct_pair_concurrent_and_repeat_creation_commits_one_private_room(db_app, db_connection):
    pair_sql = """
        SELECT c.id, c.type, c.created_by FROM Conversations c
        JOIN Participants p1 ON p1.conversation_id = c.id
        JOIN Participants p2 ON p2.conversation_id = c.id
        WHERE p1.user_id = %s AND p2.user_id = %s ORDER BY c.id
    """
    # Users 2 and 3 share the seeded group, but have no private room to reuse.
    assert [(row.id, row.type) for row in rows(db_connection, pair_sql, (2, 3))] == [(3, 'group')]
    start = Barrier(2)

    def create(uid, target):
        client = browser(db_app, uid)
        start.wait(timeout=10)
        response = client.post('/api/conversations/direct', json={'user_id': target})
        assert response.status_code == 200, response.get_json()
        result = response.get_json()
        assert result['success'] is True, result
        return result['conversation']

    with ThreadPoolExecutor(max_workers=2) as executor:
        requests = [executor.submit(create, 2, 3), executor.submit(create, 3, 2)]
        concurrent = [request.result(timeout=20) for request in requests]
    cid = concurrent[0]['id']
    expected = {'id': cid, 'type': 'private'}
    assert concurrent == [expected, expected]
    assert cid not in {1, 2, 3}

    for uid, target in [(2, 3), (3, 2), (2, 3)]:
        response = browser(db_app, uid).post('/api/conversations/direct', json={'user_id': target})
        assert response.status_code == 200, response.get_json()
        assert response.get_json()['success'] is True
        assert response.get_json()['conversation'] == expected

    rooms = rows(db_connection, pair_sql, (2, 3))
    assert [(row.id, row.type) for row in rooms] == [(3, 'group'), (cid, 'private')]
    created = rooms[1]
    assert created.created_by in {2, 3}
    participants = rows(
        db_connection,
        'SELECT user_id, role FROM Participants WHERE conversation_id = %s ORDER BY user_id',
        (cid,),
    )
    assert [(row.user_id, row.role) for row in participants] == [
        (uid, 'admin' if uid == created.created_by else 'member') for uid in (2, 3)
    ]
    assert [
        row.user_id
        for row in rows(db_connection, 'SELECT user_id FROM Participants WHERE conversation_id = 3 ORDER BY user_id')
    ] == [1, 2, 3]


def test_real_reply_scope_rejects_other_conversation_and_deleted_parent_without_insert(db_client, db_connection):
    sign_in(db_client, 1)
    assert (
        db_client.post(
            '/api/chat/send', json={'conversation_id': 2, 'content': 'cross scope', 'reply_to_id': 1}
        ).status_code
        == 403
    )
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 3
    result = send(db_client, 'same scope reply', reply_to_id=3)
    assert result['parent_content'] == 'Synthetic private message'
    assert result['parent_sender_name'] == 'Test Other Customer'
    assert one(db_connection, 'SELECT reply_to_id FROM Messages WHERE id=%s', (result['id'],)).reply_to_id == 3
    change(db_connection, 'UPDATE Messages SET is_deleted=TRUE WHERE id=3')
    denied = db_client.post(
        '/api/chat/send', json={'conversation_id': 2, 'content': 'deleted parent', 'reply_to_id': 3}
    )
    assert denied.status_code == 403
    history = db_client.get('/api/chat/history?conversation_id=2').get_json()['messages']
    assert [row['id'] for row in history] == [result['id']]
    assert history[0]['parent_content'] is None
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 4


def test_real_guest_scope_never_ors_private_or_unrelated_messages_by_user(db_app, db_connection):
    owner, issued, headers = guest(db_app)
    other, other_issued, other_headers = guest(db_app)
    private = send(browser(db_app, 1), 'private owned by same sender')
    first = owner.post(
        '/api/chat/send', json={'content': 'guest support only', 'session_id': issued['session_id']}, headers=headers
    )
    assert first.status_code == 200
    mid = first.get_json()['id']
    assert owner.get('/api/chat/history', headers=headers).get_json()['messages'][0]['id'] == mid
    assert owner.get('/api/chat/history', headers=headers).get_json()['messages'][0]['id'] != private['id']
    assert other.get('/api/chat/history', headers=other_headers).get_json()['messages'] == []
    assert other.get('/api/chat/history', headers=headers).status_code == 401
    assert (
        owner.get(
            '/api/chat/history', query_string={'session_id': other_issued['session_id']}, headers=headers
        ).status_code
        == 403
    )
    cross_reply = other.post(
        '/api/chat/send', json={'content': 'foreign parent', 'reply_to_id': mid}, headers=other_headers
    )
    assert cross_reply.status_code == 403
    assert owner.get('/api/chat/history?conversation_id=2', headers=headers).status_code == 401
    current = one(db_connection, 'SELECT user_id, conversation_id, session_id FROM Messages WHERE id=%s', (mid,))
    assert current.user_id is None and current.conversation_id is None and current.session_id == issued['session_id']
    assert (
        owner.post(f'/api/chat/messages/{mid}/reactions', json={'emoji': '\U0001f44d'}, headers=headers).status_code
        == 401
    )
    assert owner.post(f'/api/chat/messages/{mid}/recall', headers=headers).status_code == 200
    assert one(db_connection, 'SELECT is_deleted FROM Messages WHERE id=%s', (mid,)).is_deleted is True


def test_read_and_reactions_are_membership_scoped_idempotent_and_authoritative(db_app, db_connection):
    member = browser(db_app, 3)
    for _ in range(2):
        assert (
            member.post('/api/chat/messages/3/reactions', json={'emoji': '\U0001f44d', 'user_id': 1}).status_code == 200
        )
    stored = rows(db_connection, 'SELECT user_id,emoji FROM Reactions WHERE message_id=3')
    assert [(row.user_id, row.emoji) for row in stored] == [(3, '\U0001f44d')]
    assert member.post('/api/conversations/2/read', json={'user_id': 1}).status_code == 200
    assert (
        one(db_connection, 'SELECT last_read_at FROM Participants WHERE conversation_id=2 AND user_id=3').last_read_at
        is not None
    )
    assert (
        one(db_connection, 'SELECT last_read_at FROM Participants WHERE conversation_id=2 AND user_id=1').last_read_at
        is None
    )
    assert member.delete('/api/chat/messages/3/reactions?emoji=%F0%9F%91%8D').status_code == 200
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Reactions').count == 0
    assert member.post('/api/chat/messages/3/reactions', json={'emoji': '<script>'}).status_code == 400
    assert browser(db_app, 2).post('/api/conversations/2/read').status_code == 403


def test_pin_requires_manager_same_scope_and_recall_requires_sender(db_app, db_connection):
    owner, member, admin = browser(db_app, 1), browser(db_app, 3), browser(db_app, 2)
    assert member.post('/api/chat/pin', json={'conversation_id': 2, 'message_id': 3}).status_code == 403
    assert owner.post('/api/chat/pin', json={'conversation_id': 1, 'message_id': 3}).status_code == 403
    for _ in range(2):
        assert owner.post('/api/chat/pin', json={'conversation_id': 2, 'message_id': 3}).status_code == 200
    pins = rows(db_connection, 'SELECT conversation_id,message_id,pinned_by FROM PinnedMessages')
    assert [(row.conversation_id, row.message_id, row.pinned_by) for row in pins] == [(2, 3, 1)]
    assert owner.post('/api/chat/messages/3/recall').status_code == 403
    assert admin.post('/api/chat/messages/1/recall').status_code == 403
    assert member.post('/api/chat/messages/3/recall').status_code == 200
    assert one(db_connection, 'SELECT is_deleted,deleted_at FROM Messages WHERE id=3').is_deleted is True
    assert one(db_connection, 'SELECT deleted_at FROM Messages WHERE id=3').deleted_at is not None
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM PinnedMessages').count == 0
    assert owner.get('/api/chat/history?conversation_id=2').get_json()['messages'] == []
    assert owner.get('/api/chat/messages/3/reactions').status_code == 404


def test_history_pagination_applies_id_window_and_chronological_order(db_client, db_connection):
    sign_in(db_client, 1)
    created = [send(db_client, f'pagination {i}')['id'] for i in range(4)]
    latest = db_client.get('/api/chat/history', query_string={'conversation_id': 2, 'limit': 2}).get_json()['messages']
    assert [row['id'] for row in latest] == created[-2:]
    older = db_client.get(
        '/api/chat/history', query_string={'conversation_id': 2, 'before_id': created[-2], 'limit': 2}
    ).get_json()['messages']
    assert [row['id'] for row in older] == created[:2]
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 7


def test_user_conversations_and_status_expose_only_actual_membership(db_app, db_client):
    sign_in(db_client, 1)
    assert {row['id'] for row in db_client.get('/api/conversations').get_json()['conversations']} == {1, 2, 3}
    assert {row['id'] for row in browser(db_app, 3).get('/api/conversations').get_json()['conversations']} == {2, 3}
    assert {row['id'] for row in browser(db_app, 2).get('/api/conversations').get_json()['conversations']} == {1, 3}
    assert browser(db_app, 3).get('/api/users/2/status').status_code == 200
    assert db_client.get('/api/users/3/status').status_code == 200
    assert db_client.get('/api/users/1/status').status_code == 200


def test_current_auth_version_and_role_are_read_from_database_not_cookie(db_app, db_connection):
    customer = browser(db_app, 1, role='admin')
    assert customer.post('/api/chat/admin/send', json={'conversation_id': 1, 'content': 'spoof'}).status_code == 403
    admin = browser(db_app, 2)
    change(db_connection, "UPDATE Customers SET IsAdmin=FALSE, Role='customer' WHERE CustomerID=2")
    assert admin.post('/api/chat/admin/send', json={'conversation_id': 1, 'content': 'demoted'}).status_code == 403
    with admin.session_transaction() as cookie:
        assert cookie['role'] == 'customer'
        assert cookie['is_admin'] is False
    change(db_connection, 'UPDATE Customers SET auth_version=auth_version+1 WHERE CustomerID=1')
    assert customer.post('/api/chat/send', json={'conversation_id': 2, 'content': 'revoked'}).status_code == 401
    with customer.session_transaction() as cookie:
        assert 'user_id' not in cookie
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 3


def test_stale_service_actor_is_revalidated_even_without_http_hook(db_app, db_connection):
    change(db_connection, 'UPDATE Customers SET auth_version=2 WHERE CustomerID=1')
    with db_app.app_context(), pytest.raises(ChatAccessError) as error:
        ChatService.send_message('admin', 'stale direct invocation', conversation_id=2, actor=actor(admin=True))
    assert error.value.status == 401
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 3


def test_leave_removes_access_and_transfers_owner_to_remaining_member(db_app, db_client, db_connection):
    sign_in(db_client, 1)
    assert db_client.post('/api/conversations/2/leave').status_code == 200
    assert (
        one(db_connection, 'SELECT COUNT(*) AS count FROM Participants WHERE conversation_id=2 AND user_id=1').count
        == 0
    )
    assert one(db_connection, 'SELECT created_by FROM Conversations WHERE id=2').created_by == 3
    assert one(db_connection, 'SELECT role FROM Participants WHERE conversation_id=2 AND user_id=3').role == 'admin'
    assert db_client.get('/api/chat/history?conversation_id=2').status_code == 403
    assert db_client.post('/api/chat/send', json={'conversation_id': 2, 'content': 'former member'}).status_code == 403
    assert browser(db_app, 3).get('/api/chat/history?conversation_id=2').status_code == 200
    assert browser(db_app, 3).post('/api/conversations/2/leave').status_code == 200
    assert one(db_connection, 'SELECT id FROM Conversations WHERE id=2') is None
    assert one(db_connection, 'SELECT id FROM Messages WHERE id=3') is None


def test_participant_personal_settings_do_not_leak_mute_to_other_members(db_app, db_connection):
    member, owner = browser(db_app, 3), browser(db_app, 1)
    response = member.patch(
        '/api/conversations/2/participants/me', json={'nickname': 'Personal nickname', 'is_muted': True}
    )
    assert response.status_code == 200
    personal = one(db_connection, 'SELECT nickname,is_muted FROM Participants WHERE conversation_id=2 AND user_id=3')
    assert personal.nickname == 'Personal nickname' and personal.is_muted is True
    self_view = member.get('/api/conversations/2/participants').get_json()['participants']
    peer_view = owner.get('/api/conversations/2/participants').get_json()['participants']
    assert next(row for row in self_view if row['id'] == 3)['is_muted'] is True
    assert next(row for row in peer_view if row['id'] == 3)['is_muted'] is None
    assert member.patch('/api/conversations/2/participants/me', json={'role': 'admin'}).status_code == 403
    assert member.patch('/api/conversations/2/participants/1', json={'nickname': 'stolen'}).status_code == 403
    assert owner.patch('/api/conversations/2/participants/3', json={'role': 'admin'}).status_code == 403


def test_upload_persists_message_and_attachment_atomically_and_returns_private_download(
    db_app, db_client, db_connection
):
    sign_in(db_client, 1)
    response = upload(db_client)
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    stored = attachment_row(db_connection, result['file_url'])
    message = one(
        db_connection,
        'SELECT user_id,conversation_id,message_type,session_id FROM Messages WHERE id=%s',
        (stored.message_id,),
    )
    assert (message.user_id, message.conversation_id, message.message_type, message.session_id) == (
        1,
        2,
        'file',
        'user_1',
    )
    assert stored.file_url == result['file_url'] == f'/api/chat/attachments/{stored.id}'
    assert stored.file_size == len(b'private file')
    assert stored.mime_type == 'text/plain'
    assert 'storage_name' not in result['message']['attachments'][0]
    with db_app.app_context():
        path = AttachmentService.storage_path(stored.storage_name)
    assert path.read_bytes() == b'private file'
    for client in [db_client, browser(db_app, 3)]:
        with download(client, result['file_url']) as served:
            assert served.status_code == 200
            assert served.data == b'private file'
            assert served.headers['Cache-Control'] == 'no-store'
            assert served.headers['Content-Security-Policy'] == "default-src 'none'; sandbox"
            assert served.headers['Referrer-Policy'] == 'no-referrer'
    with download(browser(db_app, 2), result['file_url']) as denied:
        assert denied.status_code == 403
    assert db_app.test_client().get(result['file_url']).status_code == 401
    assert db_client.get(f'/static/uploads/chat/{stored.storage_name}').status_code == 404


def test_upload_database_error_after_both_real_inserts_rolls_back_rows_and_removes_disk_file(
    db_app, db_client, db_connection, monkeypatch
):
    sign_in(db_client, 1)
    insert = attachment_storage.insert_attachment
    wrote = []

    def fail_after_insert(cursor, mid, attachment):
        result = insert(cursor, mid, attachment)
        path = AttachmentService.storage_path(attachment['storage_name'])
        assert path.is_file()
        wrote.append(path)
        # A real PostgreSQL failure inside the actual message/attachment transaction,
        # after both inserts, proves rollback through committed row readback.
        cursor.execute('SELECT 1 / 0')
        return result

    monkeypatch.setattr(attachment_storage, 'insert_attachment', fail_after_insert)
    response = upload(db_client)
    assert response.status_code == 503, response.get_json()
    assert len(wrote) == 1 and not wrote[0].exists()
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 3
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Attachments').count == 0
    assert 'division by zero' not in response.get_data(as_text=True)


def test_upload_denial_occurs_before_decoding_or_filesystem_write(db_app, db_client, db_connection, monkeypatch):
    sign_in(db_client, 2)
    called = []
    original = AttachmentService.prepare_upload

    def tracked(file):
        called.append(file)
        return original(file)

    monkeypatch.setattr(AttachmentService, 'prepare_upload', tracked)
    assert upload(db_client, raw=b'not an image', name='fake.png').status_code == 403
    assert called == []
    assert not Path(db_app.config['UPLOAD_ROOT']).exists()
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 3
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Attachments').count == 0


def test_upload_rechecks_membership_after_prepare_and_cleans_when_access_revoked(
    db_app, db_client, db_connection, monkeypatch
):
    sign_in(db_client, 1)
    original = AttachmentService.prepare_upload
    wrote = []

    def revoke_after_prepare(file):
        prepared = original(file)
        wrote.append(AttachmentService.storage_path(prepared['storage_name']))
        change(db_connection, 'DELETE FROM Participants WHERE conversation_id=2 AND user_id=1')
        return prepared

    monkeypatch.setattr(AttachmentService, 'prepare_upload', revoke_after_prepare)
    assert upload(db_client).status_code == 403
    assert len(wrote) == 1 and not wrote[0].exists()
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 3
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Attachments').count == 0


@pytest.mark.parametrize(
    'raw,name', [(b'not image', 'fake.png'), (b'not pdf', 'fake.pdf'), (b'MZ', 'file.exe'), (b'bad\x00text', 'bad.txt')]
)
def test_invalid_private_upload_never_persists_a_message_or_file(db_app, db_client, db_connection, raw, name):
    sign_in(db_client, 1)
    assert upload(db_client, raw=raw, name=name).status_code == 400
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 3
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Attachments').count == 0
    assert not Path(db_app.config['UPLOAD_ROOT']).exists()


def test_recall_deletes_attachment_reaction_pin_rows_and_disk_after_commit(db_app, db_client, db_connection):
    sign_in(db_client, 1)
    result = upload(db_client).get_json()
    assert result['success'] is True
    mid = result['message']['id']
    stored = attachment_row(db_connection, result['file_url'])
    with db_app.app_context():
        path = AttachmentService.storage_path(stored.storage_name)
    assert db_client.post('/api/chat/pin', json={'conversation_id': 2, 'message_id': mid}).status_code == 200
    assert (
        browser(db_app, 3).post(f'/api/chat/messages/{mid}/reactions', json={'emoji': '\U0001f44d'}).status_code == 200
    )
    assert browser(db_app, 3).post(f'/api/chat/messages/{mid}/recall').status_code == 403
    assert path.exists()
    assert db_client.post(f'/api/chat/messages/{mid}/recall').status_code == 200
    assert not path.exists()
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Attachments').count == 0
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Reactions').count == 0
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM PinnedMessages').count == 0
    assert one(db_connection, 'SELECT is_deleted FROM Messages WHERE id=%s', (mid,)).is_deleted is True
    assert db_client.get(result['file_url']).status_code == 404
    assert db_client.get('/api/conversations/2/attachments').get_json()['attachments'] == []


def test_attachment_database_path_traversal_and_legacy_public_rows_are_not_downloadable(
    db_app, db_client, db_connection, tmp_path
):
    sign_in(db_client, 1)
    result = upload(db_client).get_json()
    stored = attachment_row(db_connection, result['file_url'])
    outside = tmp_path / 'outside-secret.txt'
    outside.write_bytes(b'outside secret')
    change(db_connection, 'UPDATE Attachments SET storage_name=%s WHERE id=%s', ('../outside-secret.txt', stored.id))
    assert db_client.get(result['file_url']).status_code == 400
    assert outside.read_bytes() == b'outside secret'
    change(
        db_connection,
        'UPDATE Attachments SET storage_name=NULL, file_url=%s WHERE id=%s',
        ('/static/uploads/public.txt', stored.id),
    )
    assert db_client.get(result['file_url']).status_code == 404
    assert db_client.get('/api/conversations/2/attachments').get_json()['attachments'] == []


def test_guest_attachment_download_and_support_admin_reply_are_exact_signed_scope(db_app, db_connection):
    owner, issued, headers = guest(db_app)
    other, other_issued, other_headers = guest(db_app)
    response = upload(owner, cid=None, sid=issued['session_id'], headers=headers)
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    stored = attachment_row(db_connection, result['file_url'])
    message = one(
        db_connection, 'SELECT conversation_id,user_id,session_id FROM Messages WHERE id=%s', (stored.message_id,)
    )
    assert message.conversation_id is None and message.user_id is None and message.session_id == issued['session_id']
    with download(owner, result['file_url'], headers=headers) as served:
        assert served.status_code == 200 and served.data == b'private file'
    assert other.get(result['file_url'], headers=other_headers).status_code == 403
    assert other.get(result['file_url'], headers=headers).status_code == 401
    admin = browser(db_app, 2)
    with download(admin, result['file_url']) as served:
        assert served.status_code == 200
    reply = admin.post('/api/chat/admin/send', json={'session_id': issued['session_id'], 'content': 'reply to guest'})
    assert reply.status_code == 200
    assert {row['id'] for row in owner.get('/api/chat/history', headers=headers).get_json()['messages']} == {
        stored.message_id,
        reply.get_json()['id'],
    }
    assert other.get('/api/chat/history', headers=other_headers).get_json()['messages'] == []
    assert other_issued['session_id'] != issued['session_id']


def test_db_backed_socket_join_and_delivery_never_broadcast_private_to_admin(db_app, db_connection, db_chat_sockets):
    sender, _, _ = db_chat_sockets(1)
    peer, _, _ = db_chat_sockets(3)
    admin, _, admin_sid = db_chat_sockets(2)
    join(sender)
    join(peer)
    denial = admin.emit('join_conversation', {'conversation_id': 2, 'room': 'conv_1'}, callback=True)
    assert denial['status'] == 403
    admin.get_received()
    assert 'conv_2' not in db_app.extensions['chat_socket_handlers'].joined[admin_sid]
    result = sender.emit(
        'send_message',
        {'conversation_id': 2, 'content': 'socket private', 'user_id': 2, 'room': 'conv_1'},
        callback=True,
    )
    assert result['success'] is True
    delivered = received(peer, 'new_message')
    assert len(delivered) == 1
    assert delivered[0]['sender_id'] == 1 and delivered[0]['sender_name'] == 'Test Customer'
    assert delivered[0]['conversation_id'] == 2
    assert admin.get_received() == []
    assert one(db_connection, 'SELECT user_id,conversation_id FROM Messages WHERE id=%s', (result['id'],)).user_id == 1


def test_http_persisted_message_is_published_to_authorized_socket_peer_only(db_app, db_connection, db_chat_sockets):
    peer, _, _ = db_chat_sockets(3)
    admin, _, _ = db_chat_sockets(2)
    join(peer)
    result = send(browser(db_app, 1), 'HTTP to real socket')
    assert received(peer, 'new_message')[0]['id'] == result['id']
    assert admin.get_received() == []
    assert (
        one(db_connection, 'SELECT content FROM Messages WHERE id=%s', (result['id'],)).content == 'HTTP to real socket'
    )


def test_db_socket_membership_removal_and_auth_version_recipient_revocation(db_app, db_connection, db_chat_sockets):
    sender, _, _ = db_chat_sockets(1)
    peer, _, peer_sid = db_chat_sockets(3)
    join(sender)
    join(peer)
    change(db_connection, 'DELETE FROM Participants WHERE conversation_id=2 AND user_id=3')
    response = sender.emit(
        'send_message', {'conversation_id': 2, 'content': 'after actual membership removal'}, callback=True
    )
    assert response['success'] is True
    assert peer.get_received() == []
    assert 'conv_2' not in db_app.extensions['chat_socket_handlers'].joined[peer_sid]
    assert (
        peer.emit('send_message', {'conversation_id': 2, 'content': 'forbidden removed sender'}, callback=True)[
            'status'
        ]
        == 403
    )
    peer.get_received()
    change(db_connection, "INSERT INTO Participants (conversation_id,user_id,role) VALUES (2,3,'member')")
    join(peer)
    change(db_connection, 'UPDATE Customers SET auth_version=2 WHERE CustomerID=3')
    assert (
        sender.emit('send_message', {'conversation_id': 2, 'content': 'after recipient revocation'}, callback=True)[
            'success'
        ]
        is True
    )
    assert sender.is_connected() is True
    assert peer.is_connected() is False
    assert peer_sid not in db_app.extensions['chat_socket_handlers'].clients


def test_db_socket_sender_revocation_denies_before_insert(db_app, db_connection, db_chat_sockets):
    sender, _, sid = db_chat_sockets(1)
    peer, _, _ = db_chat_sockets(3)
    join(peer)
    change(db_connection, 'UPDATE Customers SET auth_version=2 WHERE CustomerID=1')
    result = sender.emit('send_message', {'conversation_id': 2, 'content': 'must not persist'}, callback=True)
    assert result['status'] == 401
    assert sender.is_connected() is False
    assert sid not in db_app.extensions['chat_socket_handlers'].clients
    assert peer.get_received() == []
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 3


def test_db_socket_current_admin_role_is_revoked_for_support_broadcast(db_app, db_connection, db_chat_sockets):
    guest_client, issued, _ = guest(db_app)
    owner, _, _ = db_chat_sockets(flask_client=guest_client, auth={'auth_token': issued['auth_token']})
    admin, _, _ = db_chat_sockets(2)
    response = owner.emit('send_message', {'content': 'support one'}, callback=True)
    assert response['success'] is True
    assert received(admin, 'new_message')[0]['session_id'] == issued['session_id']
    change(db_connection, "UPDATE Customers SET IsAdmin=FALSE,Role='customer' WHERE CustomerID=2")
    assert owner.emit('send_message', {'content': 'support two'}, callback=True)['success'] is True
    assert admin.get_received() == []
    denied = admin.emit('admin_reply', {'session_id': issued['session_id'], 'content': 'demoted'}, callback=True)
    assert denied['status'] == 403
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 5


def test_db_call_offer_answer_ice_end_are_bound_to_exactly_two_authenticated_sids(
    db_app, db_connection, db_chat_sockets
):
    caller, _, caller_sid = db_chat_sockets(1)
    callee, _, callee_sid = db_chat_sockets(3)
    other_tab, _, _ = db_chat_sockets(3)
    admin, _, _ = db_chat_sockets(2)
    assert begin_call(caller)['success'] is True
    incoming = received(callee, 'incoming_call')
    assert len(incoming) == 1
    assert incoming[0]['sender_id'] == 1 and incoming[0]['sender_name'] == 'Test Customer'
    assert incoming[0]['offer'] == OFFER
    assert other_tab.get_received() == [] and admin.get_received() == []
    call = db_app.extensions['chat_socket_handlers'].calls[CALL_ID]
    assert call['sids'] == (caller_sid, callee_sid)
    assert call_signal(other_tab, 'answer_call', answer=ANSWER)['status'] == 409
    assert call_signal(callee, 'answer_call', answer=ANSWER)['success'] is True
    assert received(caller, 'call_answered')[0]['sender_name'] == 'Test Other Customer'
    assert call_signal(caller, 'ice_candidate', candidate=ICE)['success'] is True
    assert received(callee, 'remote_ice_candidate')[0]['candidate'] == ICE
    assert other_tab.get_received()[0]['name'] == 'error'
    assert call_signal(callee, 'end_call')['success'] is True
    assert received(caller, 'call_ended')[0]['reason'] == 'ended'
    assert db_app.extensions['chat_socket_handlers'].calls == {}
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages').count == 3


def test_db_call_losing_peer_auth_revokes_peer_sid_not_sender(db_app, db_connection, db_chat_sockets):
    caller, _, _ = db_chat_sockets(1)
    callee, _, callee_sid = db_chat_sockets(3)
    assert begin_call(caller)['success'] is True
    callee.get_received()
    assert call_signal(callee, 'answer_call', answer=ANSWER)['success'] is True
    caller.get_received()
    change(db_connection, 'UPDATE Customers SET auth_version=2 WHERE CustomerID=3')
    denied = call_signal(caller, 'ice_candidate', candidate=ICE)
    assert denied['status'] == 409
    assert caller.is_connected() is True
    assert callee.is_connected() is False
    assert callee_sid not in db_app.extensions['chat_socket_handlers'].clients
    assert received(caller, 'call_ended')[0]['reason'] == 'access_revoked'
    assert db_app.extensions['chat_socket_handlers'].calls == {}


def test_db_http_leave_evicts_all_socket_tabs_and_ends_existing_call(db_app, db_connection, db_chat_sockets):
    caller, _, _ = db_chat_sockets(1)
    member_browser = browser(db_app, 3)
    callee, _, sid = db_chat_sockets(flask_client=member_browser)
    other_tab, _, other_sid = db_chat_sockets(flask_client=member_browser)
    join(callee)
    join(other_tab)
    assert begin_call(caller)['success'] is True
    callee.get_received()
    assert member_browser.post('/api/conversations/2/leave').status_code == 200
    handlers = db_app.extensions['chat_socket_handlers']
    assert handlers.calls == {}
    assert 'conv_2' not in handlers.joined[sid] and 'conv_2' not in handlers.joined[other_sid]
    assert received(caller, 'call_ended')[0]['reason'] == 'left_conversation'
    assert (
        one(db_connection, 'SELECT COUNT(*) AS count FROM Participants WHERE conversation_id=2 AND user_id=3').count
        == 0
    )
    assert (
        caller.emit('send_message', {'conversation_id': 2, 'content': 'after leave'}, callback=True)['success'] is True
    )
    assert callee.get_received() == [] and other_tab.get_received() == []


def test_db_socket_connect_checks_csrf_with_real_cookie_and_identity(db_app, db_chat_sockets):
    db_app.config['WTF_CSRF_ENABLED'] = True
    client = browser(db_app, 1)
    denied, _, _ = db_chat_sockets(flask_client=client, auth={'csrf_token': 'unsigned'})
    assert denied.is_connected() is False
    with client.session_transaction() as cookie:
        prior = dict(cookie)
    from flask import session

    with db_app.test_request_context():
        session.update(prior)
        token = generate_csrf()
        raw = session['csrf_token']
    with client.session_transaction() as cookie:
        cookie['csrf_token'] = raw
    accepted, _, sid = db_chat_sockets(flask_client=client, auth={'csrf_token': token})
    assert accepted.is_connected() is True
    assert db_app.extensions['chat_socket_handlers'].clients[sid].name == 'Test Customer'
