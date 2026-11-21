"""Offline list/ACL/error contracts; PostgreSQL tests prove the unread SQL.

No test in this module may open a database connection. Mock rows verify JSON
serialization and control flow, not whether a message is actually unread.
"""

from datetime import datetime, timezone
from unittest.mock import Mock

import psycopg2
import pytest

from app.database import CaseInsensitiveRecord
from app.services.auth_service import AuthService
from app.services.base_service import BaseService
from app.services.conversation_service import ChatAccessError, ChatIdentity, ConversationService
from app.validation import ValidationError


@pytest.fixture(autouse=True)
def no_unplanned_database(monkeypatch):
    def refused():
        pytest.fail('Unread unit test attempted an unplanned database connection')

    monkeypatch.setattr(BaseService, 'get_connection', staticmethod(refused))


def actor(uid=1, *, admin=False):
    return ChatIdentity(uid, is_admin=admin, name='Test Actor', auth_version=1)


def conversation_row(**values):
    return CaseInsensitiveRecord(
        {
            'id': 2,
            'type': 'private',
            'name': None,
            'partner_display_name': 'Test Peer',
            'role': 'member',
            'my_nickname': None,
            'created_at': datetime(2026, 4, 5, 10),
            'updated_at': datetime(2026, 4, 5, 11),
            'last_message': 'Visible message',
            'last_message_at': datetime(2026, 4, 5, 11),
            'last_read_at': None,
            'unread_count': 1,
            **values,
        }
    )


@pytest.mark.parametrize(
    'identity,requested_uid,status',
    [(actor(1), 3, 403), (actor(2, admin=True), 1, 403), (actor(None), 1, 401)],
    ids=['different-user', 'site-admin-cannot-impersonate', 'guest'],
)
def test_list_cannot_impersonate_or_list_as_guest_before_database(app, identity, requested_uid, status):
    with app.app_context(), pytest.raises(ChatAccessError) as denied:
        ConversationService.get_user_conversations(requested_uid, actor=identity)
    assert denied.value.status == status


@pytest.mark.parametrize('uid', [None, True, False, 0, -1, '1.5', '1 OR 1=1', [], {}, 2147483648, '9' * 21])
def test_list_user_id_is_a_bounded_positive_integer_before_database(app, uid):
    with app.app_context(), pytest.raises(ValidationError):
        ConversationService.get_user_conversations(uid, actor=actor())


@pytest.mark.parametrize(
    'state',
    [None, CaseInsensitiveRecord(CustomerID=1, FullName='Current User', AuthVersion=2, Role='customer')],
    ids=['account-removed', 'auth-version-expired'],
)
def test_passed_identity_is_revalidated_before_unread_metadata_query(app, monkeypatch, state):
    app.config['SESSION_REVALIDATION_ENABLED'] = True
    refresh = Mock(return_value=state)
    monkeypatch.setattr(AuthService, 'get_identity_state', refresh)
    with app.app_context(), pytest.raises(ChatAccessError) as denied:
        ConversationService.get_user_conversations(1, actor=actor())
    assert denied.value.status == 401
    refresh.assert_called_once_with(1)


@pytest.mark.parametrize('count', [0, 1, 7, 2147483648])
def test_unread_count_stays_integer_and_timestamps_serialize_without_mutating_rows(app, fake_db, count):
    read_at = datetime(2026, 4, 5, 10, 30, 0, 123456, tzinfo=timezone.utc)
    row = conversation_row(unread_count=count, last_read_at=read_at)
    original = dict(row)
    fake_db.cursor.fetchall.return_value = [row]
    with app.app_context():
        result = ConversationService.get_user_conversations(1, actor=actor())
    assert len(result) == 1
    conv = result[0]
    assert type(conv['unread_count']) is int
    assert conv['unread_count'] == count
    for key in ('created_at', 'updated_at', 'last_message_at', 'last_read_at'):
        assert conv[key] == original[key].isoformat()
    assert conv['name'] == 'Test Peer'
    assert conv['my_nickname'] is None
    assert conv['role'] == 'member'
    assert conv['is_online'] is False
    assert row == original
    fake_db.cursor.execute.assert_called_once()
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()


@pytest.mark.parametrize(
    'name,partner,expected',
    [('Named room', 'Peer', 'Named room'), (None, 'Peer nickname', 'Peer nickname'), ('', None, 'Cuộc trò chuyện')],
)
def test_name_fallback_does_not_drop_unread_count(app, fake_db, name, partner, expected):
    fake_db.cursor.fetchall.return_value = [conversation_row(name=name, partner_display_name=partner, unread_count=2)]
    with app.app_context():
        result = ConversationService.get_user_conversations(1, actor=actor())
    assert result[0]['name'] == expected
    assert result[0]['unread_count'] == 2


@pytest.mark.parametrize('uid', [1, '0001'])
def test_list_uses_one_parameterized_member_scoped_query_and_only_fixed_sorting(app, fake_db, uid):
    # These are SQL-shape guards only. Real row-selection/order assertions live
    # in tests/integration/test_chat_unread_counts.py.
    fake_db.cursor.fetchall.return_value = [
        conversation_row(id=9, unread_count=0),
        conversation_row(id=3, unread_count=5),
    ]
    with app.app_context():
        result = ConversationService.get_user_conversations(uid, actor=actor())
    assert [row['id'] for row in result] == [9, 3]  # Preserve database order, not badge-count order.
    fake_db.cursor.execute.assert_called_once()
    query, params = fake_db.cursor.execute.call_args.args
    sql = ' '.join(query.split())
    assert params == (1, 1, 1)
    assert sql.count('%s') == 3
    assert 'FROM Conversations c JOIN Participants p ON c.id = p.conversation_id' in sql
    assert 'WHERE p.user_id = %s ORDER BY last_message_at DESC NULLS LAST, c.id DESC' in sql
    assert 'SELECT COUNT(*) FROM Messages m WHERE m.conversation_id = c.id AND NOT m.is_deleted' in sql
    assert 'm.user_id IS DISTINCT FROM %s' in sql
    assert '(p.last_read_at IS NULL OR m.created_at > p.last_read_at)' in sql
    assert 'joined_at' not in sql
    assert 'm.is_read' not in sql
    fake_db.conn.close.assert_called_once()


@pytest.mark.parametrize('stage', ['execute', 'fetchall'])
def test_database_failure_propagates_instead_of_fabricating_zero_counts_and_closes(app, fake_db, stage):
    failure = psycopg2.OperationalError('private unread database detail')
    getattr(fake_db.cursor, stage).side_effect = failure
    with app.app_context(), pytest.raises(psycopg2.OperationalError) as caught:
        ConversationService.get_user_conversations(1, actor=actor())
    assert caught.value is failure
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()


def test_successful_empty_list_closes_connection(app, fake_db):
    fake_db.cursor.fetchall.return_value = []
    with app.app_context():
        assert ConversationService.get_user_conversations(1, actor=actor()) == []
    fake_db.cursor.execute.assert_called_once()
    fake_db.conn.close.assert_called_once()


def test_api_conversations_json_has_integer_badges_iso_dates_and_nullable_empty_preview(auth_client, fake_db):
    live = conversation_row(unread_count=3, last_read_at=datetime(2026, 4, 5, 10, 30))
    empty = conversation_row(
        id=4,
        type='group',
        name='Empty group',
        partner_display_name=None,
        unread_count=0,
        last_message=None,
        last_message_at=None,
    )
    fake_db.cursor.fetchall.return_value = [live, empty]
    response = auth_client.get('/api/conversations')
    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {'conversations'}
    assert [row['id'] for row in payload['conversations']] == [2, 4]
    assert [row['unread_count'] for row in payload['conversations']] == [3, 0]
    assert all(type(row['unread_count']) is int for row in payload['conversations'])
    assert payload['conversations'][0]['last_read_at'] == live.last_read_at.isoformat()
    assert payload['conversations'][0]['last_message_at'] == live.last_message_at.isoformat()
    assert payload['conversations'][1]['last_message'] is None
    assert payload['conversations'][1]['last_message_at'] is None
    assert payload['conversations'][1]['last_read_at'] is None
    fake_db.conn.close.assert_called_once()


def test_api_empty_list_is_an_empty_array(auth_client, fake_db):
    fake_db.cursor.fetchall.return_value = []
    response = auth_client.get('/api/conversations')
    assert response.status_code == 200
    assert response.get_json() == {'conversations': []}
    fake_db.conn.close.assert_called_once()


def test_api_request_cannot_select_another_user_or_inject_sorting(auth_client, fake_db):
    fake_db.cursor.fetchall.return_value = []
    malicious_sort = 'unread_count DESC; DROP TABLE Messages'
    response = auth_client.get('/api/conversations', query_string={'user_id': 3, 'sort': malicious_sort})
    assert response.status_code == 200
    query, params = fake_db.cursor.execute.call_args.args
    assert params == (1, 1, 1)
    assert malicious_sort not in query
    assert 'ORDER BY last_message_at DESC NULLS LAST, c.id DESC' in query


def test_api_requires_authenticated_identity_before_database(client):
    response = client.get('/api/conversations')
    assert response.status_code == 401
    assert response.get_json()['success'] is False
    assert 'conversations' not in response.get_json()


@pytest.mark.parametrize('stage', ['execute', 'fetchall'])
def test_api_database_failure_is_generic_503_not_an_empty_or_zero_unread_list(auth_client, fake_db, stage):
    getattr(fake_db.cursor, stage).side_effect = psycopg2.OperationalError('private unread database detail')
    response = auth_client.get('/api/conversations')
    assert response.status_code == 503
    payload = response.get_json()
    assert payload == {'success': False, 'error': 'Chat tạm thời không khả dụng'}
    assert 'private unread database detail' not in response.get_data(as_text=True)
    assert 'conversations' not in payload
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()


def test_api_connection_acquisition_failure_is_generic_503(auth_client, monkeypatch):
    connect = Mock(side_effect=psycopg2.OperationalError('private connection detail'))
    monkeypatch.setattr(BaseService, 'get_connection', connect)
    response = auth_client.get('/api/conversations')
    assert response.status_code == 503
    assert response.get_json() == {'success': False, 'error': 'Chat tạm thời không khả dụng'}
    connect.assert_called_once_with()


def test_admin_guest_entries_remain_separate_from_participant_unread_badges(admin_client, fake_db, monkeypatch):
    fake_db.cursor.fetchall.return_value = [conversation_row(id=1, type='support', unread_count=1)]
    guest_entries = Mock(
        return_value=[{'id': 'guest-ticket', 'session_id': 'guest-ticket', 'type': 'support', 'name': 'Guest ticket'}]
    )
    monkeypatch.setattr(ConversationService, 'get_guest_conversations', guest_entries)
    response = admin_client.get('/api/conversations')
    assert response.status_code == 200
    numeric, guest = response.get_json()['conversations']
    assert type(numeric['unread_count']) is int
    assert numeric['unread_count'] == 1
    assert guest['id'] == 'guest-ticket'
    assert 'unread_count' not in guest  # No participant cursor exists for guest sessions.
    assert guest_entries.call_args.kwargs['actor'].user_id == 2
    assert fake_db.cursor.execute.call_args.args[1] == (2, 2, 2)
