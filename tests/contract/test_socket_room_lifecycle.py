"""Offline, deterministic Socket.IO lifecycle and in-flight event races."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import psycopg2
import pytest

from app import socketio
from app.services.base_service import BaseService
from app.services.chat_service import ChatService
from app.services.conversation_service import ChatAccessError, ConversationService
import app.sockets as socket_module
from app.sockets import socket_sid
from tests.contract.test_chat_server import ANSWER, CALL_ID, OFFER, ChatHarness


@pytest.fixture(autouse=True)
def forbid_database(monkeypatch):
    def refused():
        pytest.fail('Socket lifecycle tests must not connect to a database')

    monkeypatch.setattr(BaseService, 'get_connection', staticmethod(refused))


@pytest.fixture
def chat(app, monkeypatch):
    harness = ChatHarness(app, monkeypatch)
    try:
        yield harness
    finally:
        harness.close()


def pause_identity(monkeypatch, uid):
    """Block exactly one refresh; the controlling thread can still refresh/leave."""
    started, resume = Event(), Event()
    original = socket_module.refresh_identity

    def refresh(actor):
        refreshed = original(actor)
        if actor.user_id == uid and not started.is_set():
            started.set()
            assert resume.wait(5), 'The test did not release identity refresh'
        return refreshed

    monkeypatch.setattr(socket_module, 'refresh_identity', refresh)
    return started, resume


def in_app(app, operation):
    with app.app_context():
        return operation()


def test_leave_between_content_and_delivery_join_rejects_stale_subscription(chat, monkeypatch):
    connection = chat.connect(3)
    sender = chat.connect(1)
    chat.join(sender, 2)
    sid = chat.sids[connection]
    original = chat.handlers._enter_delivery_room
    left = False

    def leave_then_enter(access, **kwargs):
        nonlocal left
        if not left:
            left = True
            assert connection.emit('leave_conversation', {'conversation_id': 2}, callback=True)['success']
        return original(access, **kwargs)

    monkeypatch.setattr(chat.handlers, '_enter_delivery_room', leave_then_enter)
    response = connection.emit('join_conversation', {'conversation_id': 2}, callback=True)

    assert response['success'] is False and response['status'] == 409
    assert chat.handlers.joined[sid] == set()
    assert socketio.server.rooms(sid, namespace='/') == [sid]
    assert sender.emit('send_message', {'conversation_id': 2, 'content': 'Not subscribed'}, callback=True)['success']
    assert not any(packet['name'] == 'new_message' for packet in connection.get_received())


def test_superseded_join_failure_cannot_rollback_newer_delivery_subscription(chat, monkeypatch):
    connection = chat.connect(3)
    sid = chat.sids[connection]
    original = chat.handlers._enter_delivery_room
    replaced = False

    def newer_join_then_fail(access, **kwargs):
        nonlocal replaced
        if not replaced:
            replaced = True
            assert connection.emit('join_conversation', {'conversation_id': 2}, callback=True)['success']
            raise ChatAccessError('Yêu cầu vào phòng đã được thay thế', 409)
        return original(access, **kwargs)

    monkeypatch.setattr(chat.handlers, '_enter_delivery_room', newer_join_then_fail)
    response = connection.emit('join_conversation', {'conversation_id': 2}, callback=True)

    assert response['success'] is False and response['status'] == 409
    assert chat.handlers.joined[sid] == {'conv_2', 'conv_2_user_3_v1'}
    assert {'conv_2', 'conv_2_user_3_v1'} <= set(socketio.server.rooms(sid, namespace='/'))


def test_delivery_room_failure_rolls_back_content_room_without_success_ack(chat, monkeypatch):
    connection = chat.connect(1)
    sid = chat.sids[connection]
    manager = chat.handlers.socketio.server.manager
    original = manager.enter_room

    def fail_delivery(joining_sid, namespace, room, **kwargs):
        if room == 'conv_2_user_1_v1':
            raise ValueError('delivery room failure')
        return original(joining_sid, namespace, room, **kwargs)

    monkeypatch.setattr(manager, 'enter_room', fail_delivery)
    with pytest.raises(ValueError, match='delivery room failure'):
        connection.emit('join_conversation', {'conversation_id': 2}, callback=True)
    assert chat.handlers.joined[sid] == set()
    assert manager.get_rooms(sid, '/') == [sid]


@pytest.mark.parametrize(
    'failure',
    [
        ValueError('sid is not connected to requested namespace'),
        KeyError(None),
    ],
)
def test_missing_connection_leave_errors_cleanup_without_false_success(chat, monkeypatch, failure):
    connection = chat.connect(1)
    chat.join(connection, 2)
    sid = chat.sids[connection]
    monkeypatch.setattr(chat.handlers.socketio.server.manager, 'leave_room', Mock(side_effect=failure))
    monkeypatch.setattr(chat.handlers, '_connected', lambda *_args, **_kwargs: False)

    response = connection.emit('leave_conversation', {'conversation_id': 2}, callback=True)

    assert response['success'] is False and response['status'] == 401
    assert sid not in chat.handlers.clients
    assert sid not in chat.handlers.joined


def test_leave_manager_noop_is_503_not_success(chat, monkeypatch):
    connection = chat.connect(1)
    chat.join(connection, 2)
    monkeypatch.setattr(chat.handlers.socketio.server.manager, 'leave_room', Mock(return_value=None))

    response = connection.emit('leave_conversation', {'conversation_id': 2}, callback=True)

    assert response['success'] is False and response['status'] == 503
    assert connection.is_connected()


@pytest.mark.parametrize('keep_namespace', [False, True])
def test_disconnect_inside_manager_join_has_no_success_ack_or_resurrected_sid(chat, monkeypatch, keep_namespace):
    connection = chat.connect(1)
    sid = chat.sids[connection]
    if keep_namespace:
        chat.connect(3)
    manager = chat.handlers.socketio.server.manager
    original = manager.enter_room

    def disconnect_then_enter(joining_sid, namespace, room, **kwargs):
        connection.disconnect()
        return original(joining_sid, namespace, room, **kwargs)

    monkeypatch.setattr(manager, 'enter_room', disconnect_then_enter)
    response = connection.emit('join_conversation', {'conversation_id': 2}, callback=True)
    assert response['success'] is False
    assert response['status'] == 401
    assert sid not in chat.handlers.clients
    assert sid not in chat.handlers.joined
    assert manager.get_rooms(sid, '/') == []


@pytest.mark.parametrize('disconnect_first', [False, True])
def test_unrelated_join_value_error_is_not_swallowed(chat, monkeypatch, disconnect_first):
    connection = chat.connect(1)
    sid = chat.sids[connection]

    def invalid_room(*args, **kwargs):
        if disconnect_first:
            connection.disconnect()
        raise ValueError('unrelated room validation failure')

    monkeypatch.setattr(chat.handlers.socketio.server.manager, 'enter_room', invalid_room)
    with pytest.raises(ValueError, match='unrelated room validation failure'):
        connection.emit('join_conversation', {'conversation_id': 2}, callback=True)
    assert 'conv_2' not in chat.handlers.joined.get(sid, set())


def test_live_namespace_value_error_is_not_misclassified_as_disconnect(chat, monkeypatch):
    connection = chat.connect(1)
    monkeypatch.setattr(
        chat.handlers.socketio.server.manager,
        'enter_room',
        Mock(side_effect=ValueError('sid is not connected to requested namespace')),
    )
    with pytest.raises(ValueError, match='sid is not connected'):
        connection.emit('join_conversation', {'conversation_id': 2}, callback=True)
    assert connection.is_connected()
    assert chat.handlers.joined[chat.sids[connection]] == set()


def test_manager_noop_join_cannot_produce_success_ack(chat, monkeypatch):
    connection = chat.connect(1)
    monkeypatch.setattr(chat.handlers.socketio.server.manager, 'enter_room', Mock(return_value=None))
    response = connection.emit('join_conversation', {'conversation_id': 2}, callback=True)
    assert response['success'] is False
    assert response['status'] == 503
    assert chat.handlers.joined[chat.sids[connection]] == set()


def test_unrelated_leave_error_is_not_swallowed_or_written_as_success(chat, monkeypatch):
    connection = chat.connect(1)
    chat.join(connection, 2)
    original = chat.handlers.socketio.server.manager.leave_room
    monkeypatch.setattr(
        chat.handlers.socketio.server.manager, 'leave_room', Mock(side_effect=ValueError('unrelated leave failure'))
    )
    try:
        with pytest.raises(ValueError, match='unrelated leave failure'):
            connection.emit('leave_conversation', {'conversation_id': 2}, callback=True)
        assert chat.handlers.joined[chat.sids[connection]] == {'conv_2', 'conv_2_user_1_v1'}
    finally:
        monkeypatch.setattr(chat.handlers.socketio.server.manager, 'leave_room', original)


def test_disconnect_after_join_relies_on_manager_auto_cleanup_without_late_leave(chat, monkeypatch):
    connection = chat.connect(1)
    chat.join(connection, 2)
    sid = chat.sids[connection]
    leave = Mock(wraps=chat.handlers.socketio.server.manager.leave_room)
    monkeypatch.setattr(chat.handlers.socketio.server.manager, 'leave_room', leave)

    connection.disconnect()

    assert sid not in chat.handlers.clients
    assert sid not in chat.handlers.joined
    assert sid not in chat.handlers.generations
    leave.assert_not_called()


@pytest.mark.parametrize('teardown', ['disconnect', 'close'])
def test_identity_refresh_cannot_restore_a_torn_down_connection(chat, monkeypatch, teardown):
    connection = chat.connect(1)
    sid = chat.sids[connection]
    started, resume = pause_identity(monkeypatch, 1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(in_app, chat.app, lambda: chat.handlers._actor(sid))
        try:
            assert started.wait(5)
            connection.disconnect() if teardown == 'disconnect' else chat.handlers.close()
        finally:
            resume.set()
        with pytest.raises(ChatAccessError) as error:
            future.result(timeout=5)
    assert error.value.status == 401
    assert sid not in chat.handlers.clients
    assert sid not in chat.handlers.joined


def test_disconnect_during_conversation_acl_refresh_rejects_join(chat, monkeypatch):
    connection = chat.connect(1)
    sid = chat.sids[connection]
    original = ConversationService.get_access

    def access(*args, **kwargs):
        result = original(*args, **kwargs)
        connection.disconnect()
        return result

    monkeypatch.setattr(ConversationService, 'get_access', access)
    response = connection.emit('join_conversation', {'conversation_id': 2}, callback=True)
    assert response['success'] is False
    assert response['status'] == 401
    assert sid not in chat.handlers.clients
    assert sid not in chat.handlers.joined


def test_leave_wins_over_a_join_waiting_for_identity_refresh(chat, monkeypatch):
    connection = chat.connect(1)
    started, resume = pause_identity(monkeypatch, 1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(connection.emit, 'join_conversation', {'conversation_id': 2}, callback=True)
        try:
            assert started.wait(5)
            response = connection.emit('leave_conversation', {'conversation_id': 2}, callback=True)
            assert response['success'] is True
        finally:
            resume.set()
        response = future.result(timeout=5)
    assert response['success'] is False
    assert response['status'] == 409
    assert chat.handlers.joined[chat.sids[connection]] == set()
    rooms = chat.handlers.socketio.server.rooms(chat.sids[connection], namespace='/')
    assert 'conv_2' not in rooms
    assert 'conv_2_user_1_v1' not in rooms


def test_newer_join_wins_over_leave_waiting_for_identity_refresh(chat, monkeypatch):
    connection = chat.connect(3)
    chat.join(connection, 2)
    sid = chat.sids[connection]
    started, resume = pause_identity(monkeypatch, 3)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(connection.emit, 'leave_conversation', {'conversation_id': 2}, callback=True)
        try:
            assert started.wait(5)
            assert connection.emit('join_conversation', {'conversation_id': 2}, callback=True)['success']
        finally:
            resume.set()
        response = future.result(timeout=5)

    assert response['success'] is False and response['status'] == 409
    assert chat.handlers.joined[sid] == {'conv_2', 'conv_2_user_3_v1'}
    assert {'conv_2', 'conv_2_user_3_v1'} <= set(socketio.server.rooms(sid, namespace='/'))


def test_disconnect_during_connect_authentication_does_not_register_dead_sid(chat, monkeypatch):
    original = socket_module.get_identity

    def identity(*args, **kwargs):
        actor = original(*args, **kwargs)
        chat.handlers.socketio.server.manager.disconnect(socket_sid(), '/')
        return actor

    monkeypatch.setattr(socket_module, 'get_identity', identity)
    connection = chat.connect(1)
    assert not connection.is_connected()
    assert chat.handlers.clients == chat.handlers.joined == {}


@pytest.mark.parametrize('error', [ChatAccessError('expired', 401), psycopg2.OperationalError('offline')])
def test_guest_connect_acl_failure_cleans_registered_state(chat, monkeypatch, error):
    browser, credentials = chat.guest()
    monkeypatch.setattr(ConversationService, 'get_access', Mock(side_effect=error))
    connection = chat.connect(browser=browser, auth={'auth_token': credentials['auth_token']})
    assert not connection.is_connected()
    assert chat.handlers.clients == chat.handlers.joined == {}


def test_connect_unexpected_failure_propagates_but_cleans_gateway_state(chat, monkeypatch):
    monkeypatch.setattr(ChatService, 'update_last_seen', Mock(side_effect=ValueError('unrelated presence failure')))
    with pytest.raises(ValueError, match='unrelated presence failure'):
        chat.connect(1)
    assert chat.handlers.clients == chat.handlers.joined == {}


def test_close_during_connect_presence_update_rejects_connection(chat, monkeypatch):
    monkeypatch.setattr(ChatService, 'update_last_seen', lambda *args, **kwargs: chat.handlers.close())
    connection = chat.connect(1)
    assert not connection.is_connected()
    assert chat.handlers.clients == chat.handlers.joined == {}


def test_close_removes_selected_rooms_and_cancels_timers_without_late_signals(chat):
    caller, peer = chat.connect(1), chat.connect(3)
    chat.join(caller, 2)
    chat.join(peer, 2)
    assert caller.emit('call_user', {'conversation_id': 2, 'call_id': CALL_ID, 'offer': OFFER}, callback=True)[
        'success'
    ]
    peer.get_received()
    chat.handlers.close()
    assert chat.handlers.clients == chat.handlers.joined == chat.handlers.calls == {}
    for connection in (caller, peer):
        assert 'conv_2' not in chat.handlers.socketio.server.rooms(chat.sids[connection], namespace='/')
        assert connection.get_received() == []
    assert chat.timers[0].cancelled
    chat.timers[0].fire()
    assert caller.get_received() == peer.get_received() == []


def test_call_peer_disconnect_inside_refresh_cannot_relay_a_late_signal(chat, monkeypatch):
    caller, peer = chat.connect(1), chat.connect(3)
    assert caller.emit('call_user', {'conversation_id': 2, 'call_id': CALL_ID, 'offer': OFFER}, callback=True)[
        'success'
    ]
    peer.get_received()
    assert peer.emit('answer_call', {'conversation_id': 2, 'call_id': CALL_ID, 'answer': ANSWER}, callback=True)[
        'success'
    ]
    caller.get_received()
    original = socket_module.refresh_identity
    emitted = Mock(wraps=socketio.emit)
    monkeypatch.setattr(socketio, 'emit', emitted)

    def refresh(actor):
        result = original(actor)
        if actor.user_id == 3 and peer.is_connected():
            peer.disconnect()
        return result

    monkeypatch.setattr(socket_module, 'refresh_identity', refresh)
    response = caller.emit(
        'media_status', {'conversation_id': 2, 'call_id': CALL_ID, 'type': 'mic', 'enabled': True}, callback=True
    )
    assert response['success'] is False
    assert response['status'] == 409
    assert chat.handlers.calls == {}
    assert chat.sids[peer] not in chat.handlers.clients
    assert not any(call.args[0] == 'media_status' for call in emitted.call_args_list)


def test_call_peer_disappearing_during_caller_refresh_does_not_revoke_valid_caller(chat, monkeypatch):
    caller, peer = chat.connect(1), chat.connect(3)
    assert caller.emit('call_user', {'conversation_id': 2, 'call_id': CALL_ID, 'offer': OFFER}, callback=True)[
        'success'
    ]
    peer.get_received()
    assert peer.emit('answer_call', {'conversation_id': 2, 'call_id': CALL_ID, 'answer': ANSWER}, callback=True)[
        'success'
    ]
    caller.get_received()
    original = socket_module.refresh_identity
    refreshes = 0

    def refresh(actor):
        nonlocal refreshes
        result = original(actor)
        if actor.user_id == 1:
            refreshes += 1
            # The first refresh is guarded_event; the second is the caller's
            # ACL check inside _lookup_call while the call still exists.
            if refreshes == 2:
                peer.disconnect()
        return result

    monkeypatch.setattr(socket_module, 'refresh_identity', refresh)
    response = caller.emit(
        'media_status', {'conversation_id': 2, 'call_id': CALL_ID, 'type': 'mic', 'enabled': True}, callback=True
    )
    assert response['success'] is False
    assert response['status'] == 409
    assert caller.is_connected()
    assert chat.sids[caller] in chat.handlers.clients
    assert chat.sids[peer] not in chat.handlers.clients
    assert chat.handlers.calls == {}
