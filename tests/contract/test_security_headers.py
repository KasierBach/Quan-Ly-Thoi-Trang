"""Offline Flask security contracts; persistence doubles do not prove SQL safety."""

from http.cookies import SimpleCookie
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
from flask import request
import pytest

from app import create_app
from app.config import Config
from app.database import close_db_pool
from app.services.auth_service import AuthService
from app.services.base_service import BaseService
from app.services.chat_service import ChatService
from app.services.main_service import MainService
from tests.contract.test_chat_server import ChatHarness


def csrf_token(browser):
    response = browser.get('/login')
    assert response.status_code == 200
    meta = BeautifulSoup(response.data, 'html.parser').select_one('meta[name="csrf-token"]')
    assert meta is not None
    token = meta.get('content')
    assert isinstance(token, str) and token
    return token


@pytest.fixture(autouse=True)
def forbid_database(monkeypatch):
    monkeypatch.setattr(
        BaseService, 'get_connection', Mock(side_effect=AssertionError('Offline test attempted DB I/O'))
    )


@pytest.mark.parametrize(
    'path,status',
    [
        ('/login', 200),
        ('/health/live', 200),
        ('/api/users/suggested', 401),
        ('/api/not-a-route', 404),
        ('/api/search_autocomplete?q=' + 'x' * 201, 400),
    ],
)
def test_headers_on_pages_and_api_success_or_denial(auth_client, path, status):
    response = (
        auth_client.get(path) if path != '/api/users/suggested' else auth_client.application.test_client().get(path)
    )
    assert response.status_code == status
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['Cache-Control'] == 'no-store'
    policy = response.headers['Content-Security-Policy']
    assert "object-src 'none'" in policy and "frame-ancestors 'none'" in policy
    assert "form-action 'self'" in policy and 'unsafe-eval' not in policy
    assert 'Strict-Transport-Security' not in response.headers


@pytest.mark.parametrize(
    'path,body',
    [
        ('/login', {'data': {'email': 'user@example.test', 'password': 'TestPass123!'}}),
        ('/contact', {'data': {'name': 'Test', 'email': 'user@example.test', 'message': 'Test contact'}}),
        ('/subscribe_newsletter', {'data': {'email': 'user@example.test'}}),
        ('/api/chat/send', {'json': {'content': 'Test', 'conversation_id': 2}}),
    ],
)
def test_real_csrf_blocks_missing_or_tampered_tokens_before_mutation(app, auth_client, monkeypatch, path, body):
    app.config['WTF_CSRF_ENABLED'] = True
    token = csrf_token(auth_client)
    writes = []
    for service, name in [
        (AuthService, 'login_user'),
        (MainService, 'add_contact_message'),
        (MainService, 'subscribe_newsletter'),
        (ChatService, 'send_message'),
    ]:
        write = Mock(side_effect=AssertionError('CSRF denial reached a mutation'))
        monkeypatch.setattr(service, name, write)
        writes.append(write)
    for headers in ({}, {'X-CSRFToken': token + 'tampered'}):
        assert auth_client.post(path, headers=headers, **body).status_code == 400
    for write in writes:
        write.assert_not_called()
    with auth_client.session_transaction() as state:
        assert state['user_id'] == 1


def test_real_csrf_token_is_cookie_bound_and_valid_token_allows_logout(app, auth_client):
    app.config['WTF_CSRF_ENABLED'] = True
    token = csrf_token(auth_client)
    other = app.test_client()
    assert other.post('/logout', headers={'X-CSRFToken': token}).status_code == 400
    assert auth_client.post('/logout', headers={'X-CSRFToken': token}).status_code == 302
    with auth_client.session_transaction() as state:
        assert 'user_id' not in state


@pytest.mark.parametrize('proxy_count', [0, 1])
def test_production_cookie_hsts_and_explicit_proxy_host_trust(app, monkeypatch, proxy_count):
    monkeypatch.setenv('APP_ENV', 'production')
    configuration = dict(app.config)
    configuration.update(
        APP_ENV='production',
        SESSION_COOKIE_SECURE=Config.from_environment()['SESSION_COOKIE_SECURE'],
        PUBLIC_BASE_URL='https://localhost',
        TRUSTED_PROXY_COUNT=proxy_count,
        WTF_CSRF_ENABLED=True,
    )
    production = create_app(configuration)  # Still DB-disabled, mail-suppressed, memory limiter disabled.
    seen = {}

    @production.before_request
    def observe_request():
        seen.update(secure=request.is_secure, host=request.host, address=request.remote_addr)

    try:
        browser = production.test_client()
        response = browser.get('/login', base_url='https://localhost')
        assert response.status_code == 200
        cookie = SimpleCookie(response.headers['Set-Cookie'])[production.config['SESSION_COOKIE_NAME']]
        assert cookie['secure'] and cookie['httponly'] and cookie['samesite'] == 'Lax'
        assert response.headers['Strict-Transport-Security'] == 'max-age=31536000; includeSubDomains'
        forwarded = {'X-Forwarded-Host': 'localhost', 'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '127.0.0.2'}
        assert browser.get('/health/live', headers=forwarded).status_code == 200
        assert seen == {
            'secure': bool(proxy_count),
            'host': 'localhost',
            'address': '127.0.0.2' if proxy_count else '127.0.0.1',
        }
        forwarded['X-Forwarded-Host'] = 'untrusted.example.test'
        assert browser.get('/health/live', headers=forwarded).status_code == (400 if proxy_count else 200)
        assert browser.get('/health/live', headers={'Host': 'untrusted.example.test'}).status_code == 400
    finally:
        production.extensions['chat_socket_handlers'].close()
        close_db_pool(production)


def test_private_upload_download_is_no_store_and_never_public(app, monkeypatch, tmp_path):
    chat = ChatHarness(app, monkeypatch)
    try:
        browser = chat.browser(1)
        uploaded = browser.post(
            '/api/chat/upload', data={'conversation_id': '2', 'file': (BytesIO(b'private'), 'test.txt')}
        )
        assert uploaded.status_code == 200
        url = uploaded.json['file_url']
        with browser.get(url) as response:
            assert response.status_code == 200 and response.data == b'private'
            assert response.headers['Cache-Control'] == 'no-store'
            assert response.headers['Content-Security-Policy'] == "default-src 'none'; sandbox"
            assert response.headers['X-Content-Type-Options'] == 'nosniff'
            assert response.headers['Referrer-Policy'] == 'no-referrer'
            assert 'attachment;' in response.headers['Content-Disposition']
        assert chat.browser().get(url).status_code == 401
        name = next(iter(chat.attachments.values()))['storage_name']
        assert (Path(app.config['UPLOAD_ROOT']) / 'chat' / name).is_file()
        static = tmp_path / 'static'
        legacy = static / 'uploads' / 'chat' / name
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b'private legacy')
        monkeypatch.setattr(app, 'static_folder', str(static))
        for path in (f'/static/uploads/chat/{name}', f'/uploads/chat/{name}'):
            assert browser.get(path).status_code == 404
    finally:
        chat.close()
