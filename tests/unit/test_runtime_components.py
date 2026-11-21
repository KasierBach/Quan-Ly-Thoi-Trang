import json
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import app.config as app_config
import app.extensions as app_extensions

import psycopg2
import pytest
from flask import abort
from PIL import Image
from psycopg2.extensions import TRANSACTION_STATUS_IDLE

from app.cache import SimpleCache, cached, invalidate_cache
from app.config import Config, validate_config
from app.database import (
    CaseInsensitiveRecord,
    PooledConnection,
    close_db_connection,
    close_db_pool,
    get_db_connection,
    init_db_pool,
)
from app.decorators import handle_db_errors
from app.uploads import image_bytes
from app.utils import DecimalEncoder, resolve_image, send_email, slugify


@pytest.mark.parametrize('format', ['PNG', 'JPEG', 'GIF', 'WEBP'])
def test_images_reencoded_not_trusted_by_extension(app, format):
    data = BytesIO()
    Image.new('RGB', (4, 4), 'red').save(data, format)
    with app.app_context():
        raw, extension, mime = image_bytes(data.getvalue())
    assert raw.startswith(b'\xff\xd8') and extension == 'jpg' and mime == 'image/jpeg'


def test_image_size_and_unknown_type_rejected(app):
    with app.app_context():
        with pytest.raises(ValueError):
            image_bytes(b'')
        app.config['MAX_CONTENT_LENGTH'] = 8
        with pytest.raises(ValueError):
            image_bytes(b'not-an-image' * 3)


def test_email_suppression_and_configuration(app, monkeypatch):
    from app import mail

    with app.app_context():
        with mail.record_messages() as outbox:
            assert send_email('user@example.test', 'Subject', '<p>Test</p>', [('report.csv', 'text/csv', b'test')])
            assert len(outbox) == 1
            assert outbox[0].attachments[0].data == b'test'
        app.config['MAIL_SUPPRESS_SEND'] = False
        assert not send_email('user@example.test', 'Subject', 'Test')
        assert not send_email('invalid', 'Subject', 'Test')
        app.config.update(MAIL_USERNAME='test', MAIL_PASSWORD='synthetic', MAIL_DEFAULT_SENDER='test@example.test')
        monkeypatch.setattr(mail, 'send', MagicMock(side_effect=OSError('SMTP failed')))
        assert not send_email('user@example.test', 'Subject', 'Test')


def test_utils_decimal_and_slug(app):
    assert json.loads(json.dumps({'price': Decimal('1.25')}, cls=DecimalEncoder)) == {'price': 1.25}
    with pytest.raises(TypeError):
        json.dumps(object(), cls=DecimalEncoder)
    assert slugify(None) == ''
    assert slugify('Áo Thun') == 'ao-thun'
    with app.app_context():
        assert resolve_image(None) == 'images/default.jpg'
        assert resolve_image({'ImageURL': 'images/ao.jpg'}) == 'images/ao.jpg'
        assert resolve_image({'product_id': 99999, 'ProductName': 'No Asset'}) == 'images/default.jpg'


def test_cache_expiry_lru_and_invalidation(monkeypatch):
    clock = [0]
    monkeypatch.setattr('app.cache.time.monotonic', lambda: clock[0])
    store = SimpleCache(default_timeout=10, max_entries=2)
    store.set('a', 1)
    store.set('b', 2)
    assert store.get('a') == 1
    store.set('c', 3)
    assert store.get('b') is None
    clock[0] = 20
    assert store.get('a') is None
    store.delete('missing')
    store.invalidate('c')
    store.set('d', 4)
    store.clear()
    assert store.get('d') is None


def test_cached_args_and_pattern_invalidation(app):
    calls = []

    @cached(timeout=20, key_prefix='test')
    def value(number):
        calls.append(number)
        return number

    with app.app_context():
        assert value(3) == value(3) == 3
        assert calls == [3]
        invalidate_cache('test')
        assert value(3) == 3
        assert calls == [3, 3]
        invalidate_cache()


def test_pools_are_per_app_and_close_idempotently(app, monkeypatch):
    pools = []

    def factory(**kwargs):
        pool = MagicMock()
        pools.append(pool)
        return pool

    monkeypatch.setattr('app.database.ThreadedConnectionPool', factory)
    app.config.update(DB_POOL_ENABLED=True, DB_CONNECT_ENABLED=True, DATABASE_URL='postgresql://test@localhost/test')
    assert init_db_pool(app) is init_db_pool(app)
    assert len(pools) == 1
    close_db_pool(app)
    close_db_pool(app)
    pools[0].closeall.assert_called_once()


def test_pool_health_and_recovery(app, monkeypatch):
    pool = MagicMock()
    dead, healthy = MagicMock(), MagicMock()
    dead.closed = True
    healthy.closed = False
    healthy.get_transaction_status.return_value = TRANSACTION_STATUS_IDLE
    pool.getconn.side_effect = [dead, healthy]
    app.config.update(DB_CONNECT_ENABLED=True, DB_POOL_ENABLED=True)
    monkeypatch.setattr('app.database.init_db_pool', lambda _: pool)
    with app.app_context():
        connection = get_db_connection()
        connection.close()
    pool.putconn.assert_any_call(dead, close=True)
    assert healthy.rollback.call_count == 1


def test_pool_unhealthy_exhausted_fails_without_unbounded_fallback(app, monkeypatch):
    pool, dead = MagicMock(), MagicMock()
    dead.closed = False
    dead.get_transaction_status.return_value = TRANSACTION_STATUS_IDLE
    dead.cursor.return_value.__enter__.side_effect = psycopg2.OperationalError('dead')
    pool.getconn.return_value = dead
    app.config.update(DB_CONNECT_ENABLED=True, DB_POOL_ENABLED=True)
    monkeypatch.setattr('app.database.init_db_pool', lambda _: pool)
    connect = MagicMock()
    monkeypatch.setattr('app.database.psycopg2.connect', connect)
    with app.app_context(), pytest.raises(psycopg2.OperationalError):
        get_db_connection()
    assert pool.putconn.call_count == 3
    connect.assert_not_called()


def test_disabled_db_never_connects(app):
    with app.app_context(), pytest.raises(RuntimeError, match='disabled'):
        get_db_connection()
    close_db_connection(None)


def test_pooled_close_discards_rollback_failure():
    pool, conn = MagicMock(), MagicMock()
    conn.closed = False
    conn.get_transaction_status.return_value = 2
    conn.rollback.side_effect = psycopg2.InterfaceError('bad')
    wrapped = PooledConnection(pool, conn)
    wrapped.close()
    pool.putconn.assert_called_once_with(conn, close=True)
    with pytest.raises(psycopg2.InterfaceError):
        wrapped.cursor()


@pytest.mark.parametrize(
    'change',
    [
        {'MAIL_USE_TLS': True, 'MAIL_USE_SSL': True},
        {'TRUSTED_PROXY_COUNT': 2},
        {'TRUSTED_PROXY_COUNT': True},
        {'APP_ENV': 'production', 'SESSION_COOKIE_SECURE': False},
        {'APP_ENV': 'production', 'SESSION_COOKIE_SECURE': True, 'TRUSTED_HOSTS': []},
        {
            'APP_ENV': 'production',
            'SESSION_COOKIE_SECURE': True,
            'TRUSTED_HOSTS': ['example.test'],
            'PUBLIC_BASE_URL': 'http://example.test',
        },
        {
            'APP_ENV': 'production',
            'SESSION_COOKIE_SECURE': True,
            'TRUSTED_HOSTS': ['example.test'],
            'PUBLIC_BASE_URL': 'https://example.test',
            'RATELIMIT_STORAGE_URI': 'memory://',
        },
    ],
)
def test_configuration_errors_are_actionable(change):
    with pytest.raises(ValueError):
        validate_config({'SECRET_KEY': 'x' * 48, 'DB_CONNECT_ENABLED': False, **change})


def test_env_config_reads_only_explicit_worktree(monkeypatch):
    calls = []
    monkeypatch.setenv('DISABLE_DOTENV', '0')
    monkeypatch.setenv('APP_ENV', 'testing')
    monkeypatch.setenv('DATABASE_URL', 'postgres://test@localhost/test')
    monkeypatch.setattr('app.config.load_dotenv', lambda path: calls.append(path))
    values = Config.from_environment()
    assert calls[0].name == '.env'
    # The .env must come from this project's root (the folder containing the app
    # package), never from an arbitrary parent directory of the checkout.
    assert calls[0].parent == Path(app_config.__file__).resolve().parents[1]
    assert values['DATABASE_URL'].startswith('postgresql://')
    monkeypatch.setenv('APP_ENV', 'invalid')
    with pytest.raises(ValueError):
        Config.from_environment()


def test_package_reexports_exact_extension_singletons():
    from app import csrf, limiter, mail, socketio

    assert socketio is app_extensions.socketio
    assert limiter is app_extensions.limiter
    assert mail is app_extensions.mail
    assert csrf is app_extensions.csrf


def test_json_decimal_exact(app):
    with app.app_context():
        assert app.json.loads(app.json.dumps({'amount': Decimal('0.10')})) == {'amount': '0.10'}


def test_decorator_keeps_http_errors_and_safe_validation(app):
    @app.route('/api/test-http')
    @handle_db_errors
    def test_http():
        abort(409)

    @app.route('/api/test-db')
    @handle_db_errors
    def test_db():
        raise psycopg2.OperationalError('secret database URI')

    client = app.test_client()
    assert client.get('/api/test-http').status_code == 409
    response = client.get('/api/test-db')
    assert response.status_code == 503
    assert b'secret' not in response.data


def test_session_role_revalidation_refresh(app, auth_client, monkeypatch):
    from app.services.auth_service import AuthService

    app.config['SESSION_REVALIDATION_ENABLED'] = True
    monkeypatch.setattr(
        AuthService,
        'get_identity_state',
        lambda _: CaseInsensitiveRecord(AuthVersion=1, FullName='Updated', Role='customer', DarkModeEnabled=True),
    )
    assert auth_client.get('/login').status_code == 200
    with auth_client.session_transaction() as session:
        assert session['user_name'] == 'Updated'
        assert session['dark_mode']
