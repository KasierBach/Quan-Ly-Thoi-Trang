"""Small offline IDOR sweep: real route/validation/ACL code, mocked persistence.

SQL query scoping is asserted, not claimed as a PostgreSQL authorization proof.
Profile/feedback routes bind identity from the signed session, not supplied IDs.
"""

from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services.base_service import BaseService
from tests.contract.test_chat_server import ChatHarness


@pytest.fixture(autouse=True)
def forbid_database(monkeypatch):
    monkeypatch.setattr(BaseService, 'get_connection', Mock(side_effect=AssertionError('IDOR test attempted DB I/O')))


@pytest.fixture
def chat(app, monkeypatch):
    harness = ChatHarness(app, monkeypatch)
    try:
        yield harness
    finally:
        harness.close()


@pytest.mark.parametrize(
    'method,path,payload',
    [
        ('GET', '/order/99', None),
        ('POST', '/cancel_order/99', {}),
        ('POST', '/checkout', {}),
        ('POST', '/update_profile', {'full_name': 'Changed', 'user_id': 3}),
        ('POST', '/add_review', {'product_id': 1, 'rating': 5, 'comment': 'Changed', 'user_id': 3}),
        ('POST', '/add_comment', {'product_id': 1, 'content': 'Changed', 'user_id': 3}),
    ],
)
def test_anonymous_owner_endpoints_block_before_any_service(client, method, path, payload):
    response = client.open(path, method=method, json=payload, headers={'Accept': 'application/json'})
    assert response.status_code == 401
    assert response.json['success'] is False
    with client.session_transaction() as state:
        assert 'user_id' not in state and not state.get('cart')


@pytest.mark.parametrize(
    'method,path', [('GET', '/order/99'), ('GET', '/order_confirmation/99'), ('POST', '/cancel_order/99')]
)
def test_foreign_order_query_binds_session_owner_and_empty_scope_never_mutates(auth_client, fake_db, method, path):
    fake_db.cursor.fetchone.return_value = None  # No order in the authenticated owner's scope.
    response = auth_client.open(path + '?customer_id=3', method=method, headers={'Accept': 'application/json'})
    assert response.status_code == 404
    fake_db.cursor.execute.assert_called_once()
    sql, params = fake_db.cursor.execute.call_args.args
    assert 'CustomerID = %s' in sql and 'OrderID = %s' in sql
    assert params == (99, 1)
    fake_db.connection.commit.assert_not_called()
    fake_db.cursor.fetchall.assert_not_called()


@pytest.mark.parametrize('path', ['/update_cart', '/remove_from_cart'])
def test_other_browser_cart_item_cannot_be_mutated(auth_client, app, path):
    other = app.test_client()
    own, foreign = [{'variant_id': 1, 'quantity': 2}], [{'variant_id': 3, 'quantity': 4}]
    for browser, cart in ((auth_client, own), (other, foreign)):
        with browser.session_transaction() as state:
            state['cart'] = cart
    response = auth_client.post(path, json={'variant_id': 3, 'quantity': 1, 'customer_id': 3})
    assert response.status_code == 404 and response.json['success'] is False
    for browser, expected in ((auth_client, own), (other, foreign)):
        with browser.session_transaction() as state:
            assert state['cart'] == expected


def test_missing_session_profile_cannot_read_supplied_foreign_customer(auth_client, fake_db):
    fake_db.cursor.fetchone.return_value = None
    response = auth_client.get('/my_account?user_id=3&customer_id=3')
    assert response.status_code == 302 and response.location == '/login'
    fake_db.cursor.execute.assert_called_once()
    sql, params = fake_db.cursor.execute.call_args.args
    assert 'FROM Customers WHERE CustomerID = %s' in sql and params == (1,)
    fake_db.connection.commit.assert_not_called()
    with auth_client.session_transaction() as state:
        assert 'user_id' not in state


def test_profile_invalid_spoofed_identity_never_mutates(auth_client, fake_db):
    response = auth_client.post(
        '/update_profile',
        data={'user_id': 3, 'customer_id': 3, 'full_name': 'Changed', 'phone': 'not-a-phone', 'gender': 'other'},
    )
    assert response.status_code == 302 and response.location.endswith('#profile')
    fake_db.connection.cursor.assert_not_called()
    fake_db.connection.commit.assert_not_called()
    with auth_client.session_transaction() as state:
        assert state['user_id'] == 1 and state['user_name'] == 'Test User'


@pytest.mark.parametrize(
    'path,body',
    [
        ('/add_review', {'product_id': 1, 'rating': 5, 'comment': 'Changed'}),
        ('/add_comment', {'product_id': 1, 'content': 'Changed'}),
    ],
)
def test_feedback_cannot_borrow_foreign_customer_when_session_customer_missing(auth_client, fake_db, path, body):
    fake_db.cursor.fetchone.return_value = None
    response = auth_client.post(path, json={**body, 'user_id': 3, 'customer_id': 3})
    assert response.status_code == 404 and response.json['success'] is False
    fake_db.cursor.execute.assert_called_once_with(
        'SELECT FullName FROM Customers WHERE CustomerID = %s FOR UPDATE', (1,)
    )
    fake_db.connection.commit.assert_not_called()


@pytest.mark.parametrize(
    'method,path,payload',
    [
        ('GET', '/api/conversations/2', None),
        ('GET', '/api/chat/history?conversation_id=2', None),
        ('POST', '/api/chat/send', {'conversation_id': 2, 'user_id': 1, 'room': 'conv_2', 'content': 'Changed'}),
        ('PATCH', '/api/conversations/2/settings', {'name': 'Changed'}),
        ('POST', '/api/conversations/2/read', {}),
    ],
)
def test_site_admin_is_not_private_owner_even_with_spoofed_ids(chat, method, path, payload):
    before = deepcopy((chat.conversations, chat.messages, chat.operations))
    response = chat.browser(2).open(path, method=method, json=payload)
    assert response.status_code == 403 and response.json['success'] is False
    assert (chat.conversations, chat.messages, chat.operations) == before


def test_nonmember_attachment_download_and_upload_block_before_filesystem(chat, monkeypatch):
    owner = chat.browser(1)
    uploaded = owner.post('/api/chat/upload', data={'conversation_id': '2', 'file': (BytesIO(b'private'), 'test.txt')})
    assert uploaded.status_code == 200
    path = Path(chat.app.config['UPLOAD_ROOT']) / 'chat'
    before = deepcopy((chat.messages, chat.attachments, chat.operations))
    files = {item.name: item.read_bytes() for item in path.iterdir()}
    send_file = Mock(side_effect=AssertionError('Nonmember reached file download'))
    monkeypatch.setattr('app.routes.chat.send_file', send_file)
    outsider = chat.browser(2)
    assert outsider.get(uploaded.json['file_url']).status_code == 403
    assert (
        outsider.post(
            '/api/chat/upload', data={'conversation_id': '2', 'file': (BytesIO(b'attack'), 'new.txt')}
        ).status_code
        == 403
    )
    send_file.assert_not_called()
    assert (chat.messages, chat.attachments, chat.operations) == before
    assert {item.name: item.read_bytes() for item in path.iterdir()} == files


def test_socket_room_and_identity_spoof_cannot_join_private_room(chat):
    outsider = chat.connect(2)
    before = deepcopy((chat.messages, chat.operations))
    result = outsider.emit('join_conversation', {'conversation_id': 2, 'room': 'conv_2', 'user_id': 1}, callback=True)
    assert result['success'] is False and result['status'] == 403
    assert 'conv_2' not in chat.handlers.joined[chat.sids[outsider]]
    assert (chat.messages, chat.operations) == before
