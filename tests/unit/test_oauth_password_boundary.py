"""Password flows must fail closed for accounts with only an OAuth identity."""

import pytest

from app.database import CaseInsensitiveRecord
from app.services.auth_service import AuthService


@pytest.mark.parametrize('stored', [None, '', 123, b'not-a-password-hash'])
def test_password_login_denies_missing_hash_without_calling_werkzeug(fake_db, monkeypatch, stored):
    fake_db.cursor.fetchone.return_value = CaseInsensitiveRecord(Password=stored)
    checked = []
    monkeypatch.setattr('app.services.auth_service.check_password_hash', lambda *args: checked.append(args))
    assert AuthService.login_user('synthetic@example.test', 'ProvidedPassword123!') is None
    assert checked == []
    fake_db.conn.close.assert_called_once()


@pytest.mark.parametrize('stored', [None, '', 123, b'not-a-password-hash'])
def test_password_change_denies_missing_hash_without_mutation(fake_db, monkeypatch, stored):
    fake_db.cursor.fetchone.return_value = CaseInsensitiveRecord(Password=stored)
    checked = []
    monkeypatch.setattr('app.services.auth_service.check_password_hash', lambda *args: checked.append(args))
    result = AuthService.change_password(1, 'ProvidedPassword123!', 'ReplacementPassword456!')
    assert result['success'] is False
    assert checked == []
    assert fake_db.cursor.execute.call_count == 1
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()
