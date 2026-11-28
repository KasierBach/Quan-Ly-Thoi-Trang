import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import urlsplit

import psycopg2
import pytest

# Test configuration is passed before any app/pool creation; never load a real .env.
os.environ['DISABLE_DOTENV'] = '1'

from app import create_app
from app.database import CaseInsensitiveCursor, close_db_pool


ROOT = Path(__file__).resolve().parents[1]


class TestConfig:
    TESTING = True
    APP_ENV = 'testing'
    SECRET_KEY = 'main-test-secret-key-not-used-outside-tests-2026'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    DATABASE_URL = None
    DB_POOL_ENABLED = False
    DB_CONNECT_ENABLED = False
    SESSION_REVALIDATION_ENABLED = False
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    TRUSTED_PROXY_COUNT = 0
    TRUSTED_HOSTS = ['localhost', '127.0.0.1']
    RATELIMIT_ENABLED = False
    MAIL_SUPPRESS_SEND = True
    MAIL_DEFAULT_SENDER = 'test-store@example.test'
    MAIL_USE_TLS = False
    MAIL_USE_SSL = False
    PIXABAY_API_KEY = None


@pytest.fixture
def app(tmp_path):
    application = create_app(TestConfig)
    application.config['UPLOAD_ROOT'] = str(tmp_path / 'uploads')
    yield application
    handlers = application.extensions.get('chat_socket_handlers')
    if handlers is not None:
        handlers.close()
    close_db_pool(application)


@pytest.fixture
def client(app):
    return app.test_client()


def sign_in(client, user_id=1, role='customer'):
    with client.session_transaction() as session:
        session.update(user_id=user_id, user_name='Test User', role=role, is_admin=role == 'admin', auth_version=1)
    return client


@pytest.fixture
def auth_client(client):
    return sign_in(client)


@pytest.fixture
def admin_client(client):
    return sign_in(client, 2, 'admin')


@pytest.fixture
def fake_db(monkeypatch):
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.rowcount = 1
    from app.services.base_service import BaseService

    monkeypatch.setattr(BaseService, 'get_connection', staticmethod(lambda: connection))
    return SimpleNamespace(connection=connection, conn=connection, cursor=cursor)


@pytest.fixture(scope='session')
def database_url():
    value = os.environ.get('TEST_DATABASE_URL')
    if not value:
        pytest.skip('TEST_DATABASE_URL is required for PostgreSQL integration')
    parsed = urlsplit(value)
    if (
        parsed.scheme != 'postgresql'
        or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
        or parsed.path != '/thua2_main_test'
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError('Integration tests refuse any database except the local thua2_main_test database')
    return value


@pytest.fixture
def db_connection(database_url):
    connection = psycopg2.connect(database_url, cursor_factory=CaseInsensitiveCursor, connect_timeout=5)
    try:
        with connection.cursor() as cursor:
            cursor.execute((ROOT / 'db' / 'bootstrap.sql').read_text(encoding='utf-8'))
            cursor.execute("""
                TRUNCATE Attachments, Reactions, PinnedMessages, Messages, Participants, Conversations,
                         PasswordResetTokens, ProductComments, Reviews, Wishlist, ContactMessages,
                         NewsletterSubscribers, OrderDetails, Orders, InventoryAdjustments, ProductVariants, Products,
                         Sizes, Colors, Categories, Customers RESTART IDENTITY CASCADE
            """)
            cursor.execute("SELECT set_config('thua2.allow_test_seed', 'loopback-disposable', false)")
            cursor.execute((ROOT / 'db' / 'seed_test.sql').read_text(encoding='utf-8'))
        connection.commit()
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def db_app(database_url, db_connection, tmp_path):
    config = {key: getattr(TestConfig, key) for key in dir(TestConfig) if key.isupper()}
    config.update(
        DATABASE_URL=database_url,
        SQLALCHEMY_DATABASE_URI=database_url.replace('postgresql://', 'postgresql+psycopg2://'),
        DB_CONNECT_ENABLED=True,
        DB_POOL_ENABLED=True,
        SESSION_REVALIDATION_ENABLED=True,
        UPLOAD_ROOT=str(tmp_path / 'uploads'),
    )
    application = create_app(config)
    yield application
    handlers = application.extensions.get('chat_socket_handlers')
    if handlers is not None:
        handlers.close()
    close_db_pool(application)


@pytest.fixture
def db_client(db_app):
    return db_app.test_client()
