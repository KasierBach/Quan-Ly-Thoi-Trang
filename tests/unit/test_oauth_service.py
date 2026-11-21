"""Offline provider doubles and SQL transaction contracts; never external OAuth."""

import logging
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import psycopg2
import pytest
from flask import session
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey
from werkzeug.security import generate_password_hash

from app.database import CaseInsensitiveRecord
from app.services.oauth_service import (
    OAuthAccountConflict,
    OAuthFailure,
    OAuthService,
    OAuthUnavailable,
    PROVIDERS,
    ProviderRegistry,
    VerifiedIdentity,
    callback_base_url,
)


@pytest.fixture(autouse=True)
def no_provider_network(monkeypatch):
    monkeypatch.setattr(
        'requests.sessions.Session.request', MagicMock(side_effect=AssertionError('External OAuth forbidden'))
    )


@pytest.fixture
def identity():
    return VerifiedIdentity('google', PROVIDERS['google'].issuer, 'google-subject', 'person@example.test', 'Person')


@pytest.fixture
def user():
    return CaseInsensitiveRecord(
        CustomerID=4, FullName='Person', AuthVersion=1, Role='customer', DarkModeEnabled=False, Password=None
    )


@pytest.fixture
def registry(app):
    app.config.update(
        PUBLIC_BASE_URL='https://store.example.test',
        OAUTH_GOOGLE_CLIENT_ID='offline-google-client',
        OAUTH_GOOGLE_CLIENT_SECRET='offline-google-secret',
        OAUTH_GITHUB_CLIENT_ID='offline-github-client',
        OAUTH_GITHUB_CLIENT_SECRET='offline-github-secret',
    )
    return ProviderRegistry(app)


@pytest.fixture
def flow():
    return dict(state='s' * 43, binding='b' * 43, nonce='n' * 43, intent='login', issued_at=time.time())


@pytest.fixture(scope='module')
def signing_key():
    return RSAKey.generate_key(2048, {'kid': 'offline-only'})


def install_google_token(registry, signing_key, flow, monkeypatch, claims=None, wrong_key=False):
    client = registry.client('google')
    client.server_metadata.update(
        _loaded_at=time.time(),
        issuer=PROVIDERS['google'].issuer,
        authorization_endpoint='https://accounts.google.com/o/oauth2/v2/auth',
        token_endpoint='https://oauth2.googleapis.com/token',
        id_token_signing_alg_values_supported=['RS256'],
        jwks={'keys': [signing_key.as_dict(private=False)]},
    )
    now = int(time.time())
    values = dict(
        iss=PROVIDERS['google'].issuer,
        sub='google-subject',
        aud='offline-google-client',
        iat=now,
        exp=now + 300,
        nonce=flow['nonce'],
        email='person@example.test',
        email_verified=True,
        name='Person',
        auth_time=now,
    )
    values.update(claims or {})
    key = RSAKey.generate_key(2048, {'kid': 'offline-only'}) if wrong_key else signing_key
    token = {
        'id_token': jwt.encode({'alg': 'RS256', 'kid': 'offline-only'}, values, key),
        'access_token': 'offline-access-token',
        'token_type': 'Bearer',
    }
    fetch = MagicMock(return_value=token)
    monkeypatch.setattr(client, 'fetch_access_token', fetch)
    return client, fetch


@pytest.mark.parametrize(
    'base',
    [
        None,
        '',
        'https://user:secret@store.test',
        'https://store.test/callback',
        'https://store.test?url=x',
        'https://store.test#x',
        '//store.test',
        'http://store.test',
        'javascript:alert(1)',
        'https://store.test:99999',
        'https://store.test:0',
        'https://store.test\\evil',
        'https://store.test\n',
    ],
)
def test_untrusted_callback_bases_disable(base):
    assert callback_base_url(dict(PUBLIC_BASE_URL=base, APP_ENV='production')) is None


@pytest.mark.parametrize(
    'base,expected',
    [
        ('https://store.test/', 'https://store.test'),
        ('https://store.test:444', 'https://store.test:444'),
        ('http://127.0.0.1:8080', 'http://127.0.0.1:8080'),
    ],
)
def test_fixed_callback_bases(base, expected):
    assert callback_base_url(dict(PUBLIC_BASE_URL=base, APP_ENV='testing')) == expected


def test_missing_credentials_disable_without_registering_network(app):
    providers = ProviderRegistry(app)
    assert all(not item['enabled'] for item in providers.choices())
    with pytest.raises(OAuthUnavailable):
        providers.client('google')


def test_partial_credentials_never_enable(app):
    app.config.update(
        PUBLIC_BASE_URL='https://store.test', OAUTH_GOOGLE_CLIENT_ID='offline-client', OAUTH_GOOGLE_CLIENT_SECRET=None
    )
    assert not ProviderRegistry(app).available('google')


def test_callback_url_uses_public_base_not_request_host(app, registry):
    with app.test_request_context('/', base_url='https://attacker.test', headers={'X-Forwarded-Host': 'evil.test'}):
        assert registry.callback_url('google') == 'https://store.example.test/oauth/google/callback'


@pytest.mark.parametrize(
    'provider,issuer',
    [('unknown', PROVIDERS['google'].issuer), ('google', PROVIDERS['github'].issuer)],
)
def test_verified_identity_rejects_unknown_provider_or_wrong_issuer(provider, issuer):
    with pytest.raises(OAuthFailure, match='Nhà cung cấp'):
        VerifiedIdentity(provider, issuer, 'subject', 'person@example.test', 'Person')


def test_pkce_authlib_state_nonce_saved_only_server_side(app, registry, flow, monkeypatch, caplog):
    client = registry.client('google')
    client.server_metadata.update(_loaded_at=time.time(), authorization_endpoint='https://accounts.google.com/auth')
    issue = MagicMock()
    monkeypatch.setattr(OAuthService, 'issue_ticket', issue)
    with caplog.at_level(logging.DEBUG, logger='authlib.integrations.base_client.sync_app'):
        with app.test_request_context('/'):
            destination = registry.authorize('google', flow)
            assert not any(key.startswith('_state_google') for key in session)
    assert 'code_challenge_method=S256' in destination
    assert 'nonce=' + flow['nonce'] in destination
    assert 'prompt=select_account' in destination
    args = issue.call_args.args
    assert args[:3] == (flow['state'], flow['binding'], 'authorization')
    assert args[3]['redirect_uri'] == registry.callback_url('google')
    assert len(args[3]['code_verifier']) >= 43
    assert args[3]['code_verifier'] not in caplog.text


@pytest.mark.parametrize(
    'changed',
    [
        {'iss': 'https://evil.test'},
        {'aud': 'different-client'},
        {'nonce': 'different-nonce'},
        {'nonce': None, 'nonce_supported': False},
        {'exp': 0},
        {'sub': None},
    ],
)
def test_real_authlib_validates_signed_google_claims(app, registry, flow, signing_key, monkeypatch, changed):
    client, fetch = install_google_token(registry, signing_key, flow, monkeypatch, changed)
    data = dict(redirect_uri=registry.callback_url('google'), nonce=flow['nonce'], code_verifier='v' * 48)
    with app.test_request_context('/oauth/google/callback?code=offline-code&state=' + flow['state']):
        with pytest.raises(Exception) as failure:
            registry.exchange('google', flow, data)
        assert not isinstance(failure.value, AssertionError), 'No external request is allowed'
        assert not any(key.startswith('_state_google') for key in session)
        assert client.token is None
    fetch.assert_called_once()


def test_real_authlib_rejects_invalid_signature(app, registry, flow, signing_key, monkeypatch):
    install_google_token(registry, signing_key, flow, monkeypatch, wrong_key=True)
    with app.test_request_context('/oauth/google/callback?code=offline&state=' + flow['state']):
        with pytest.raises(JoseError):
            registry.exchange('google', flow, dict(nonce=flow['nonce'], code_verifier='v' * 48))


def test_valid_signed_google_token_minimal_identity(app, registry, flow, signing_key, monkeypatch):
    client, fetch = install_google_token(registry, signing_key, flow, monkeypatch)
    with app.test_request_context('/oauth/google/callback?code=offline&state=' + flow['state']):
        result = registry.exchange('google', flow, dict(nonce=flow['nonce'], code_verifier='v' * 48))
        assert client.token is None
        assert dict(session) == {}
    assert result.email == 'person@example.test'
    assert result.subject == 'google-subject'
    assert not hasattr(result, 'access_token')
    assert fetch.call_args.kwargs['allow_redirects'] is False


@pytest.mark.parametrize('verified', [False, None, 'true', 1])
def test_google_requires_boolean_verified_email(app, registry, flow, signing_key, monkeypatch, verified):
    install_google_token(registry, signing_key, flow, monkeypatch, {'email_verified': verified})
    with app.test_request_context('/oauth/google/callback?code=offline&state=' + flow['state']):
        with pytest.raises(OAuthFailure):
            registry.exchange('google', flow, dict(nonce=flow['nonce'], code_verifier='v' * 48))


@pytest.mark.parametrize('auth_time', [None, True, 'new', 0, float('nan'), float('inf')])
def test_google_reauth_requires_fresh_auth_time(app, registry, flow, signing_key, monkeypatch, auth_time):
    flow['intent'] = 'reauth'
    install_google_token(registry, signing_key, flow, monkeypatch, {'auth_time': auth_time})
    with app.test_request_context('/oauth/google/callback?code=offline&state=' + flow['state']):
        with pytest.raises(Exception) as failure:
            registry.exchange('google', flow, dict(nonce=flow['nonce'], code_verifier='v' * 48))
        assert not isinstance(failure.value, AssertionError)


def test_google_reauth_accepts_fresh_auth_time(app, registry, flow, signing_key, monkeypatch):
    flow['intent'] = 'reauth'
    auth_time = time.time()
    install_google_token(registry, signing_key, flow, monkeypatch, {'auth_time': auth_time})
    with app.test_request_context('/oauth/google/callback?code=offline&state=' + flow['state']):
        result = registry.exchange('google', flow, dict(nonce=flow['nonce'], code_verifier='v' * 48))
    assert result.subject == 'google-subject'


def test_github_uses_verified_email_endpoint_not_public_profile(app, registry, flow, monkeypatch):
    client = registry.client('github')
    monkeypatch.setattr(
        client, 'fetch_access_token', lambda **kwargs: {'access_token': 'offline-access', 'token_type': 'Bearer'}
    )
    responses = [
        SimpleNamespace(status_code=200, json=lambda: dict(id=123, login='offline', email='unverified@example.test')),
        SimpleNamespace(
            status_code=200, json=lambda: [dict(email='verified@example.test', verified=True, primary=True)]
        ),
    ]
    get = MagicMock(side_effect=responses)
    monkeypatch.setattr(client, 'get', get)
    with app.test_request_context('/oauth/github/callback?code=offline&state=' + flow['state']):
        result = registry.exchange('github', flow, dict(code_verifier='v' * 48))
        assert client.token is None
    assert result.email == 'verified@example.test'
    assert result.subject == '123'
    assert [call.args[0] for call in get.call_args_list] == ['user', 'user/emails']
    assert all(call.kwargs['allow_redirects'] is False for call in get.call_args_list)


def test_github_without_verified_email_denies(app, registry, flow, monkeypatch):
    client = registry.client('github')
    monkeypatch.setattr(
        client, 'fetch_access_token', lambda **kwargs: {'access_token': 'offline', 'token_type': 'Bearer'}
    )
    monkeypatch.setattr(
        client,
        'get',
        MagicMock(
            side_effect=[
                SimpleNamespace(status_code=200, json=lambda: {'id': 123, 'email': 'public@example.test'}),
                SimpleNamespace(status_code=200, json=lambda: [{'email': 'public@example.test', 'verified': False}]),
            ]
        ),
    )
    with app.test_request_context('/oauth/github/callback?code=offline&state=' + flow['state']):
        with pytest.raises(OAuthFailure):
            registry.exchange('github', flow, dict(code_verifier='v' * 48))


@pytest.mark.parametrize(
    'responses',
    [
        [SimpleNamespace(status_code=503, json=lambda: {})],
        [SimpleNamespace(status_code=200, json=lambda: []), SimpleNamespace(status_code=200, json=lambda: [])],
        [
            SimpleNamespace(status_code=200, json=lambda: {'id': 123}),
            SimpleNamespace(status_code=200, json=lambda: {'email': 'person@example.test'}),
        ],
    ],
)
def test_github_rejects_non_200_or_malformed_responses(app, registry, flow, monkeypatch, responses):
    client = registry.client('github')
    monkeypatch.setattr(
        client, 'fetch_access_token', lambda **kwargs: {'access_token': 'offline', 'token_type': 'Bearer'}
    )
    monkeypatch.setattr(client, 'get', MagicMock(side_effect=responses))
    with app.test_request_context('/oauth/github/callback?code=offline&state=' + flow['state']):
        with pytest.raises(OAuthFailure, match='xác minh tài khoản GitHub'):
            registry.exchange('github', flow, dict(code_verifier='v' * 48))


@pytest.mark.parametrize('profile_name', [None, '', ' ', '\x00bad', 'x' * 256])
def test_github_uses_email_local_part_when_profile_name_is_unusable(app, registry, flow, monkeypatch, profile_name):
    client = registry.client('github')
    monkeypatch.setattr(
        client, 'fetch_access_token', lambda **kwargs: {'access_token': 'offline', 'token_type': 'Bearer'}
    )
    monkeypatch.setattr(
        client,
        'get',
        MagicMock(
            side_effect=[
                SimpleNamespace(status_code=200, json=lambda: {'id': 123, 'name': profile_name, 'login': ''}),
                SimpleNamespace(
                    status_code=200,
                    json=lambda: [{'email': 'fallback@example.test', 'verified': True, 'primary': True}],
                ),
            ]
        ),
    )
    with app.test_request_context('/oauth/github/callback?code=offline&state=' + flow['state']):
        result = registry.exchange('github', flow, dict(code_verifier='v' * 48))
    assert result.name == 'fallback'


def test_existing_identity_logs_in_without_email_matching(fake_db, identity, user):
    fake_db.cursor.fetchone.return_value = user
    assert OAuthService.login_or_register(identity) is user
    assert fake_db.cursor.execute.call_count == 1
    assert 'i.issuer = %s' in fake_db.cursor.execute.call_args.args[0]
    fake_db.conn.commit.assert_not_called()


def test_existing_email_never_auto_links(fake_db, identity, user):
    fake_db.cursor.fetchone.side_effect = [None, user]
    with pytest.raises(OAuthAccountConflict, match='mật khẩu'):
        OAuthService.login_or_register(identity)
    assert fake_db.cursor.execute.call_count == 2
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.rollback.assert_called_once()


def test_new_verified_email_creates_null_password_and_identity_atomically(fake_db, identity, user):
    fake_db.cursor.fetchone.side_effect = [None, None, user]
    assert OAuthService.login_or_register(identity) is user
    statements = [call.args[0] for call in fake_db.cursor.execute.call_args_list]
    assert 'NULL, FALSE' in statements[2]
    assert 'INSERT INTO OAuthIdentities' in statements[3]
    assert all('access_token' not in sql and 'refresh_token' not in sql for sql in statements)
    fake_db.conn.commit.assert_called_once()


def test_identity_race_rolls_back_orphan_and_logs_in_exact_winner(fake_db, identity, user):
    fake_db.cursor.fetchone.side_effect = [None, None, user, user]
    fake_db.cursor.execute.side_effect = [None, None, None, psycopg2.IntegrityError('private'), None]
    assert OAuthService.login_or_register(identity) is user
    fake_db.conn.rollback.assert_called_once()
    fake_db.conn.commit.assert_not_called()


def test_email_race_still_never_auto_links(fake_db, identity, user):
    fake_db.cursor.fetchone.side_effect = [None, None, user, None]
    fake_db.cursor.execute.side_effect = [None, None, None, psycopg2.IntegrityError('private'), None]
    with pytest.raises(OAuthAccountConflict):
        OAuthService.login_or_register(identity)
    fake_db.conn.commit.assert_not_called()


def test_link_checks_auth_version_with_customer_row_lock(fake_db, identity, user):
    fake_db.cursor.fetchone.side_effect = [user, None, CaseInsensitiveRecord(AuthVersion=2)]
    assert OAuthService.link_identity(identity, 4, 1) == 2
    assert 'FOR UPDATE' in fake_db.cursor.execute.call_args_list[0].args[0]
    fake_db.conn.commit.assert_called_once()


def test_link_cannot_transfer_another_users_subject(fake_db, identity, user):
    fake_db.cursor.fetchone.side_effect = [user, CaseInsensitiveRecord(CustomerID=99)]
    with pytest.raises(OAuthAccountConflict):
        OAuthService.link_identity(identity, 4, 1)
    assert fake_db.cursor.execute.call_count == 2
    fake_db.conn.commit.assert_not_called()


def test_link_integrity_conflict_rolls_back_and_closes(fake_db, identity, user):
    fake_db.cursor.fetchone.side_effect = [user, None]
    fake_db.cursor.execute.side_effect = [None, None, psycopg2.IntegrityError('duplicate identity')]
    with pytest.raises(OAuthAccountConflict, match='đã được liên kết'):
        OAuthService.link_identity(identity, 4, 1)
    fake_db.conn.rollback.assert_called_once()
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()


@pytest.mark.parametrize('method', ['link_identity', 'unlink_identity', 'reauthenticate_identity'])
def test_stale_auth_version_never_mutates(fake_db, identity, user, method):
    fake_db.cursor.fetchone.return_value = user
    first = 'google' if method == 'unlink_identity' else identity
    with pytest.raises(OAuthFailure):
        getattr(OAuthService, method)(first, 4, 2)
    assert fake_db.cursor.execute.call_count == 1
    fake_db.conn.commit.assert_not_called()


@pytest.mark.parametrize('owner', [None, CaseInsensitiveRecord(CustomerID=99)])
def test_reauthenticate_identity_requires_current_account_owner(fake_db, identity, user, owner):
    fake_db.cursor.fetchone.side_effect = [user, owner]
    with pytest.raises(OAuthFailure, match='tài khoản hiện tại'):
        OAuthService.reauthenticate_identity(identity, 4, 1)
    fake_db.conn.rollback.assert_called_once()
    fake_db.conn.close.assert_called_once()


def test_reauthenticate_identity_accepts_current_account_owner(fake_db, identity, user):
    fake_db.cursor.fetchone.side_effect = [user, CaseInsensitiveRecord(CustomerID=4)]
    assert OAuthService.reauthenticate_identity(identity, 4, 1) is None
    fake_db.conn.rollback.assert_called_once()
    fake_db.conn.close.assert_called_once()


def test_unlink_unknown_provider_fails_without_database(monkeypatch):
    get_connection = MagicMock()
    monkeypatch.setattr(OAuthService, 'get_connection', get_connection)
    with pytest.raises(OAuthFailure, match='không hợp lệ'):
        OAuthService.unlink_identity('unknown', 4, 1)
    get_connection.assert_not_called()


def test_unlink_absent_provider_rolls_back_without_mutating(fake_db, user):
    fake_db.cursor.fetchone.return_value = user
    fake_db.cursor.fetchall.return_value = [CaseInsensitiveRecord(provider='github')]
    with pytest.raises(OAuthFailure, match='chưa được liên kết'):
        OAuthService.unlink_identity('google', 4, 1)
    assert fake_db.cursor.execute.call_count == 2
    fake_db.conn.rollback.assert_called_once()
    fake_db.conn.commit.assert_not_called()


def test_unlink_last_identity_without_password_forbidden(fake_db, user):
    fake_db.cursor.fetchone.return_value = user
    fake_db.cursor.fetchall.return_value = [CaseInsensitiveRecord(provider='google')]
    with pytest.raises(OAuthFailure, match='cuối cùng'):
        OAuthService.unlink_identity('google', 4, 1)
    assert fake_db.cursor.execute.call_count == 2
    fake_db.conn.commit.assert_not_called()


@pytest.mark.parametrize(
    'password,identities', [(generate_password_hash('ExistingPass123!'), ['google']), (None, ['google', 'github'])]
)
def test_unlink_preserves_password_or_remaining_identity(fake_db, user, password, identities):
    user.Password = password
    fake_db.cursor.fetchone.side_effect = [user, CaseInsensitiveRecord(AuthVersion=2)]
    fake_db.cursor.fetchall.return_value = [CaseInsensitiveRecord(provider=name) for name in identities]
    assert OAuthService.unlink_identity('google', 4, 1) == 2
    assert 'FOR UPDATE' in fake_db.cursor.execute.call_args_list[0].args[0]
    fake_db.conn.commit.assert_called_once()


def test_no_password_is_not_password_reauth(fake_db, user):
    fake_db.cursor.fetchone.return_value = user
    assert OAuthService.reauthenticate_password(4, 1, 'Anything123!') is False
    fake_db.conn.commit.assert_not_called()


@pytest.mark.parametrize('password', [None, '', 'x' * 129, 123, object()])
def test_malformed_password_reauth_never_opens_database(monkeypatch, password):
    get_connection = MagicMock()
    monkeypatch.setattr(OAuthService, 'get_connection', get_connection)
    assert OAuthService.reauthenticate_password(4, 1, password) is False
    get_connection.assert_not_called()


def test_list_identities_queries_ordered_user_rows_and_closes(fake_db):
    rows = [
        CaseInsensitiveRecord(provider='github', email='github@example.test'),
        CaseInsensitiveRecord(provider='google', email='google@example.test'),
    ]
    fake_db.cursor.fetchall.return_value = rows
    assert OAuthService.list_identities('4') == rows
    sql, params = fake_db.cursor.execute.call_args.args
    assert 'ORDER BY provider' in sql
    assert params == (4,)
    fake_db.conn.close.assert_called_once()


def test_issue_ticket_insert_failure_rolls_back_closes_and_reraises(app, fake_db):
    failure = psycopg2.OperationalError('insert failed')
    fake_db.cursor.execute.side_effect = [None, failure]
    with app.app_context(), pytest.raises(psycopg2.OperationalError, match='insert failed'):
        OAuthService.issue_ticket('s' * 43, 'b' * 43, 'authorization', {'nonce': 'offline'})
    fake_db.conn.rollback.assert_called_once()
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()


def test_ticket_consumption_deletes_atomically_and_commits_before_return(app, fake_db):
    fake_db.cursor.fetchone.return_value = CaseInsensitiveRecord(AuthData={'nonce': 'offline-nonce'})
    with app.app_context():
        result = OAuthService.consume_ticket('s' * 43, 'b' * 43, 'authorization')
    sql, params = fake_db.cursor.execute.call_args.args
    assert 'DELETE FROM OAuthStates' in sql and 'expires_at > CURRENT_TIMESTAMP' in sql
    assert 'binding_digest = %s' in sql
    assert 's' * 43 not in params and 'b' * 43 not in params
    assert result == {'nonce': 'offline-nonce'}
    fake_db.conn.commit.assert_called_once()


def test_consumed_or_expired_ticket_rejected(app, fake_db):
    fake_db.cursor.fetchone.return_value = None
    with app.app_context(), pytest.raises(OAuthFailure):
        OAuthService.consume_ticket('s' * 43, 'b' * 43, 'authorization')
    fake_db.conn.commit.assert_called_once()
