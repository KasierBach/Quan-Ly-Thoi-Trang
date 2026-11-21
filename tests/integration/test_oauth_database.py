"""OAuth identity/one-use ledger behavior against the guarded disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.auth_service import AuthService
from app.services.oauth_service import OAuthAccountConflict, OAuthFailure, OAuthService, PROVIDERS, VerifiedIdentity


pytestmark = pytest.mark.integration


def verified(subject='synthetic-new-subject', email='oauth-new@example.test'):
    return VerifiedIdentity('google', PROVIDERS['google'].issuer, subject, email, 'Synthetic OAuth Customer')


def run_in_app(application, operation):
    with application.app_context():
        return operation()


def test_oauth_only_customer_is_created_once_and_password_auth_remains_unavailable(db_app, db_connection):
    identity = verified()
    with db_app.app_context():
        user = OAuthService.login_or_register(identity)
        same = OAuthService.login_or_register(identity)
        assert user.CustomerID == same.CustomerID
        assert AuthService.login_user(identity.email, 'NoPasswordWasEverSet123!') is None
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT Password,IsAdmin FROM Customers WHERE CustomerID=%s', (user.CustomerID,))
        row = cursor.fetchone()
        assert row.Password is None and row.IsAdmin is False
        cursor.execute('SELECT COUNT(*) AS total FROM OAuthIdentities WHERE customer_id=%s', (user.CustomerID,))
        assert cursor.fetchone().total == 1


def test_verified_email_match_is_not_authority_to_auto_link_existing_customer(db_app, db_connection):
    identity = verified(email='customer@example.test')
    with db_app.app_context(), pytest.raises(OAuthAccountConflict):
        OAuthService.login_or_register(identity)
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM OAuthIdentities WHERE customer_id=1')
        assert cursor.fetchone().total == 0


def test_explicit_identity_link_unlink_bumps_auth_version_and_preserves_password_access(db_app, db_connection):
    identity = verified(email='customer@example.test')
    with db_app.app_context():
        assert OAuthService.reauthenticate_password(1, 1, 'TestUser123!')
        version = OAuthService.link_identity(identity, 1, 1)
        assert version == 2
        user = OAuthService.login_or_register(identity)
        assert user.CustomerID == 1 and user.AuthVersion == 2
        assert OAuthService.unlink_identity('google', 1, version) == 3
        assert AuthService.login_user('customer@example.test', 'TestUser123!') is not None
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM OAuthIdentities WHERE customer_id=1')
        assert cursor.fetchone().total == 0


def test_stale_link_version_and_last_oauth_identity_unlink_are_rejected(db_app):
    with db_app.app_context():
        user = OAuthService.login_or_register(verified())
        with pytest.raises(OAuthFailure):
            OAuthService.unlink_identity('google', user.CustomerID, user.AuthVersion)
        with pytest.raises(OAuthFailure):
            OAuthService.link_identity(verified(subject='second'), 1, 999)


def test_state_ticket_can_be_consumed_exactly_once_in_racing_workers(db_app):
    token, binding = OAuthService.new_ticket(), OAuthService.new_ticket()
    data = {'redirect_uri': 'https://store.example.test/oauth/google/callback', 'nonce': 'synthetic-only'}
    with db_app.app_context():
        OAuthService.issue_ticket(token, binding, 'authorization', data)

    def consume():
        try:
            return run_in_app(db_app, lambda: OAuthService.consume_ticket(token, binding, 'authorization'))
        except OAuthFailure:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: consume(), range(2)))
    assert results.count(data) == 1 and results.count(None) == 1


def test_wrong_ticket_binding_cannot_destroy_legitimate_flow(db_app):
    token, binding = OAuthService.new_ticket(), OAuthService.new_ticket()
    with db_app.app_context():
        OAuthService.issue_ticket(token, binding, 'authorization', {'nonce': 'synthetic'})
        with pytest.raises(OAuthFailure):
            OAuthService.consume_ticket(token, OAuthService.new_ticket(), 'authorization')
        assert OAuthService.consume_ticket(token, binding, 'authorization') == {'nonce': 'synthetic'}
