from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image
from werkzeug.security import generate_password_hash

from app import create_app
from app.database import CaseInsensitiveRecord
from app.services.auth_service import AuthService


@pytest.mark.parametrize('path', ['/login', '/register', '/forgot_password', '/reset_password/test-token-long-enough'])
def test_public_auth_pages_render_without_database(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert b'csrf-token' in response.data


def test_logout_is_post_and_csrf_protected(app, auth_client):
    assert auth_client.get('/logout').status_code == 405
    app.config['WTF_CSRF_ENABLED'] = True
    assert auth_client.post('/logout').status_code == 400
    app.config['WTF_CSRF_ENABLED'] = False
    assert auth_client.post('/logout').status_code == 302
    with auth_client.session_transaction() as session:
        assert 'user_id' not in session


def test_login_normalizes_identity_and_blocks_external_next(client, monkeypatch):
    identity = CaseInsensitiveRecord(
        CustomerID=9, FullName='Người dùng', Role='customer', AuthVersion=3, DarkModeEnabled=False
    )
    login = MagicMock(return_value=identity)
    monkeypatch.setattr(AuthService, 'login_user', login)
    response = client.post('/login?next=//evil.test', data={'email': ' User@Example.TEST ', 'password': 'TestPass123!'})
    assert response.status_code == 302
    assert response.headers['Location'] == '/'
    login.assert_called_once_with('user@example.test', 'TestPass123!')
    with client.session_transaction() as session:
        assert session['auth_version'] == 3
        assert session['role'] == 'customer'
        assert not session['is_admin']


def test_login_keeps_local_next(client, monkeypatch):
    monkeypatch.setattr(
        AuthService,
        'login_user',
        lambda *_: CaseInsensitiveRecord(
            CustomerID=1, FullName='Test', Role='customer', AuthVersion=1, DarkModeEnabled=False
        ),
    )
    response = client.post(
        '/login', data={'email': 'user@example.test', 'password': 'TestPass123!', 'next': '/checkout?buy_now=1'}
    )
    assert response.headers['Location'] == '/checkout?buy_now=1'


@pytest.mark.parametrize('data', [{}, {'email': 'invalid', 'password': 'pass'}, {'email': 'a@b.test', 'password': ''}])
def test_login_invalid_does_not_access_database(client, data):
    assert client.post('/login', data=data).status_code == 400


def test_register_mismatch_never_calls_service(client, monkeypatch):
    register = MagicMock()
    monkeypatch.setattr(AuthService, 'register_user', register)
    response = client.post(
        '/register',
        data={
            'full_name': 'Test',
            'email': 'user@example.test',
            'password': 'GoodPass123!',
            'confirm_password': 'wrong',
        },
    )
    assert response.status_code == 400
    register.assert_not_called()


def test_register_uses_customer_role_and_preserves_cart(client, monkeypatch):
    monkeypatch.setattr(
        AuthService,
        'register_user',
        lambda *_: {'success': True, 'customer_id': 8, 'full_name': 'Test', 'auth_version': 1},
    )
    with client.session_transaction() as session:
        session['cart'] = [{'variant_id': 1, 'quantity': 2}]
        session['is_admin'] = True
    response = client.post(
        '/register',
        data={
            'full_name': 'Test',
            'email': 'user@example.test',
            'password': 'GoodPass123!',
            'confirm_password': 'GoodPass123!',
            'is_admin': '1',
        },
    )
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session['role'] == 'customer'
        assert not session['is_admin']
        assert session['cart'][0]['quantity'] == 2


def test_api_login_guard_returns_json(client):
    response = client.post('/api/profile/avatar')
    assert response.status_code == 401
    assert response.json['success'] is False


def test_avatar_rejects_disguised_active_content(auth_client):
    response = auth_client.post(
        '/api/profile/avatar', data={'avatar': (BytesIO(b'<script>alert(1)</script>'), 'avatar.png')}
    )
    assert response.status_code == 400
    assert response.json['success'] is False


def test_avatar_saves_decoded_image_and_checks_service_result(auth_client, monkeypatch):
    buffer = BytesIO()
    Image.new('RGB', (8, 8), 'blue').save(buffer, 'PNG')
    buffer.seek(0)
    monkeypatch.setattr(AuthService, 'update_avatar', lambda *_: {'success': True})
    response = auth_client.post('/api/profile/avatar', data={'avatar': (buffer, 'avatar.png')})
    assert response.status_code == 200
    url = response.json['avatar_url']
    assert url.startswith('/uploads/avatars/')
    image_response = auth_client.get(url)
    assert image_response.mimetype == 'image/jpeg'
    image_response.close()
    assert auth_client.get('/uploads/avatars/../anything').status_code == 404


def test_session_revalidation_revokes_stale_or_deleted_identity(app, auth_client, monkeypatch):
    app.config['SESSION_REVALIDATION_ENABLED'] = True
    monkeypatch.setattr(
        AuthService,
        'get_identity_state',
        lambda _: CaseInsensitiveRecord(AuthVersion=2, FullName='Test', Role='admin', DarkModeEnabled=False),
    )
    response = auth_client.get('/my_account')
    assert response.status_code == 302
    with auth_client.session_transaction() as session:
        assert 'user_id' not in session


def test_session_role_refresh_removes_stale_admin(app, admin_client, monkeypatch):
    app.config['SESSION_REVALIDATION_ENABLED'] = True
    monkeypatch.setattr(
        AuthService,
        'get_identity_state',
        lambda _: CaseInsensitiveRecord(AuthVersion=1, FullName='Test', Role='customer', DarkModeEnabled=False),
    )
    assert admin_client.get('/admin').status_code in {302, 404}
    with admin_client.session_transaction() as session:
        assert session['role'] == 'customer'
        assert not session['is_admin']


def test_toggle_invalid_input_does_not_mutate(auth_client, monkeypatch):
    toggle = MagicMock()
    monkeypatch.setattr(AuthService, 'toggle_dark_mode', toggle)
    assert auth_client.post('/toggle_dark_mode', data={'dark_mode': '99'}).status_code == 400
    toggle.assert_not_called()


def test_security_headers_do_not_allow_unsafe_eval(client):
    response = client.get('/login')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'unsafe-eval' not in response.headers['Content-Security-Policy']
    assert 'Strict-Transport-Security' not in response.headers


def test_missing_secrets_fail_before_database_connection():
    with pytest.raises(ValueError, match='SECRET_KEY'):
        create_app({'SECRET_KEY': None, 'DB_CONNECT_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})


def test_auth_hash_check_and_reset_digest(fake_db):
    fake_db.cursor.fetchone.return_value = CaseInsensitiveRecord(
        CustomerID=1, FullName='Test', Password=generate_password_hash('GoodPass123!')
    )
    assert AuthService.login_user('user@example.test', 'wrong') is None
    result = AuthService.create_password_reset_token('user@example.test')
    assert len(result['token']) >= 32
    insert = fake_db.cursor.execute.call_args_list[-1]
    assert result['token'] not in str(insert)
    assert len(insert.args[1][1]) == 64
    fake_db.conn.commit.assert_called_once()
