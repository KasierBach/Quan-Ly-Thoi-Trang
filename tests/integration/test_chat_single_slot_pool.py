"""Authorization must revalidate on an existing transaction, never borrow a second pool slot."""

import pytest

from app import create_app
from app.database import close_db_pool
from app.services.chat_service import ChatService
from app.services.conversation_service import ChatAccessError, ChatIdentity, ConversationService


pytestmark = pytest.mark.integration


@pytest.fixture
def one_slot_app(database_url, db_connection, tmp_path):
    application = create_app(
        {
            'APP_ENV': 'testing',
            'TESTING': True,
            'SECRET_KEY': 'synthetic-single-slot-authorization-key-2026',
            'DATABASE_URL': database_url,
            'SQLALCHEMY_DATABASE_URI': database_url.replace('postgresql://', 'postgresql+psycopg2://'),
            'DB_CONNECT_ENABLED': True,
            'DB_POOL_ENABLED': True,
            'DB_POOL_MIN': 1,
            'DB_POOL_MAX': 1,
            'DB_POOL_WAIT_TIMEOUT': 0.05,
            'SESSION_REVALIDATION_ENABLED': True,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'MAIL_SUPPRESS_SEND': True,
            'UPLOAD_ROOT': str(tmp_path / 'uploads'),
        }
    )
    try:
        yield application
    finally:
        application.extensions['chat_socket_handlers'].close()
        close_db_pool(application)


def test_authenticated_chat_reads_and_mutation_fit_one_pool_slot(one_slot_app):
    actor = ChatIdentity(1, auth_version=1)
    with one_slot_app.app_context():
        access = ConversationService.get_access(2, actor=actor)
        assert access.role == 'owner'
        assert {person['id'] for person in ConversationService.get_participants(2, actor=actor)} == {1, 3}
        assert [message['id'] for message in ChatService.get_messages(conversation_id=2, actor=actor)] == [3]
        result = ChatService.send_message('user', 'Single-slot persisted message', conversation_id=2, actor=actor)
        assert result['success'] and result['user_id'] == 1


def test_one_pool_slot_revalidation_rejects_stale_actor_and_cookie(one_slot_app, db_connection):
    with db_connection.cursor() as cursor:
        cursor.execute('UPDATE Customers SET auth_version=2 WHERE CustomerID=1')
    db_connection.commit()
    actor = ChatIdentity(1, auth_version=1)
    with one_slot_app.app_context():
        with pytest.raises(ChatAccessError) as error:
            ConversationService.get_participants(2, actor=actor)
        assert error.value.status == 401
    with one_slot_app.test_request_context('/'):
        from flask import session

        session.update(user_id=1, auth_version=1, user_name='Synthetic stale cookie')
        with pytest.raises(ChatAccessError) as error:
            ConversationService.get_access(2)
        assert error.value.status == 401
