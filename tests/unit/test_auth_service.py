import hashlib
from unittest.mock import MagicMock

import psycopg2
import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import CaseInsensitiveRecord
from app.services.auth_service import AuthService
from app.services.base_service import BaseService
from app.validation import ValidationError


@pytest.mark.parametrize(
    'method,args',
    [
        ('register_user', ('Test', 'user@example.test', 'GoodPass123!', None, None)),
        ('update_profile', (1, 'Test', None, 'other', '2000-01-01')),
        ('update_address', (1, 'Test address')),
        ('update_avatar', (1, '/uploads/avatars/test.jpg')),
        ('toggle_dark_mode', (1, True)),
    ],
)
def test_auth_mutations_commit_and_close(fake_db, method, args):
    fake_db.cursor.fetchone.return_value = CaseInsensitiveRecord(CustomerID=4)
    result = getattr(AuthService, method)(*args)
    assert result['success']
    fake_db.conn.commit.assert_called_once()
    fake_db.conn.close.assert_called_once()


@pytest.mark.parametrize(
    'method,args',
    [
        ('register_user', ('Test', 'user@example.test', 'GoodPass123!', None, None)),
        ('update_profile', (1, 'Test', None, 'other', None)),
        ('update_address', (1, 'Test address')),
        ('update_avatar', (1, '/uploads/avatars/test.jpg')),
        ('toggle_dark_mode', (1, True)),
    ],
)
def test_auth_database_failure_rolls_back_without_details(app, fake_db, method, args):
    fake_db.cursor.execute.side_effect = psycopg2.OperationalError('password=secret connection details')
    with app.app_context():
        result = getattr(AuthService, method)(*args)
    assert not result['success']
    assert 'secret' not in result['message']
    fake_db.conn.rollback.assert_called_once()
    fake_db.conn.close.assert_called_once()


@pytest.mark.parametrize(
    'method,args',
    [
        ('register_user', ('Test', 'user@example.test', 'GoodPass123!', None, None)),
        ('update_profile', (1, 'Test', '0900000001', 'other', None)),
    ],
)
def test_auth_unique_error_is_safe(fake_db, method, args):
    fake_db.cursor.execute.side_effect = psycopg2.IntegrityError('duplicate')
    result = getattr(AuthService, method)(*args)
    assert not result['success']
    fake_db.conn.rollback.assert_called_once()


def test_profile_invalid_fields_do_not_open_database(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr(BaseService, 'get_connection', connection)
    with pytest.raises(ValidationError):
        AuthService.update_profile(1, 'Test', None, 'invalid', None)
    with pytest.raises(ValidationError):
        AuthService.update_profile(1, 'Test', None, 'other', '2999-01-01')
    connection.assert_not_called()


def test_password_change_checks_hash_revokes_and_marks_tokens(fake_db):
    fake_db.cursor.fetchone.side_effect = [
        CaseInsensitiveRecord(Password=generate_password_hash('OldPass123!')),
        CaseInsensitiveRecord(AuthVersion=2),
    ]
    result = AuthService.change_password(1, 'OldPass123!', 'NewPass123!')
    assert result == {'success': True, 'auth_version': 2}
    password_update = fake_db.cursor.execute.call_args_list[1]
    assert check_password_hash(password_update.args[1][0], 'NewPass123!')
    assert 'auth_version + 1' in password_update.args[0]
    assert 'IsUsed = TRUE' in fake_db.cursor.execute.call_args_list[2].args[0]
    fake_db.conn.commit.assert_called_once()


def test_wrong_password_does_not_mutate(fake_db):
    fake_db.cursor.fetchone.return_value = CaseInsensitiveRecord(Password=generate_password_hash('OldPass123!'))
    assert not AuthService.change_password(1, 'WrongPass123!', 'NewPass123!')['success']
    fake_db.conn.commit.assert_not_called()
    assert fake_db.cursor.execute.call_count == 1


def test_reset_locks_customer_then_claims_token_and_revokes_all(fake_db):
    fake_db.cursor.fetchone.side_effect = [CaseInsensitiveRecord(CustomerID=1), CaseInsensitiveRecord(TokenID=4)]
    token = 'a' * 43
    digest = hashlib.sha256(token.encode()).hexdigest()
    assert AuthService.reset_password(token, 'NewPass123!')['success']
    lock, claim, password, invalidate = [call.args for call in fake_db.cursor.execute.call_args_list]
    assert 'FOR UPDATE OF c' in lock[0]
    assert lock[1] == (digest,)
    assert 'UPDATE PasswordResetTokens' in claim[0] and 'IsUsed = FALSE' in claim[0]
    assert claim[1] == (1, digest)
    assert 'auth_version + 1' in password[0]
    assert 'UPDATE PasswordResetTokens' in invalidate[0] and invalidate[1] == (1,)
    fake_db.conn.commit.assert_called_once()


def test_reset_rechecks_after_waiting_for_customer_lock(fake_db):
    fake_db.cursor.fetchone.side_effect = [CaseInsensitiveRecord(CustomerID=1), None]
    assert not AuthService.reset_password('a' * 43, 'NewPass123!')['success']
    assert fake_db.cursor.execute.call_count == 2
    fake_db.conn.commit.assert_not_called()


def test_reset_missing_and_invalid_do_not_write(fake_db):
    assert not AuthService.reset_password('short', 'NewPass123!')['success']
    assert not AuthService.reset_password('!' * 43, 'NewPass123!')['success']
    fake_db.conn.cursor.assert_not_called()
    fake_db.cursor.fetchone.return_value = None
    assert not AuthService.reset_password('a' * 43, 'NewPass123!')['success']
    fake_db.conn.commit.assert_not_called()


def test_reset_unknown_customer_does_not_create_token(fake_db):
    fake_db.cursor.fetchone.return_value = None
    assert AuthService.issue_account_recovery_token('nobody@example.test') is None
    fake_db.conn.commit.assert_not_called()


def test_identity_and_profile_return_records(fake_db):
    row = CaseInsensitiveRecord(CustomerID=1, AuthVersion=2)
    fake_db.cursor.fetchone.return_value = row
    assert AuthService.get_identity_state(1) is row
    assert AuthService.get_customer_profile(1) is row
    assert 'avatar_url AS AvatarUrl' in fake_db.cursor.execute.call_args.args[0]
