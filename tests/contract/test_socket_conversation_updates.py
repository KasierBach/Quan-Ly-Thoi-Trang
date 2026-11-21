"""Participant-only numeric sidebar invalidations with real offline Socket.IO transport."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import ANY, Mock

import psycopg2
import pytest

from app import socketio
from app.services.base_service import BaseService
from app.services.conversation_service import ChatAccess, ChatIdentity, ConversationService
import app.sockets as socket_module
from tests.contract.test_chat_server import ChatHarness


@pytest.fixture(autouse=True)
def forbid_database(monkeypatch):
    def refused():
        pytest.fail('Conversation invalidation tests must not connect to a database')

    monkeypatch.setattr(BaseService, 'get_connection', staticmethod(refused))


@pytest.fixture
def chat(app, monkeypatch):
    harness = ChatHarness(app, monkeypatch)
    try:
        yield harness
    finally:
        harness.close()


def event_payloads(connection):
    received = {}
    for packet in connection.get_received():
        received.setdefault(packet['name'], []).append(packet['args'][0])
    return received


def published_message(cid=2):
    return {
        'success': True,
        'id': 77,
        'conversation_id': cid,
        'session_id': None,
        'user_id': 1,
        'content': 'Selected-room message content',
    }


def test_numeric_message_uses_one_authorized_room_emit_for_cross_worker_delivery(chat, monkeypatch):
    sender, selected = chat.connect(1), chat.connect(3)
    chat.join(sender, 2)
    chat.join(selected, 2)
    emitted = Mock(wraps=socketio.emit)
    monkeypatch.setattr(socketio, 'emit', emitted)

    response = sender.emit('send_message', {'conversation_id': 2, 'content': 'queued room'}, callback=True)

    assert response['success'] is True
    room_calls = [
        call
        for call in emitted.call_args_list
        if call.args[:2] == ('new_message', ANY) and call.kwargs.get('to') == ['conv_2_user_1_v1', 'conv_2_user_3_v1']
    ]
    assert len(room_calls) == 1
    assert room_calls[0].args[1]['id'] == response['id']
    assert room_calls[0].kwargs == {'to': ['conv_2_user_1_v1', 'conv_2_user_3_v1'], 'namespace': '/'}
    assert len(event_payloads(sender)['new_message']) == 1
    assert len(event_payloads(selected)['new_message']) == 1


def test_removed_or_revoked_remote_targets_are_not_in_queued_delivery_rooms(chat, monkeypatch):
    chat.connect(1)
    chat.connect(3)
    del chat.conversations[2]['members'][3]
    chat.states[1]['AuthVersion'] = 2
    emitted = Mock(wraps=socketio.emit)
    monkeypatch.setattr(socketio, 'emit', emitted)

    with chat.app.app_context():
        chat.handlers.publish_message(published_message())

    room_calls = [call for call in emitted.call_args_list if call.args and call.args[0] == 'new_message']
    assert len(room_calls) == 1
    assert room_calls[0].kwargs['to'] == ['conv_2_user_1_v2']
    assert 'conv_2_user_3_v1' not in room_calls[0].kwargs['to']


def test_numeric_message_invalidates_all_current_participant_tabs_not_unselected_content(chat):
    sender, selected, unselected, admin = chat.connect(1), chat.connect(3), chat.connect(3), chat.connect(2)
    chat.join(sender, 2)
    chat.join(selected, 2)
    response = sender.emit('send_message', {'conversation_id': 2, 'content': 'private'}, callback=True)
    assert response['success'] is True
    for connection in (sender, selected):
        events = event_payloads(connection)
        assert events['new_message'][0]['content'] == 'private'
        assert events['conversation_updated'] == [{'conversation_id': 2}]
    assert event_payloads(unselected) == {'conversation_updated': [{'conversation_id': 2}]}
    assert admin.get_received() == []


@pytest.mark.parametrize('mutation', ['recall_message', 'mark_read'])
def test_successful_numeric_mutations_invalidate_participants_and_preserve_room_scope(chat, mutation):
    actor = chat.connect(3)
    selected, unselected, admin = chat.connect(1), chat.connect(1), chat.connect(2)
    chat.join(actor, 2)
    chat.join(selected, 2)
    response = actor.emit(mutation, {'conversation_id': 2, 'message_id': 3}, callback=True)
    assert response['success'] is True
    expected = 'message_recalled' if mutation == 'recall_message' else 'messages_read'
    assert expected in event_payloads(selected)
    assert event_payloads(unselected) == {'conversation_updated': [{'conversation_id': 2}]}
    assert event_payloads(actor)['conversation_updated'] == [{'conversation_id': 2}]
    assert admin.get_received() == []


def test_support_admin_read_access_alone_cannot_receive_numeric_invalidation(chat):
    owner, admin = chat.connect(1), chat.connect(2)
    del chat.conversations[1]['members'][2]
    chat.join(admin, 1)
    response = owner.emit('send_message', {'conversation_id': 1, 'content': 'support'}, callback=True)
    assert response['success'] is True
    admin_events = event_payloads(admin)
    assert admin_events['new_message'][0]['content'] == 'support'
    assert 'conversation_updated' not in admin_events
    assert admin.is_connected()
    assert chat.handlers.joined[chat.sids[admin]] == {'conv_1', 'conv_1_user_2_v1'}
    assert 'conv_1' in chat.handlers.socketio.server.rooms(chat.sids[admin], namespace='/')
    assert event_payloads(owner) == {
        'conversation_updated': [{'conversation_id': 1}],
        'message_sent': [{'success': True, 'id': response['id']}],
    }


def test_guest_support_never_emits_numeric_conversation_invalidation(chat):
    browser, credentials = chat.guest()
    guest = chat.connect(browser=browser, auth={'auth_token': credentials['auth_token']})
    admin = chat.connect(2)
    response = guest.emit(
        'send_message', {'session_id': credentials['session_id'], 'content': 'guest question'}, callback=True
    )
    assert response['success'] is True
    for connection in (guest, admin):
        events = event_payloads(connection)
        assert events['new_message'][0]['session_id'] == credentials['session_id']
        assert 'conversation_updated' not in events


def test_expired_unselected_participant_tabs_receive_no_invalidation(chat):
    sender, expired, other_tab = chat.connect(1), chat.connect(3), chat.connect(3)
    chat.states[3]['AuthVersion'] = 2
    with chat.app.app_context():
        chat.handlers.publish_message(published_message())
    assert event_payloads(sender) == {'conversation_updated': [{'conversation_id': 2}]}
    assert not expired.is_connected()
    assert not other_tab.is_connected()
    assert chat.sids[expired] not in chat.handlers.clients
    assert chat.sids[other_tab] not in chat.handlers.clients


def test_removed_but_authenticated_unselected_participant_receives_nothing(chat):
    sender, removed = chat.connect(1), chat.connect(3)
    del chat.conversations[2]['members'][3]
    with chat.app.app_context():
        chat.handlers.publish_message(published_message())
    assert removed.get_received() == []
    assert removed.is_connected()
    assert chat.handlers.joined[chat.sids[removed]] == set()
    assert event_payloads(sender) == {'conversation_updated': [{'conversation_id': 2}]}


@pytest.mark.parametrize('boundary', ['identity', 'acl'])
def test_recipient_disconnect_during_authorization_is_not_emitted_or_resurrected(chat, monkeypatch, boundary):
    recipient = chat.connect(3)
    chat.join(recipient, 2)
    sid = chat.sids[recipient]
    emitted = Mock(wraps=socketio.emit)
    monkeypatch.setattr(socketio, 'emit', emitted)
    if boundary == 'identity':
        original = socket_module.refresh_identity

        def refresh(actor):
            result = original(actor)
            if recipient.is_connected():
                recipient.disconnect()
            return result

        monkeypatch.setattr(socket_module, 'refresh_identity', refresh)
    else:
        original = ConversationService.get_access

        def access(*args, **kwargs):
            result = original(*args, **kwargs)
            if recipient.is_connected():
                recipient.disconnect()
            return result

        monkeypatch.setattr(ConversationService, 'get_access', access)
    with chat.app.app_context():
        chat.handlers.publish_message(published_message())
    assert sid not in chat.handlers.clients
    assert sid not in chat.handlers.joined
    assert not any(call.kwargs.get('to') == sid for call in emitted.call_args_list)


def test_recipient_leave_while_content_acl_pending_prevents_late_content(chat, monkeypatch):
    recipient = chat.connect(3)
    chat.join(recipient, 2)
    started, resume = Event(), Event()
    original = ConversationService.get_access

    def access(*args, **kwargs):
        result = original(*args, **kwargs)
        if not started.is_set():
            started.set()
            assert resume.wait(5)
        return result

    monkeypatch.setattr(ConversationService, 'get_access', access)

    def publish():
        with chat.app.app_context():
            chat.handlers.publish_message(published_message())

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(publish)
        try:
            assert started.wait(5)
            assert recipient.emit('leave_conversation', {'conversation_id': 2}, callback=True)['success']
        finally:
            resume.set()
        future.result(timeout=5)
    assert event_payloads(recipient) == {'conversation_updated': [{'conversation_id': 2}]}
    assert chat.handlers.joined[chat.sids[recipient]] == set()


@pytest.mark.parametrize('selected', [False, True])
def test_recipient_acl_outage_fails_closed_without_canceling_persisted_mutation(chat, monkeypatch, selected):
    sender, recipient = chat.connect(1), chat.connect(3)
    if selected:
        chat.join(sender, 2)
        chat.join(recipient, 2)
    original = ConversationService.get_access

    def access(*args, **kwargs):
        if kwargs['actor'].user_id == 3:
            raise psycopg2.OperationalError('offline recipient ACL')
        return original(*args, **kwargs)

    monkeypatch.setattr(ConversationService, 'get_access', access)
    result = sender.emit('send_message', {'conversation_id': 2, 'content': 'committed'}, callback=True)
    assert result['success'] is True
    assert chat.messages[result['id']]['content'] == 'committed'
    assert recipient.get_received() == []
    assert recipient.is_connected()


def test_publication_target_outage_does_not_turn_committed_message_into_failure(chat, monkeypatch):
    sender, recipient = chat.connect(1), chat.connect(3)
    chat.join(sender, 2)
    chat.join(recipient, 2)
    monkeypatch.setattr(
        ConversationService,
        'get_publication_targets',
        Mock(side_effect=psycopg2.OperationalError('offline target query')),
    )

    result = sender.emit('send_message', {'conversation_id': 2, 'content': 'committed without publish'}, callback=True)

    assert result['success'] is True
    assert chat.messages[result['id']]['content'] == 'committed without publish'
    assert not event_payloads(recipient).get('new_message')
    assert event_payloads(sender)['message_sent'] == [{'success': True, 'id': result['id']}]


@pytest.mark.parametrize('transport', ['socket', 'http'])
def test_postcommit_transport_outage_preserves_persisted_success(chat, monkeypatch, transport):
    sender, recipient = chat.connect(1), chat.connect(3)
    chat.join(sender, 2)
    chat.join(recipient, 2)
    original = socketio.emit

    def emit(event, payload, **kwargs):
        if event == 'new_message':
            raise OSError('synthetic queue unavailable')
        return original(event, payload, **kwargs)

    monkeypatch.setattr(socketio, 'emit', emit)
    if transport == 'socket':
        result = sender.emit(
            'send_message', {'conversation_id': 2, 'content': 'Saved during queue outage'}, callback=True
        )
    else:
        response = chat.browser(1).post(
            '/api/chat/send', json={'conversation_id': 2, 'content': 'Saved during queue outage'}
        )
        assert response.status_code == 200
        result = response.get_json()

    assert result['success'] is True
    assert chat.messages[result['id']]['content'] == 'Saved during queue outage'
    assert not event_payloads(recipient).get('new_message')
    if transport == 'socket':
        assert event_payloads(sender)['message_sent'] == [{'success': True, 'id': result['id']}]


def test_postcommit_recipient_cleanup_failure_does_not_fail_sender_or_leak_content(chat, monkeypatch):
    sender, recipient = chat.connect(1), chat.connect(3)
    chat.join(sender, 2)
    chat.join(recipient, 2)
    recipient_sid = chat.sids[recipient]
    original_send = chat.send.side_effect
    original_leave = socketio.server.manager.leave_room

    def persist_then_revoke(*args, **kwargs):
        result = original_send(*args, **kwargs)
        chat.conversations[2]['members'].pop(3)
        return result

    def noop_recipient_leave(sid, namespace, room):
        if sid == recipient_sid:
            return None
        return original_leave(sid, namespace, room)

    chat.send.side_effect = persist_then_revoke
    monkeypatch.setattr(socketio.server.manager, 'leave_room', noop_recipient_leave)
    result = sender.emit('send_message', {'conversation_id': 2, 'content': 'Already committed'}, callback=True)

    assert result['success'] is True
    assert chat.messages[result['id']]['content'] == 'Already committed'
    assert not event_payloads(recipient).get('new_message')
    assert event_payloads(sender)['message_sent'] == [{'success': True, 'id': result['id']}]


@pytest.mark.parametrize('event', ['new_message', 'message_sent'])
def test_socket_publish_and_sent_notice_outages_preserve_committed_ack(chat, monkeypatch, event):
    sender, recipient = chat.connect(1), chat.connect(3)
    chat.join(sender, 2)
    chat.join(recipient, 2)
    original = socketio.emit

    def fail_notice(name, payload, **kwargs):
        if name == event:
            raise OSError('synthetic notice transport failure')
        return original(name, payload, **kwargs)

    monkeypatch.setattr(socketio, 'emit', fail_notice)
    result = sender.emit('send_message', {'conversation_id': 2, 'content': 'Committed ACK survives'}, callback=True)

    assert result['success'] is True
    assert chat.messages[result['id']]['content'] == 'Committed ACK survives'


def test_failed_publish_result_and_support_receipt_are_noops(chat):
    recipient = chat.connect(1)
    with chat.app.app_context():
        chat.handlers.publish_message({'success': False, 'conversation_id': 2, 'content': 'not persisted'})
        chat.handlers.publish_read_receipt(ChatAccess(ChatIdentity(None), session_id='guest'))
    assert recipient.get_received() == []
