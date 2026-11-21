"""HTTP commit-to-socket publication contracts; no SQL or network calls."""

from io import BytesIO
from unittest.mock import Mock

import psycopg2
import pytest

from app.services.attachment_service import AttachmentService
from app.services.base_service import BaseService
from app.services.chat_service import ChatService
from app.services.conversation_service import ChatAccessError, ConversationService
from tests.contract.test_chat_server import ChatHarness


@pytest.fixture(autouse=True)
def forbid_database(monkeypatch):
    def refused():
        pytest.fail('Chat publication route tests must not connect to a database')

    monkeypatch.setattr(BaseService, 'get_connection', staticmethod(refused))


@pytest.fixture
def chat(app, monkeypatch):
    harness = ChatHarness(app, monkeypatch)
    try:
        yield harness
    finally:
        harness.close()


def packets(connection):
    return {packet['name']: packet['args'][0] for packet in connection.get_received()}


@pytest.mark.parametrize('mutation', ['recall', 'read'])
def test_http_success_publishes_after_persistence_with_actual_scope(chat, monkeypatch, mutation):
    selected, unselected, outsider = chat.connect(1), chat.connect(1), chat.connect(2)
    chat.join(selected, 2)
    actor_browser = chat.browser(3)
    sequence = []
    if mutation == 'recall':
        original = ChatService.recall_message
        publication = chat.handlers.publish_recall

        def persist_recall(mid, **kwargs):
            result = original(mid, **kwargs)
            sequence.append('persisted')
            return result

        def publish_recall(mid, access):
            assert chat.messages[mid]['is_deleted'] is True
            assert access.conversation_id == 2
            assert access.actor.user_id == 3
            sequence.append('published')
            return publication(mid, access)

        monkeypatch.setattr(ChatService, 'recall_message', persist_recall)
        monkeypatch.setattr(chat.handlers, 'publish_recall', publish_recall)
        response = actor_browser.post('/api/chat/messages/3/recall', json={'conversation_id': 1, 'user_id': 2})
        expected_event = 'message_recalled'
    else:
        original = ConversationService.mark_as_read
        publication = chat.handlers.publish_read_receipt

        def persist(cid, uid, **kwargs):
            result = original(cid, uid, **kwargs)
            sequence.append('persisted')
            return result

        def publish(access):
            assert ('read', 2, 3) in chat.operations
            assert access.conversation_id == 2
            assert access.actor.user_id == 3
            sequence.append('published')
            return publication(access)

        monkeypatch.setattr(ConversationService, 'mark_as_read', persist)
        monkeypatch.setattr(chat.handlers, 'publish_read_receipt', publish)
        response = actor_browser.post('/api/conversations/2/read', json={'user_id': 2, 'conversation_id': 1})
        expected_event = 'messages_read'
    assert response.status_code == 200
    assert response.get_json() == {'status': 'success'}
    assert sequence == ['persisted', 'published']
    selected_events = packets(selected)
    assert selected_events[expected_event]['conversation_id'] == 2
    assert selected_events['conversation_updated'] == {'conversation_id': 2}
    assert packets(unselected) == {'conversation_updated': {'conversation_id': 2}}
    assert outsider.get_received() == []


@pytest.mark.parametrize('mutation', ['recall', 'read'])
@pytest.mark.parametrize('failure', [False, psycopg2.OperationalError('offline persistence')])
def test_http_persistence_failure_returns_503_without_any_publication(chat, monkeypatch, mutation, failure):
    selected, unselected = chat.connect(1), chat.connect(1)
    chat.join(selected, 2)
    operation = Mock(return_value=False) if failure is False else Mock(side_effect=failure)
    if mutation == 'recall':
        monkeypatch.setattr(ChatService, 'recall_message', operation)
        response = chat.browser(3).post('/api/chat/messages/3/recall')
    else:
        monkeypatch.setattr(ConversationService, 'mark_as_read', operation)
        response = chat.browser(3).post('/api/conversations/2/read')
    assert response.status_code == 503
    assert selected.get_received() == unselected.get_received() == []
    assert chat.messages[3]['is_deleted'] is False


@pytest.mark.parametrize('mutation', ['recall', 'read'])
def test_http_permission_denial_does_not_call_persistence_or_publish(chat, monkeypatch, mutation):
    recipient = chat.connect(1)
    chat.join(recipient, 2)
    operation = Mock(side_effect=ChatAccessError())
    if mutation == 'recall':
        monkeypatch.setattr(ChatService, 'recall_message', operation)
        response = chat.browser(2).post('/api/chat/messages/3/recall')
        operation.assert_not_called()
    else:
        monkeypatch.setattr(ConversationService, 'mark_as_read', operation)
        response = chat.browser(2).post('/api/conversations/2/read')
        operation.assert_not_called()
    assert response.status_code == 403
    assert recipient.get_received() == []


@pytest.mark.parametrize('mutation', ['recall', 'read'])
def test_http_mutations_succeed_when_no_socket_gateway_is_installed(chat, monkeypatch, mutation):
    monkeypatch.delitem(chat.app.extensions, 'chat_socket_handlers')
    browser = chat.browser(3)
    path = '/api/chat/messages/3/recall' if mutation == 'recall' else '/api/conversations/2/read'
    assert browser.post(path).status_code == 200


def test_http_guest_read_is_noop_without_receipt_or_numeric_invalidation(chat):
    browser, credentials = chat.guest()
    admin = chat.connect(2)
    response = browser.post(
        f'/api/conversations/{credentials["session_id"]}/read', headers={'X-Chat-Token': credentials['auth_token']}
    )
    assert response.status_code == 200
    assert chat.operations == []
    assert admin.get_received() == []


@pytest.mark.parametrize('transport', ['send', 'admin_send', 'upload'])
def test_all_http_message_publishers_emit_invalidation_once_after_service_success(chat, monkeypatch, transport):
    selected, unselected = chat.connect(1), chat.connect(1)
    chat.join(selected, 1)
    browser = chat.browser(2 if transport == 'admin_send' else 1)
    if transport == 'upload':
        attachment = {
            'file_name': 'proof.txt',
            'file_type': 'file',
            'storage_name': 'offline-test.txt',
            'mime_type': 'text/plain',
        }
        monkeypatch.setattr(AttachmentService, 'prepare_upload', Mock(return_value=attachment))
        response = browser.post(
            '/api/chat/upload', data={'conversation_id': '1', 'file': (BytesIO(b'proof'), 'proof.txt')}
        )
    else:
        path = '/api/chat/admin/send' if transport == 'admin_send' else '/api/chat/send'
        response = browser.post(path, json={'conversation_id': 1, 'content': 'persisted'})
    assert response.status_code == 200
    for connection in (selected, unselected):
        received = connection.get_received()
        invalidations = [packet['args'][0] for packet in received if packet['name'] == 'conversation_updated']
        assert invalidations == [{'conversation_id': 1}]
        messages = [packet['args'][0] for packet in received if packet['name'] == 'new_message']
        assert len(messages) == (1 if connection is selected else 0)


@pytest.mark.parametrize('transport', ['send', 'admin_send', 'upload'])
def test_failed_http_message_publishers_emit_nothing(chat, monkeypatch, transport):
    recipient = chat.connect(1)
    chat.join(recipient, 1)
    chat.send.return_value = {'success': False, 'message': 'not persisted'}
    chat.send.side_effect = None
    browser = chat.browser(2 if transport == 'admin_send' else 1)
    if transport == 'upload':
        attachment = {'file_name': 'proof.txt', 'file_type': 'file', 'storage_name': 'offline-test.txt'}
        cleanup = Mock()
        monkeypatch.setattr(AttachmentService, 'prepare_upload', Mock(return_value=attachment))
        monkeypatch.setattr(AttachmentService, 'cleanup_files', cleanup)
        response = browser.post(
            '/api/chat/upload', data={'conversation_id': '1', 'file': (BytesIO(b'proof'), 'proof.txt')}
        )
        cleanup.assert_called_once_with(['offline-test.txt'])
    else:
        path = '/api/chat/admin/send' if transport == 'admin_send' else '/api/chat/send'
        response = browser.post(path, json={'conversation_id': 1, 'content': 'failed'})
    assert response.status_code == 503
    assert recipient.get_received() == []
