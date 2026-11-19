import pytest

from app import socketio


pytestmark = pytest.mark.integration


def test_logout_revokes_existing_socket_sessions(db_app, db_client):
    response = db_client.post('/login', data={'email': 'customer@example.test', 'password': 'TestUser123!'})
    assert response.status_code == 302
    socket = socketio.test_client(db_app, flask_test_client=db_client)
    assert socket.is_connected()
    assert db_client.post('/logout').status_code == 302
    assert not socket.is_connected()
