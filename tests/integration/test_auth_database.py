from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
from threading import Barrier

import pytest
from bs4 import BeautifulSoup
from PIL import Image

from app.services.auth_service import AuthService


pytestmark = pytest.mark.integration


def test_login_reads_actual_hashed_password_and_role(db_client):
    response = db_client.post('/login', data={'email': ' CUSTOMER@EXAMPLE.TEST ', 'password': 'TestUser123!'})
    assert response.status_code == 302
    with db_client.session_transaction() as session:
        assert session['user_id'] == 1
        assert session['auth_version'] == 1
        assert session['role'] == 'customer'
        assert not session['is_admin']
    assert db_client.get('/my_account').status_code == 200
    assert db_client.get('/admin').status_code == 302


def test_replacing_avatar_removes_the_old_public_file(db_app, db_client):
    from pathlib import Path

    assert (
        db_client.post('/login', data={'email': 'customer@example.test', 'password': 'TestUser123!'}).status_code == 302
    )
    urls = []
    for color in ('blue', 'red'):
        raw = BytesIO()
        Image.new('RGB', (8, 8), color).save(raw, 'PNG')
        raw.seek(0)
        response = db_client.post('/api/profile/avatar', data={'avatar': (raw, 'avatar.png')})
        assert response.status_code == 200
        urls.append(response.json['avatar_url'])
    guest = db_app.test_client()
    assert guest.get(urls[0]).status_code == 404
    with guest.get(urls[1]) as current:
        assert current.status_code == 200
        assert current.headers['Cache-Control'] == 'no-store'
    assert len(list((Path(db_app.config['UPLOAD_ROOT']) / 'avatars').iterdir())) == 1


def test_register_normalizes_duplicates_and_password_hash(db_app, db_connection):
    with db_app.app_context():
        result = AuthService.register_user('New Test', ' NEW@EXAMPLE.TEST ', 'NewPass123!', None, None)
        assert result['success']
        assert AuthService.login_user('new@example.test', 'NewPass123!') is not None
        duplicate = AuthService.register_user('Duplicate', 'new@example.test', 'NewPass123!', None, None)
        assert not duplicate['success']
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT Password FROM Customers WHERE Email=%s', ('new@example.test',))
        assert cursor.fetchone().Password != 'NewPass123!'


def test_change_password_revokes_other_browser_session(db_app, db_client):
    other = db_app.test_client()
    credentials = {'email': 'customer@example.test', 'password': 'TestUser123!'}
    assert db_client.post('/login', data=credentials).status_code == 302
    assert other.post('/login', data=credentials).status_code == 302
    result = db_client.post(
        '/change_password',
        data={'current_password': 'TestUser123!', 'new_password': 'NewPass123!', 'confirm_password': 'NewPass123!'},
    )
    assert result.status_code == 302
    assert db_client.get('/my_account').status_code == 200
    assert other.get('/my_account').status_code == 302
    with other.session_transaction() as session:
        assert 'user_id' not in session


def test_password_reset_token_hashed_single_use_and_revokes(db_app, db_client, db_connection):
    db_client.post('/login', data={'email': 'customer@example.test', 'password': 'TestUser123!'})
    with db_app.app_context():
        issued = AuthService.issue_account_recovery_token('customer@example.test')
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT Token FROM PasswordResetTokens WHERE CustomerID=1 AND IsUsed=FALSE')
        assert cursor.fetchone().Token == hashlib.sha256(issued['token'].encode()).hexdigest()
    with db_app.app_context():
        assert AuthService.reset_password(issued['token'], 'ResetPass123!')['success']
        assert not AuthService.reset_password(issued['token'], 'AgainPass123!')['success']
        assert AuthService.login_user('customer@example.test', 'ResetPass123!')
    assert db_client.get('/my_account').status_code == 302


def test_failed_email_keeps_already_delivered_reset_link(db_app, db_client, db_connection, monkeypatch):
    with db_app.app_context():
        delivered = AuthService.issue_account_recovery_token('customer@example.test')
    monkeypatch.setattr('app.routes.auth.send_email', lambda *_: False)
    for email in ('customer@example.test', 'unknown@example.test'):
        response = db_client.post('/forgot_password', data={'email': email})
        assert response.status_code == 200
        assert 'Kiểm tra hộp thư' in response.get_data(as_text=True)
    with db_app.app_context():
        assert AuthService.reset_password(delivered['token'], 'FirstReset123!')['success']
        assert AuthService.login_user('customer@example.test', 'FirstReset123!')
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS active FROM PasswordResetTokens WHERE CustomerID=1 AND IsUsed=FALSE')
        assert cursor.fetchone().active == 0


def test_parallel_resets_with_different_tokens_only_change_password_once(db_app, db_connection):
    with db_app.app_context():
        tokens = [AuthService.issue_account_recovery_token('customer@example.test')['token'] for _ in range(2)]
    start = Barrier(2)

    def reset(token, password):
        with db_app.app_context():
            start.wait(timeout=5)
            return AuthService.reset_password(token, password)['success']

    passwords = ('FirstReset123!', 'SecondReset123!')
    with ThreadPoolExecutor(max_workers=2) as workers:
        requests = [workers.submit(reset, token, password) for token, password in zip(tokens, passwords, strict=True)]
        results = [request.result(timeout=5) for request in requests]
    assert sum(results) == 1
    with db_app.app_context():
        assert AuthService.login_user('customer@example.test', passwords[results.index(True)])
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT auth_version FROM Customers WHERE CustomerID=1')
        assert cursor.fetchone().auth_version == 2


def test_expired_reset_rejected(db_app, db_connection):
    with db_app.app_context():
        issued = AuthService.issue_account_recovery_token('customer@example.test')
    with db_connection.cursor() as cursor:
        cursor.execute("UPDATE PasswordResetTokens SET ExpiryDate=CURRENT_TIMESTAMP - INTERVAL '1 second'")
    db_connection.commit()
    with db_app.app_context():
        assert not AuthService.reset_password(issued['token'], 'ResetPass123!')['success']


def test_admin_demotion_effective_next_request(db_client, db_connection):
    db_client.post('/login', data={'email': 'admin@example.test', 'password': 'TestUser123!'})
    with db_connection.cursor() as cursor:
        cursor.execute("UPDATE Customers SET IsAdmin=FALSE,role='customer' WHERE CustomerID=2")
    db_connection.commit()
    assert db_client.get('/admin').status_code == 302
    with db_client.session_transaction() as session:
        assert session['role'] == 'customer'
        assert not session['is_admin']


def test_csrf_still_required_with_real_database(db_app, db_client):
    db_app.config['WTF_CSRF_ENABLED'] = True
    assert (
        db_client.post('/login', data={'email': 'customer@example.test', 'password': 'TestUser123!'}).status_code == 400
    )
    page = db_client.get('/login')
    token = BeautifulSoup(page.data, 'html.parser').select_one('input[name=csrf_token]')['value']
    assert (
        db_client.post(
            '/login', data={'email': 'customer@example.test', 'password': 'TestUser123!', 'csrf_token': token}
        ).status_code
        == 302
    )
    assert db_client.post('/logout').status_code == 400


def test_profile_and_avatar_columns_are_canonical(db_app):
    with db_app.app_context():
        assert AuthService.update_profile(1, 'Updated Name', '0900000011', 'female', '2000-02-29')['success']
        assert AuthService.update_address(1, 'Updated Address')['success']
        assert AuthService.update_avatar(1, '/uploads/avatars/test.jpg')['success']
        assert AuthService.toggle_dark_mode(1, True)['success']
        profile = AuthService.get_customer_profile(1)
        assert profile.FullName == 'Updated Name'
        assert str(profile.DateOfBirth) == '2000-02-29'
        assert profile.AvatarUrl == profile.avatar_url == '/uploads/avatars/test.jpg'
        assert profile.DarkModeEnabled
