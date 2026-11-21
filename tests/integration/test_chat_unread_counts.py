"""Unread SQL/JSON regressions using the existing guarded PostgreSQL fixture.

Run serially, only in the coordinator's shared DB slot. These tests use
production services/routes and committed rows, never cursor substitutes.
"""

from datetime import datetime, timedelta
from io import BytesIO

import pytest

from app.services.attachment_service import AttachmentService
from app.services.conversation_service import ChatIdentity, ConversationService


pytestmark = pytest.mark.integration
BASE = datetime(2000, 1, 1, 12)


def sign_in(app, uid=1):
    client = app.test_client()
    role = 'admin' if uid == 2 else 'customer'
    with client.session_transaction() as cookie:
        cookie.update(user_id=uid, user_name='Synthetic User', role=role, is_admin=uid == 2, auth_version=1)
    return client


def one(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        result = cursor.fetchone()
    connection.rollback()  # Release the fixture transaction before a pooled service call.
    return result


def change(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
    connection.commit()


def create_room(connection, kind='private', *, members=(1, 3), read_at=None):
    with connection.cursor() as cursor:
        cursor.execute(
            'INSERT INTO Conversations (type, name, created_by) VALUES (%s, %s, %s) RETURNING id',
            (kind, f'Synthetic unread {kind}', members[0]),
        )
        cid = cursor.fetchone().id
        for uid in members:
            cursor.execute(
                """INSERT INTO Participants (conversation_id, user_id, role, joined_at, last_read_at)
                   VALUES (%s, %s, %s, %s, %s)""",
                (cid, uid, 'admin' if uid == members[0] else 'member', BASE, read_at if uid == 1 else None),
            )
    connection.commit()
    return cid


def insert_message(
    connection, cid, uid, at=BASE, *, content='Synthetic message', deleted=False, is_read=False, session_id=None
):
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO Messages
                   (conversation_id, user_id, sender_type, session_id, content, created_at, is_deleted, is_read)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                cid,
                uid,
                'admin' if uid == 2 else 'user',
                session_id or f'user_{uid}',
                content,
                at,
                deleted,
                is_read,
            ),
        )
        mid = cursor.fetchone().id
    connection.commit()
    return mid


def service_list(app, uid=1):
    with app.app_context():
        return ConversationService.get_user_conversations(
            uid, actor=ChatIdentity(uid, is_admin=uid == 2, auth_version=1)
        )


def listed_room(app, cid, uid=1):
    result = next(row for row in service_list(app, uid) if row['id'] == cid)
    assert type(result['unread_count']) is int
    assert result['unread_count'] >= 0
    return result


def api_list(client):
    response = client.get('/api/conversations')
    assert response.status_code == 200, response.get_json()
    return response.get_json()['conversations']


def send(client, cid, content):
    response = client.post('/api/chat/send', json={'conversation_id': cid, 'content': content})
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result['success'] is True
    return result


@pytest.mark.parametrize('kind', ['private', 'group'])
def test_null_read_cursor_counts_only_live_other_messages_without_participant_multiplication(
    db_app, db_connection, kind
):
    members = (1, 2, 3) if kind == 'group' else (1, 3)
    cid = create_room(db_connection, kind, members=members)
    insert_message(db_connection, cid, 3, content='First other message')
    insert_message(db_connection, cid, 1, BASE + timedelta(seconds=1), content='Own message')
    insert_message(
        db_connection,
        cid,
        2 if kind == 'group' else 3,
        BASE + timedelta(seconds=2),
        content='Other message with legacy global read flag',
        is_read=True,
    )
    insert_message(db_connection, cid, 3, BASE + timedelta(seconds=3), content='Recalled message', deleted=True)
    insert_message(db_connection, cid, 1, BASE + timedelta(seconds=4), content='Latest own message')
    row = listed_room(db_app, cid)
    assert row['last_read_at'] is None
    assert row['unread_count'] == 2
    assert row['last_message'] == 'Latest own message'  # Own sends affect preview, not unread.
    assert row['last_message_at'] == (BASE + timedelta(seconds=4)).isoformat()
    payload = next(room for room in api_list(sign_in(db_app)) if room['id'] == cid)
    assert type(payload['unread_count']) is int
    assert payload['unread_count'] == 2


@pytest.mark.parametrize('kind', ['private', 'group'])
def test_timestamp_cursor_is_strict_and_keeps_subsecond_precision(db_app, db_connection, kind):
    cid = create_room(db_connection, kind, read_at=BASE)
    insert_message(db_connection, cid, 3, BASE - timedelta(microseconds=1), content='Already read')
    insert_message(db_connection, cid, 3, BASE, content='Exactly at read cursor')
    insert_message(db_connection, cid, 3, BASE + timedelta(microseconds=1), content='Just after cursor')
    insert_message(db_connection, cid, 1, BASE + timedelta(microseconds=2), content='Own after cursor')
    insert_message(db_connection, cid, 3, BASE + timedelta(microseconds=3), deleted=True)
    insert_message(db_connection, cid, 3, BASE + timedelta(seconds=1), is_read=True)
    row = listed_room(db_app, cid)
    assert row['last_read_at'] == BASE.isoformat()
    assert row['unread_count'] == 2
    change(
        db_connection,
        'UPDATE Participants SET last_read_at=%s WHERE conversation_id=%s AND user_id=1',
        (BASE + timedelta(seconds=1), cid),
    )
    assert listed_room(db_app, cid)['unread_count'] == 0


@pytest.mark.parametrize('kind', ['private', 'group'])
def test_real_send_read_and_recall_update_each_participants_count_independently(db_app, db_connection, kind):
    cid = create_room(db_connection, kind)
    viewer, peer = sign_in(db_app, 1), sign_in(db_app, 3)
    assert listed_room(db_app, cid)['unread_count'] == 0
    first = send(peer, cid, 'Peer sends first')
    assert listed_room(db_app, cid, 1)['unread_count'] == 1
    assert listed_room(db_app, cid, 3)['unread_count'] == 0
    send(viewer, cid, 'Viewer replies without marking peer history read')
    assert listed_room(db_app, cid, 1)['unread_count'] == 1
    assert listed_room(db_app, cid, 3)['unread_count'] == 1

    for _ in range(2):  # A repeated read receipt remains idempotent.
        response = viewer.post(f'/api/conversations/{cid}/read')
        assert response.status_code == 200, response.get_json()
        assert response.get_json() == {'status': 'success'}
        assert listed_room(db_app, cid, 1)['unread_count'] == 0
        assert listed_room(db_app, cid, 3)['unread_count'] == 1
    watermark = one(
        db_connection, 'SELECT last_read_at FROM Participants WHERE conversation_id=%s AND user_id=1', (cid,)
    ).last_read_at
    assert watermark is not None
    first_created = one(db_connection, 'SELECT created_at FROM Messages WHERE id=%s', (first['id'],)).created_at
    assert watermark >= first_created
    assert listed_room(db_app, cid)['last_read_at'] == watermark.isoformat()

    own = send(viewer, cid, 'Own send after read')
    assert listed_room(db_app, cid, 1)['unread_count'] == 0
    assert listed_room(db_app, cid, 3)['unread_count'] == 2
    recalled = send(peer, cid, 'Peer sends then recalls')
    assert listed_room(db_app, cid, 1)['unread_count'] == 1
    assert listed_room(db_app, cid, 3)['unread_count'] == 2
    response = peer.post(f'/api/chat/messages/{recalled["id"]}/recall')
    assert response.status_code == 200, response.get_json()
    assert one(db_connection, 'SELECT is_deleted FROM Messages WHERE id=%s', (recalled['id'],)).is_deleted is True
    assert listed_room(db_app, cid, 1)['unread_count'] == 0
    assert listed_room(db_app, cid, 3)['unread_count'] == 2
    assert listed_room(db_app, cid)['last_message'] == own['content']
    assert next(room for room in api_list(viewer) if room['id'] == cid)['unread_count'] == 0


@pytest.mark.parametrize('kind', ['private', 'group'])
def test_only_current_membership_lists_a_room_not_creator_sender_site_admin_or_legacy_session(
    db_app, db_connection, kind
):
    allowed = create_room(db_connection, kind)
    hidden = create_room(db_connection, kind)
    insert_message(db_connection, allowed, 3, content='Authorized room message')
    insert_message(db_connection, hidden, 1, content='Viewer historical send')
    insert_message(db_connection, hidden, 3, BASE + timedelta(days=1), content='Hidden room message')
    change(db_connection, 'DELETE FROM Participants WHERE conversation_id=%s AND user_id=1', (hidden,))
    insert_message(
        db_connection, None, 3, BASE + timedelta(days=2), content='Unrelated support history', session_id='user_1'
    )
    own_rooms = service_list(db_app, 1)
    assert hidden not in {row['id'] for row in own_rooms}
    assert listed_room(db_app, allowed)['unread_count'] == 1
    assert listed_room(db_app, allowed)['last_message'] == 'Authorized room message'
    admin_rooms = service_list(db_app, 2)
    assert allowed not in {row['id'] for row in admin_rooms}
    assert hidden not in {row['id'] for row in admin_rooms}
    viewer, admin = sign_in(db_app, 1), sign_in(db_app, 2)
    for client in (viewer, admin):
        assert client.get(f'/api/chat/history?conversation_id={hidden}').status_code == 403
        assert hidden not in {row['id'] for row in api_list(client)}
    history = viewer.get(f'/api/chat/history?conversation_id={allowed}')
    assert history.status_code == 200
    assert [message['content'] for message in history.get_json()['messages']] == ['Authorized room message']
    assert all(row['id'] != 'user_1' for row in api_list(viewer))


def test_final_member_leave_removes_committed_attachment_rows_and_private_file(db_app, db_connection):
    cid = create_room(db_connection, 'group', members=(1,))
    owner = sign_in(db_app)
    response = owner.post(
        '/api/chat/upload',
        data={'conversation_id': str(cid), 'file': (BytesIO(b'Synthetic private attachment'), 'leave-proof.txt')},
    )
    assert response.status_code == 200, response.get_json()
    message_id = response.get_json()['message']['id']
    stored = one(db_connection, 'SELECT storage_name FROM Attachments WHERE message_id=%s', (message_id,))
    with db_app.app_context():
        path = AttachmentService.storage_path(stored.storage_name)
    assert path.is_file()

    assert owner.post(f'/api/conversations/{cid}/leave').status_code == 200

    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Conversations WHERE id=%s', (cid,)).count == 0
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages WHERE id=%s', (message_id,)).count == 0
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Attachments WHERE message_id=%s', (message_id,)).count == 0
    assert not path.exists()


def test_group_join_and_rejoin_keep_existing_full_visible_history_policy(db_app, db_connection):
    owner, newcomer = sign_in(db_app, 1), sign_in(db_app, 3)
    response = owner.post('/api/conversations', json={'type': 'group', 'name': 'History policy group'})
    assert response.status_code == 201, response.get_json()
    cid = response.get_json()['id']
    old_ids = [insert_message(db_connection, cid, 1, BASE + timedelta(seconds=n)) for n in range(2)]
    response = owner.post(f'/api/conversations/{cid}/participants', json={'user_id': 3})
    assert response.status_code == 200, response.get_json()
    participant = one(
        db_connection, 'SELECT joined_at,last_read_at FROM Participants WHERE conversation_id=%s AND user_id=3', (cid,)
    )
    assert participant.joined_at > BASE + timedelta(seconds=1)
    assert participant.last_read_at is None
    history = newcomer.get(f'/api/chat/history?conversation_id={cid}')
    assert history.status_code == 200
    assert [message['id'] for message in history.get_json()['messages']] == old_ids
    assert listed_room(db_app, cid, 3)['unread_count'] == 2  # Visible pre-join history is not silently excluded.
    assert listed_room(db_app, cid, 1)['unread_count'] == 0
    assert newcomer.post(f'/api/conversations/{cid}/read').status_code == 200
    assert listed_room(db_app, cid, 3)['unread_count'] == 0
    assert newcomer.post(f'/api/conversations/{cid}/leave').status_code == 200
    latest = send(owner, cid, 'Message while peer is not a member')
    assert cid not in {row['id'] for row in api_list(newcomer)}
    assert newcomer.get(f'/api/chat/history?conversation_id={cid}').status_code == 403
    assert owner.post(f'/api/conversations/{cid}/participants', json={'user_id': 3}).status_code == 200
    history = newcomer.get(f'/api/chat/history?conversation_id={cid}')
    assert history.status_code == 200
    assert [message['id'] for message in history.get_json()['messages']] == [*old_ids, latest['id']]
    assert listed_room(db_app, cid, 3)['last_read_at'] is None
    assert listed_room(db_app, cid, 3)['unread_count'] == 3


def test_legacy_null_sender_is_non_self_but_nullable_deletion_follows_visible_history(db_app, db_connection):
    cid = create_room(db_connection, 'support', members=(1, 2))
    anonymous = insert_message(db_connection, cid, None, content='Legacy anonymous numeric-room message')
    own = insert_message(db_connection, cid, 1, BASE + timedelta(seconds=1), content='Own support message')
    insert_message(db_connection, cid, None, BASE + timedelta(seconds=2), deleted=True)
    insert_message(db_connection, cid, None, BASE + timedelta(seconds=3), deleted=None)
    insert_message(db_connection, None, None, BASE + timedelta(seconds=4), session_id='user_1')
    assert listed_room(db_app, cid)['unread_count'] == 1  # SQL != would silently omit the NULL sender.
    assert listed_room(db_app, cid)['last_message'] == 'Own support message'
    viewer = sign_in(db_app)
    history = viewer.get(f'/api/chat/history?conversation_id={cid}')
    assert history.status_code == 200
    assert [message['id'] for message in history.get_json()['messages']] == [anonymous, own]
    assert viewer.post(f'/api/conversations/{cid}/read').status_code == 200
    assert listed_room(db_app, cid)['unread_count'] == 0


def test_publication_targets_track_membership_support_admin_and_auth_version(db_app, db_connection):
    private = create_room(db_connection, 'private', members=(1, 3))
    support = create_room(db_connection, 'support', members=(1,))
    with db_app.app_context():
        assert ConversationService.get_publication_targets(private) == [
            {'user_id': 1, 'auth_version': 1},
            {'user_id': 3, 'auth_version': 1},
        ]
        assert ConversationService.get_publication_targets(support) == [
            {'user_id': 1, 'auth_version': 1},
            {'user_id': 2, 'auth_version': 1},
        ]

    change(db_connection, 'DELETE FROM Participants WHERE conversation_id=%s AND user_id=3', (private,))
    change(db_connection, 'UPDATE Customers SET auth_version=2 WHERE CustomerID=1')
    with db_app.app_context():
        assert ConversationService.get_publication_targets(private) == [{'user_id': 1, 'auth_version': 2}]


def test_empty_own_only_and_recalled_only_rooms_have_integer_zero_not_null(db_app, db_connection):
    empty = create_room(db_connection)
    own_only = create_room(db_connection, 'group')
    recalled_only = create_room(db_connection, 'group')
    insert_message(db_connection, own_only, 1, content='Only my message')
    insert_message(db_connection, recalled_only, 3, deleted=True)
    rooms = {row['id']: row for row in api_list(sign_in(db_app))}
    for cid in (empty, own_only, recalled_only):
        assert type(rooms[cid]['unread_count']) is int
        assert rooms[cid]['unread_count'] == 0
        assert rooms[cid]['last_read_at'] is None
    assert rooms[own_only]['last_message'] == 'Only my message'
    for cid in (empty, recalled_only):
        assert rooms[cid]['last_message'] is None
        assert rooms[cid]['last_message_at'] is None


def test_no_current_memberships_returns_empty_array_even_with_existing_sender_history(db_app, db_connection):
    change(db_connection, 'DELETE FROM Participants WHERE user_id=1')
    assert one(db_connection, 'SELECT COUNT(*) AS count FROM Messages WHERE user_id=1').count > 0
    assert service_list(db_app) == []
    assert api_list(sign_in(db_app)) == []


def test_unread_total_is_not_capped_to_a_history_page_or_badge_display_limit(db_app, db_connection):
    cid = create_room(db_connection, 'group')
    with db_connection.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO Messages (conversation_id, user_id, sender_type, session_id, content, created_at)
               VALUES (%s, 3, 'user', 'user_3', %s, %s)""",
            [(cid, f'Unread page message {n}', BASE + timedelta(microseconds=n)) for n in range(105)],
        )
    db_connection.commit()
    viewer = sign_in(db_app)
    history = viewer.get(f'/api/chat/history?conversation_id={cid}')
    assert history.status_code == 200
    assert len(history.get_json()['messages']) == 50  # History is paginated, the badge is an exact total.
    assert listed_room(db_app, cid)['unread_count'] == 105
    payload = next(room for room in api_list(viewer) if room['id'] == cid)
    assert type(payload['unread_count']) is int
    assert payload['unread_count'] == 105


def test_server_sort_is_fixed_latest_live_activity_then_id_with_empty_rooms_last(db_app, db_connection):
    peer_room = create_room(db_connection)
    own_room = create_room(db_connection)
    empty = create_room(db_connection, 'group')
    recalled_only = create_room(db_connection, 'group')
    newest = create_room(db_connection, 'group')
    insert_message(db_connection, peer_room, 3, content='Unread at tied time')
    insert_message(db_connection, own_room, 1, content='Read at tied time')
    insert_message(db_connection, recalled_only, 3, BASE + timedelta(days=1), deleted=True)
    insert_message(db_connection, newest, 1, BASE + timedelta(minutes=1))
    ids = {peer_room, own_room, empty, recalled_only, newest}
    expected = [newest, own_room, peer_room, recalled_only, empty]
    assert [row['id'] for row in service_list(db_app) if row['id'] in ids] == expected
    payload = [row for row in api_list(sign_in(db_app)) if row['id'] in ids]
    assert [row['id'] for row in payload] == expected
    assert [row['unread_count'] for row in payload] == [0, 0, 1, 0, 0]
    assert payload[-1]['last_message_at'] is None
    assert payload[-2]['last_message_at'] is None
