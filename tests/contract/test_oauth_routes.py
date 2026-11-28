"""Offline OAuth browser contracts; provider I/O and database access are doubles."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlencode, urlsplit

import psycopg2
import pytest
from authlib.integrations.base_client.errors import OAuthError
from bs4 import BeautifulSoup
from joserfc.errors import InvalidClaimError
from requests.exceptions import Timeout

from app.database import CaseInsensitiveRecord
from app.routes.oauth import FLOW_KEY, REAUTH_KEY
from app.services.auth_service import AuthService
from app.services.oauth_service import (
    OAuthAccountConflict,
    OAuthFailure,
    OAuthService,
    PROVIDERS,
    ProviderRegistry,
    VerifiedIdentity,
)
from app.services.order_service import OrderService


@pytest.fixture(autouse=True)
def no_provider_network(monkeypatch):
    monkeypatch.setattr(
        'requests.sessions.Session.request', MagicMock(side_effect=AssertionError('External OAuth forbidden'))
    )


@pytest.fixture
def oauth(app, monkeypatch):
    app.config.update(
        PUBLIC_BASE_URL='https://store.example.test',
        OAUTH_GOOGLE_CLIENT_ID='offline-client',
        OAUTH_GOOGLE_CLIENT_SECRET='offline-secret',
        OAUTH_GITHUB_CLIENT_ID='offline-github-client',
        OAUTH_GITHUB_CLIENT_SECRET='offline-github-secret',
    )
    registry = ProviderRegistry(app)
    google = registry.client('google')
    google.server_metadata.update(
        _loaded_at=time.time(), authorization_endpoint='https://accounts.google.com/offline/auth'
    )
    app.extensions['oauth_providers'] = registry
    tickets = {}

    def issue(token, binding, purpose, data, ttl=None):
        tickets[(token, binding, purpose)] = dict(data)

    def consume(token, binding, purpose):
        data = tickets.pop((token, binding, purpose), None)
        if data is None:
            raise OAuthFailure('Phiên xác thực không hợp lệ hoặc đã hết hạn.')
        return data

    monkeypatch.setattr(OAuthService, 'issue_ticket', issue)
    monkeypatch.setattr(OAuthService, 'consume_ticket', consume)
    identity = VerifiedIdentity(
        'google', PROVIDERS['google'].issuer, 'offline-subject', 'person@example.test', 'Person'
    )
    exchange = MagicMock(return_value=identity)
    monkeypatch.setattr(registry, 'exchange', exchange)
    user = CaseInsensitiveRecord(CustomerID=4, FullName='Person', Role='customer', AuthVersion=1, DarkModeEnabled=False)
    login = MagicMock(return_value=user)
    link = MagicMock(return_value=2)
    unlink = MagicMock(return_value=2)
    password = MagicMock(return_value=True)
    reauth = MagicMock()
    monkeypatch.setattr(OAuthService, 'login_or_register', login)
    monkeypatch.setattr(OAuthService, 'link_identity', link)
    monkeypatch.setattr(OAuthService, 'unlink_identity', unlink)
    monkeypatch.setattr(OAuthService, 'reauthenticate_password', password)
    monkeypatch.setattr(OAuthService, 'reauthenticate_identity', reauth)
    monkeypatch.setattr(
        OAuthService,
        'list_identities',
        lambda _: [CaseInsensitiveRecord(provider='google', email='person@example.test')],
    )
    return SimpleNamespace(
        registry=registry,
        tickets=tickets,
        exchange=exchange,
        login=login,
        link=link,
        unlink=unlink,
        password=password,
        reauth=reauth,
    )


def signed_in(client):
    with client.session_transaction() as browser_session:
        browser_session.update(user_id=4, auth_version=1, user_name='Person', role='customer', cart=[{'quantity': 2}])


def start(client, intent='login', provider='google', data=None):
    fields = {'auth_version': '1', 'current_password': 'CurrentPass123!'}
    fields.update(data or {})
    response = client.post(f'/oauth/{provider}/{intent}', data=fields)
    assert response.status_code == 302, response.text
    with client.session_transaction() as browser_session:
        flow = dict(browser_session[FLOW_KEY])
    return flow


def finish(client, flow, extra=None):
    args = dict(code='offline-code', state=flow['state'])
    args.update(extra or {})
    args = {key: value for key, value in args.items() if value is not None}
    return client.get(f'/oauth/{flow["provider"]}/callback?' + urlencode(args))


@pytest.mark.parametrize('provider', ['google', 'github'])
@pytest.mark.parametrize(
    'action,method', [('login', 'post'), ('link', 'post'), ('unlink', 'post'), ('reauth', 'post'), ('callback', 'get')]
)
def test_unconfigured_provider_is_explicit_503_no_fake_login(client, provider, action, method):
    response = getattr(client, method)(f'/oauth/{provider}/{action}')
    assert response.status_code == 503
    assert 'chưa được cấu hình' in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
    with client.session_transaction() as browser_session:
        assert 'user_id' not in browser_session and FLOW_KEY not in browser_session


def test_unavailable_login_providers_are_hidden(client):
    response = client.get('/login')
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, 'html.parser')
    assert soup.select_one('#oauth-login-heading') is None
    assert not soup.select('form[action^="/oauth/"]')


@pytest.mark.parametrize('action', ['login', 'link', 'reauth', 'unlink'])
def test_sensitive_oauth_actions_never_get(client, oauth, action):
    assert client.get('/oauth/google/' + action).status_code == 405
    oauth.exchange.assert_not_called()


def test_unknown_provider_rejected(client):
    assert client.post('/oauth/unknown/login').status_code == 400


def test_authorize_uses_exact_public_callback_not_host(client, app, oauth):
    app.config['TRUSTED_HOSTS'] = ['localhost', 'evil.test']
    response = client.post(
        '/oauth/google/login', base_url='http://evil.test', headers={'X-Forwarded-Host': 'attacker.test'}
    )
    assert response.status_code == 302
    args = parse_qs(urlsplit(response.headers['Location']).query)
    assert args['redirect_uri'] == ['https://store.example.test/oauth/google/callback']
    assert args['code_challenge_method'] == ['S256']
    assert 'client_secret' not in args
    with client.session_transaction() as browser_session:
        assert not any(key.startswith('_state_google') for key in browser_session)
        assert 'current_password' not in browser_session


def test_authorize_failure_cleans_browser_flow(client, oauth, monkeypatch):
    authorize = MagicMock(side_effect=OAuthFailure('authorization failed'))
    monkeypatch.setattr(oauth.registry, 'authorize', authorize)
    response = client.post('/oauth/google/login')
    assert response.status_code == 400
    with client.session_transaction() as browser_session:
        assert FLOW_KEY not in browser_session
    assert not oauth.tickets


def test_login_success_rotates_auth_and_preserves_cart(client, oauth):
    with client.session_transaction() as browser_session:
        browser_session['cart'] = [{'product_id': 1, 'quantity': 2}]
        browser_session['old_guest_secret'] = 'old'
    flow = start(client)
    response = finish(client, flow, {'next': 'https://evil.test', 'access_token': 'ignored-token'})
    assert response.status_code == 302 and response.headers['Location'] == '/'
    with client.session_transaction() as browser_session:
        assert browser_session['user_id'] == 4
        assert browser_session['cart'] == [{'product_id': 1, 'quantity': 2}]
        assert 'old_guest_secret' not in browser_session
        assert FLOW_KEY not in browser_session
        assert not any('token' in key or 'nonce' in key for key in browser_session)
    oauth.login.assert_called_once()
    assert 'offline-code' not in response.text and 'ignored-token' not in response.text


@pytest.mark.parametrize('provider', ['google', 'github'])
def test_provider_login_preserves_local_next_without_sending_it_to_provider(client, oauth, provider):
    next_page = '/checkout?buy_now=1&draft=example-signed-draft'
    page = client.get('/login', query_string={'next': next_page})
    soup = BeautifulSoup(page.text, 'html.parser')
    field = soup.select_one(f'form[action="/oauth/{provider}/login"] input[name="next"]')
    assert field['value'] == next_page

    response = client.post(f'/oauth/{provider}/login', data={'next': field['value']})
    assert response.status_code == 302
    assert 'example-signed-draft' not in response.headers['Location']
    with client.session_transaction() as browser_session:
        flow = dict(browser_session[FLOW_KEY])
        assert 'next_page' not in flow
    response = finish(client, flow, {'next': '/wishlist'})
    assert response.status_code == 302
    assert response.headers['Location'] == next_page
    assert 'next_page' not in oauth.exchange.call_args.args[2]


def test_provider_login_ignores_external_next_from_login_form(client, oauth):
    flow = start(client, data={'next': 'https://example.com/'})
    assert finish(client, flow).headers['Location'] == '/'


def test_logged_in_user_cannot_implicitly_link_via_login(client, oauth):
    signed_in(client)
    assert client.post('/oauth/google/login').status_code == 400
    oauth.login.assert_not_called()
    oauth.link.assert_not_called()


def test_bad_state_never_exchange_and_consumes_local_flow(client, oauth):
    flow = start(client)
    response = finish(client, flow, {'state': 'evil-state'})
    assert response.status_code == 400 and 'evil-state' not in response.text
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    oauth.exchange.assert_not_called()
    with client.session_transaction() as browser_session:
        assert FLOW_KEY not in browser_session


def test_cross_browser_callback_without_flow_rejected(client, app, oauth):
    flow = start(client)
    other = app.test_client()
    assert finish(other, flow).status_code == 400
    oauth.exchange.assert_not_called()
    assert finish(client, flow).status_code == 302


def test_old_signed_cookie_snapshot_cannot_replay_consumed_state(client, oauth):
    flow = start(client)
    snapshot = client.get_cookie('session').value
    assert finish(client, flow).status_code == 302
    client.set_cookie('session', snapshot)
    assert finish(client, flow).status_code == 400
    assert oauth.exchange.call_count == 1
    assert oauth.login.call_count == 1


@pytest.mark.parametrize('change', [{'user_id': 5}, {'auth_version': 2}, {'csrf_token': 'rotated'}, {'user_id': None}])
def test_link_callback_requires_same_user_auth_version_csrf(client, oauth, change):
    signed_in(client)
    flow = start(client, 'link')
    with client.session_transaction() as browser_session:
        browser_session.update(change)
    assert finish(client, flow).status_code == 400
    oauth.exchange.assert_not_called()
    oauth.link.assert_not_called()


def test_login_callback_after_password_login_cannot_switch_accounts(client, oauth):
    flow = start(client)
    signed_in(client)
    assert finish(client, flow).status_code == 400
    oauth.exchange.assert_not_called()


def test_state_is_provider_specific(client, oauth):
    flow = start(client)
    assert (
        client.get('/oauth/github/callback?' + urlencode({'code': 'offline', 'state': flow['state']})).status_code
        == 400
    )
    oauth.exchange.assert_not_called()


@pytest.mark.parametrize(
    'query',
    [dict(error='access_denied', error_description='<script>token-secret</script>'), dict(code=''), dict(code=None)],
)
def test_provider_denial_or_missing_code_is_safe_400(client, oauth, query):
    flow = start(client)
    response = finish(client, flow, query)
    assert response.status_code == 400
    assert 'token-secret' not in response.text
    oauth.exchange.assert_not_called()


def test_duplicate_callback_parameters_rejected(client, oauth):
    flow = start(client)
    response = client.get(
        '/oauth/google/callback?' + urlencode({'code': 'offline', 'state': flow['state']}) + '&state=extra'
    )
    assert response.status_code == 400
    oauth.exchange.assert_not_called()


def test_expired_flow_denied_without_exchange(client, oauth):
    flow = start(client)
    with client.session_transaction() as browser_session:
        value = dict(browser_session[FLOW_KEY])
        value['issued_at'] = 0
        browser_session[FLOW_KEY] = value
    assert finish(client, flow).status_code == 400
    oauth.exchange.assert_not_called()


@pytest.mark.parametrize(
    'error',
    [
        OAuthError(error='bad', description='client-secret-private'),
        InvalidClaimError('private-token'),
        Timeout('private-request-url'),
        psycopg2.OperationalError('password=private'),
        ValueError('private-json'),
    ],
)
def test_upstream_failures_no_secret_leak_and_no_replay(client, oauth, error, caplog):
    oauth.exchange.side_effect = error
    flow = start(client)
    snapshot = client.get_cookie('session').value
    response = finish(client, flow)
    assert response.status_code == 400
    assert 'private' not in response.text and 'private' not in caplog.text
    client.set_cookie('session', snapshot)
    assert finish(client, flow).status_code == 400
    assert oauth.exchange.call_count == 1
    oauth.login.assert_not_called()


def test_verified_existing_email_conflict_requires_password_not_auto_link(client, oauth):
    oauth.login.side_effect = OAuthAccountConflict('Email đã có tài khoản. Hãy đăng nhập bằng mật khẩu rồi liên kết.')
    flow = start(client)
    response = finish(client, flow)
    assert response.status_code == 400 and 'mật khẩu' in response.text
    oauth.link.assert_not_called()
    with client.session_transaction() as browser_session:
        assert 'user_id' not in browser_session


@pytest.mark.parametrize('action', ['link', 'unlink', 'reauth'])
def test_account_actions_require_authenticated_explicit_intent(client, oauth, action):
    assert client.post('/oauth/google/' + action, data={'auth_version': '1'}).status_code == 400
    oauth.password.assert_not_called()
    oauth.unlink.assert_not_called()


@pytest.mark.parametrize('action', ['link', 'unlink', 'reauth'])
def test_stale_form_version_denied_before_reauth(client, oauth, action):
    signed_in(client)
    assert client.post('/oauth/google/' + action, data={'auth_version': '9'}).status_code == 400
    oauth.password.assert_not_called()


@pytest.mark.parametrize('action', ['link', 'unlink'])
def test_wrong_password_never_changes_identity(client, oauth, action):
    signed_in(client)
    oauth.password.return_value = False
    assert (
        client.post('/oauth/google/' + action, data={'auth_version': '1', 'current_password': 'wrong'}).status_code
        == 400
    )
    oauth.link.assert_not_called()
    oauth.unlink.assert_not_called()
    oauth.exchange.assert_not_called()


def test_explicit_link_success_preserves_current_account_and_cart(client, oauth):
    signed_in(client)
    flow = start(client, 'link')
    assert flow['intent'] == 'link' and flow['user_id'] == 4 and flow['auth_version'] == 1
    assert finish(client, flow).status_code == 302
    oauth.link.assert_called_once_with(oauth.exchange.return_value, 4, 1)
    oauth.login.assert_not_called()
    with client.session_transaction() as browser_session:
        assert browser_session['user_id'] == 4 and browser_session['auth_version'] == 2
        assert browser_session['cart'] == [{'quantity': 2}]
        assert 'CurrentPass123!' not in str(dict(browser_session))


def test_unlink_requires_reauth_and_increments_current_version(client, oauth):
    signed_in(client)
    response = client.post('/oauth/google/unlink', data={'auth_version': '1', 'current_password': 'CurrentPass123!'})
    assert response.status_code == 302
    oauth.unlink.assert_called_once_with('google', 4, 1)
    with client.session_transaction() as browser_session:
        assert browser_session['auth_version'] == 2
        assert browser_session['cart'] == [{'quantity': 2}]


def test_last_identity_unlink_failure_is_user_friendly(client, oauth):
    signed_in(client)
    oauth.unlink.side_effect = OAuthFailure('Không thể gỡ cách đăng nhập cuối cùng.')
    response = client.post('/oauth/google/unlink', data={'auth_version': '1', 'current_password': 'CurrentPass123!'})
    assert response.status_code == 400 and 'cuối cùng' in response.text
    with client.session_transaction() as browser_session:
        assert browser_session['auth_version'] == 1


def test_github_reauth_not_claimed_fresh(client, oauth):
    signed_in(client)
    response = client.post('/oauth/github/reauth', data={'auth_version': '1'})
    assert response.status_code == 400
    assert not oauth.tickets


def test_google_reauth_grant_one_use_and_followup_explicit_form(client, oauth):
    signed_in(client)
    flow = start(client, 'reauth')
    assert finish(client, flow).status_code == 302
    oauth.reauth.assert_called_once_with(oauth.exchange.return_value, 4, 1)
    oauth.login.assert_not_called()
    with client.session_transaction() as browser_session:
        assert REAUTH_KEY in browser_session
    oauth.password.return_value = False
    snapshot = client.get_cookie('session').value
    assert client.post('/oauth/github/link', data={'auth_version': '1'}).status_code == 302
    client.set_cookie('session', snapshot)
    assert client.post('/oauth/github/link', data={'auth_version': '1'}).status_code == 400
    assert oauth.password.call_count == 0


def test_reauth_ticket_tuple_mismatch_is_consumed_and_rejected(client, oauth):
    signed_in(client)
    flow = start(client, 'reauth')
    assert finish(client, flow).status_code == 302
    with client.session_transaction() as browser_session:
        grant = dict(browser_session[REAUTH_KEY])
    key = (grant['token'], grant['binding'], 'reauth')
    oauth.tickets[key]['auth_version'] = 2
    response = client.post('/oauth/github/link', data={'auth_version': '1'})
    assert response.status_code == 400
    assert key not in oauth.tickets
    oauth.password.assert_not_called()
    with client.session_transaction() as browser_session:
        assert REAUTH_KEY not in browser_session


def test_google_reauth_wrong_existing_identity_cannot_grant(client, oauth):
    signed_in(client)
    oauth.reauth.side_effect = OAuthFailure('Google không thuộc tài khoản hiện tại.')
    flow = start(client, 'reauth')
    assert finish(client, flow).status_code == 400
    with client.session_transaction() as browser_session:
        assert REAUTH_KEY not in browser_session


def test_account_partial_scoped_and_password_form_preserved(client, oauth, monkeypatch):
    signed_in(client)
    monkeypatch.setattr(
        AuthService,
        'get_customer_profile',
        lambda _: CaseInsensitiveRecord(
            CustomerID=4,
            FullName='Person',
            Email='person@example.test',
            AvatarUrl=None,
            PhoneNumber=None,
            DateOfBirth=None,
            Gender=None,
            CreatedAt=None,
            Address=None,
            DarkModeEnabled=False,
        ),
    )
    monkeypatch.setattr(
        OrderService, 'get_customer_orders', lambda *_: {'orders': [], 'total_orders': 0, 'total_spent': 0}
    )
    response = client.get('/my_account')
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, 'html.parser')
    assert soup.select_one('#passwordForm')
    assert soup.select_one('#oauth-identities form[action="/oauth/google/unlink"]')
    assert soup.select_one('#oauth-identities form[action="/oauth/github/link"]')
    assert len(soup.select('#oauth-identities input[name="auth_version"]')) == 3


@pytest.mark.parametrize('action', ['login', 'link', 'unlink', 'reauth'])
def test_real_csrf_protects_oauth_form_post(client, app, oauth, action):
    app.config['WTF_CSRF_ENABLED'] = True
    signed_in(client)
    response = client.post('/oauth/google/' + action, data={'auth_version': '1', 'current_password': 'CurrentPass123!'})
    assert response.status_code == 400
    oauth.password.assert_not_called()
    oauth.exchange.assert_not_called()
    oauth.unlink.assert_not_called()


def test_csrf_form_token_allows_offline_authorization(client, app, oauth):
    app.config['WTF_CSRF_ENABLED'] = True
    html = client.get('/login').text
    token = BeautifulSoup(html, 'html.parser').select_one(
        'form[action="/oauth/google/login"] input[name="csrf_token"]'
    )['value']
    assert client.post('/oauth/google/login', data={'csrf_token': token}).status_code == 302
