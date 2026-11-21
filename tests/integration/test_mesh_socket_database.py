"""Mesh Socket.IO adapters with the real PostgreSQL authorization boundary."""

import pytest

from app import socketio


pytestmark = pytest.mark.integration
CALL_ID = 'mesh_database_01234567'


def browser(application, uid, role='customer'):
    client = application.test_client()
    with client.session_transaction() as state:
        state.update(user_id=uid, user_name=f'Mesh User {uid}', role=role, is_admin=role == 'admin', auth_version=1)
    return client


def test_real_database_mesh_start_and_two_joins_ack(db_app):
    clients = [
        socketio.test_client(db_app, flask_test_client=browser(db_app, 1)),
        socketio.test_client(db_app, flask_test_client=browser(db_app, 2, 'admin')),
        socketio.test_client(db_app, flask_test_client=browser(db_app, 3)),
    ]
    try:
        result = clients[0].emit(
            'group_call_start',
            {
                'call_id': CALL_ID,
                'conversation_id': 3,
                'request_id': 'request_database_012345',
                'invite_user_ids': [2, 3],
                'isVideo': True,
            },
            callback=True,
        )
        assert result['success'] is True
        invitations = []
        for client in clients[1:]:
            packets = [packet['args'][0] for packet in client.get_received() if packet['name'] == 'group_call_invited']
            assert len(packets) == 1
            invitations.append(packets[0])
        for client, invitation in zip(clients[1:], invitations, strict=True):
            joined = client.emit(
                'group_call_join',
                {
                    'call_id': CALL_ID,
                    'conversation_id': 3,
                    'invite_id': invitation['invite_id'],
                },
                callback=True,
            )
            assert joined['success'] is True
        handlers = db_app.extensions['chat_socket_handlers']
        room = handlers.mesh_calls.calls[CALL_ID]
        assert room.status == 'active'
        assert {member.user_id for member in room.members.values() if member.status == 'joined'} == {1, 2, 3}
        assert len(room.pairs) == 3
    finally:
        for client in clients:
            if client.is_connected():
                client.disconnect()
