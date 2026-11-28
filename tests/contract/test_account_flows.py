from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.database import CaseInsensitiveRecord
from app.services.auth_service import AuthService


@pytest.mark.parametrize(
    'path,service,args',
    [
        ('/update_profile', 'update_profile', {'full_name': 'Updated', 'phone': '0900000011', 'gender': 'other'}),
        ('/update_address', 'update_address', {'address': 'Test Address'}),
        (
            '/change_password',
            'change_password',
            {'current_password': 'OldPass123!', 'new_password': 'NewPass123!', 'confirm_password': 'NewPass123!'},
        ),
        ('/toggle_dark_mode', 'toggle_dark_mode', {'dark_mode': '1'}),
    ],
)
@pytest.mark.parametrize('success', [True, False])
def test_account_mutation_reports_success_and_failure(auth_client, monkeypatch, path, service, args, success):
    outcome = {'success': success, 'message': 'Test outcome', 'auth_version': 2}
    method = MagicMock(return_value=outcome)
    monkeypatch.setattr(AuthService, service, method)
    response = auth_client.post(path, data=args)
    assert response.status_code in {200, 302, 503}
    method.assert_called_once()
    with auth_client.session_transaction() as session:
        if service == 'change_password' and success:
            assert session['auth_version'] == 2
        if service == 'update_profile' and success:
            assert session['user_name'] == 'Updated'
        if service == 'toggle_dark_mode':
            assert session.get('dark_mode', False) is success


@pytest.mark.parametrize(
    'path,data',
    [
        ('/update_profile', {'full_name': ''}),
        ('/update_address', {'address': ''}),
        ('/change_password', {}),
        ('/change_password', {'new_password': 'weak', 'confirm_password': 'weak'}),
        ('/change_password', {'new_password': 'NewPass123!', 'confirm_password': 'WrongPass123!'}),
        (
            '/change_password',
            {'new_password': 'NewPass123!', 'confirm_password': 'NewPass123!', 'current_password': ''},
        ),
    ],
)
def test_account_invalid_forms_never_mutate(auth_client, monkeypatch, path, data):
    for name in ('update_profile', 'update_address', 'change_password'):
        monkeypatch.setattr(AuthService, name, MagicMock(side_effect=ValueError('Input must be validated')))
    # Services validate some fields; replace those with the real validation contract.
    if path == '/update_address':
        from app.validation import ValidationError

        monkeypatch.setattr(
            AuthService, 'update_address', MagicMock(side_effect=ValidationError('Địa chỉ không hợp lệ'))
        )
    assert auth_client.post(path, data=data).status_code == 302


def test_missing_account_clears_session(auth_client, monkeypatch):
    monkeypatch.setattr(AuthService, 'get_customer_profile', lambda _: None)
    assert auth_client.get('/my_account').status_code == 302
    with auth_client.session_transaction() as session:
        assert 'user_id' not in session


def test_avatar_database_failure_removes_new_file(auth_client, app, monkeypatch):
    buffer = BytesIO()
    Image.new('RGB', (4, 4)).save(buffer, 'PNG')
    buffer.seek(0)
    monkeypatch.setattr(AuthService, 'update_avatar', lambda *_: {'success': False, 'message': 'Test failure'})
    assert auth_client.post('/api/profile/avatar', data={'avatar': (buffer, 'avatar.png')}).status_code == 503
    from pathlib import Path

    assert not list(Path(app.config['UPLOAD_ROOT']).rglob('*.jpg'))


@pytest.mark.parametrize('token_data', [None, {'token': 'x' * 43, 'full_name': '<script>Test</script>'}])
def test_forgot_password_generic_response_and_safe_email(client, monkeypatch, token_data):
    monkeypatch.setattr(AuthService, 'issue_account_recovery_token', lambda _: token_data)
    send = MagicMock(return_value=True)
    monkeypatch.setattr('app.routes.auth.send_email', send)
    response = client.post('/forgot_password', data={'email': 'user@example.test'})
    assert response.status_code == 200
    if token_data:
        assert '&lt;script&gt;' in send.call_args.args[2]
    else:
        send.assert_not_called()


def test_forgot_invalid_email_never_issues_token(client, monkeypatch):
    issue = MagicMock()
    monkeypatch.setattr(AuthService, 'issue_account_recovery_token', issue)
    assert client.post('/forgot_password', data={'email': 'invalid'}).status_code == 400
    issue.assert_not_called()


@pytest.mark.parametrize(
    'data',
    [
        {},
        {'password': 'weak', 'confirm_password': 'weak'},
        {'password': 'NewPass123!', 'confirm_password': 'OtherPass123!'},
    ],
)
def test_reset_invalid_forms(client, monkeypatch, data):
    reset = MagicMock()
    monkeypatch.setattr(AuthService, 'reset_password', reset)
    assert client.post('/reset_password/' + 'a' * 43, data=data).status_code == 400
    reset.assert_not_called()


@pytest.mark.parametrize('success', [True, False])
def test_reset_result_display_and_session_clear(auth_client, monkeypatch, success):
    monkeypatch.setattr(AuthService, 'reset_password', lambda *_: {'success': success, 'message': 'Token expired'})
    response = auth_client.post(
        '/reset_password/' + 'a' * 43, data={'password': 'NewPass123!', 'confirm_password': 'NewPass123!'}
    )
    assert response.status_code == (200 if success else 400)
    if success:
        with auth_client.session_transaction() as session:
            assert 'user_id' not in session


def test_register_duplicate_returns_useful_error(client, monkeypatch):
    monkeypatch.setattr(AuthService, 'register_user', lambda *_: {'success': False, 'message': 'Đã tồn tại'})
    response = client.post(
        '/register',
        data={
            'full_name': 'Test',
            'email': 'test@example.test',
            'password': 'NewPass123!',
            'confirm_password': 'NewPass123!',
        },
    )
    assert response.status_code == 400
    assert 'Đã tồn tại' in response.text


def test_login_admin_default_destination(client, monkeypatch):
    monkeypatch.setattr(
        AuthService,
        'login_user',
        lambda *_: CaseInsensitiveRecord(
            CustomerID=2, FullName='Test', Role='admin', AuthVersion=1, DarkModeEnabled=False
        ),
    )
    response = client.post('/login', data={'email': 'admin@example.test', 'password': 'TestUser123!'})
    assert response.headers['Location'] == '/admin'
