"""No-DB contracts for factory wiring and unchanged private/header behavior."""

import gzip
from unittest.mock import Mock

import pytest
from flask import Response, jsonify, render_template_string, stream_with_context
from flask_wtf.csrf import generate_csrf

from app.services.auth_service import AuthService


TEXT_BODY = b'body { color: #135790; background: white; }\n' * 80


@pytest.fixture
def offline_assets(app, monkeypatch, tmp_path):
    def database_forbidden(*args, **kwargs):
        raise AssertionError('HTTP asset contracts must not connect to a database')

    monkeypatch.setattr('psycopg2.connect', database_forbidden)
    monkeypatch.setattr('app.database.ThreadedConnectionPool', database_forbidden)
    monkeypatch.setattr('app.services.base_service.BaseService.get_connection', database_forbidden)
    static = tmp_path / 'static'
    for name in ('css/site.css', 'js/site.js', 'images/logo.svg', 'uploads/chat/private.js'):
        path = static / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(TEXT_BODY)
    app.static_folder = str(static)
    return app


def test_factory_public_assets_keep_security_headers(offline_assets):
    client = offline_assets.test_client()
    with client.get('/static/css/site.css', headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
        assert response.status_code == 200
        assert response.headers['Content-Encoding'] == 'gzip'
        assert gzip.decompress(response.data) == TEXT_BODY
        assert response.headers['Cache-Control'] == 'public, max-age=300, must-revalidate'
        assert response.headers['X-Frame-Options'] == 'DENY'
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['Referrer-Policy'] == 'same-origin'
        assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
        assert response.headers['Permissions-Policy'] == 'camera=(self), microphone=(self), display-capture=(self)'
        assert not response.headers.getlist('Set-Cookie')
        etag = response.headers['ETag']
    with client.get(
        '/static/css/site.css', headers={'Accept-Encoding': 'gzip', 'If-None-Match': etag}, buffered=True
    ) as response:
        assert response.status_code == 304
        assert response.data == b''
        assert response.headers['ETag'] == etag
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert 'Accept-Encoding' in response.headers['Vary']


def test_factory_existing_before_and_after_hooks_are_preserved(offline_assets):
    before = {callback.__name__ for callback in offline_assets.before_request_funcs[None]}
    after = [callback.__name__ for callback in offline_assets.after_request_funcs[None]]
    assert {'csrf_protect', 'block_public_chat_uploads', 'revalidate_session', 'initialize_page_chat'} <= before
    assert 'add_security_headers' in after
    assert after.index('_prepare_asset_response') < after.index('add_security_headers')
    assert offline_assets.config['SEND_FILE_MAX_AGE_DEFAULT'] is None
    assert offline_assets.config['SESSION_REVALIDATION_ENABLED'] is False  # Explicit offline test config, not changed.
    assert offline_assets.config['TRUSTED_HOSTS'] == ['localhost', '127.0.0.1']


def test_factory_chat_upload_guard_still_blocks_even_textual_files(offline_assets):
    with offline_assets.test_client().get(
        '/static/uploads/chat/private.js', headers={'Accept-Encoding': 'gzip'}, buffered=True
    ) as response:
        assert response.status_code == 404
        assert 'Content-Encoding' not in response.headers
        assert not response.cache_control.public


def test_factory_cookie_assets_never_revalidate_auth_or_change_cookie(offline_assets, monkeypatch):
    offline_assets.config['SESSION_REVALIDATION_ENABLED'] = True
    identity = Mock(side_effect=AssertionError('Static asset requests must not revalidate against a DB'))
    monkeypatch.setattr(AuthService, 'get_identity_state', identity)
    client = offline_assets.test_client()
    with client.session_transaction() as state:
        state.update(user_id=17, auth_version=3, cart=[{'variant_id': 1, 'quantity': 2}])
    with client.get('/static/js/site.js', headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'public, max-age=300, must-revalidate'
        assert gzip.decompress(response.data) == TEXT_BODY
        assert response.headers['Content-Encoding'] == 'gzip'
        assert not response.headers.getlist('Set-Cookie')
    identity.assert_not_called()
    with client.session_transaction() as state:
        assert state['cart'] == [{'variant_id': 1, 'quantity': 2}]
        assert state['auth_version'] == 3


def test_factory_private_json_and_text_keep_no_store_identity(offline_assets):
    @offline_assets.route('/api/asset-contract-private')
    def private_json():
        return jsonify(success=True, auth_token='synthetic-only', padding='private' * 400)

    @offline_assets.route('/api/asset-contract-private-text')
    def private_text():
        return Response(TEXT_BODY, mimetype='text/css')

    client = offline_assets.test_client()
    for path in ('/api/asset-contract-private', '/api/asset-contract-private-text'):
        with client.get(path, headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
            assert response.status_code == 200
            assert response.headers['Cache-Control'] == 'no-store'
            assert 'Content-Encoding' not in response.headers
            assert 'Accept-Encoding' not in response.headers.get('Vary', '')
    with client.get('/api/asset-contract-private', buffered=True) as response:
        assert response.json['auth_token'] == 'synthetic-only'


def test_factory_html_with_csrf_and_post_csrf_protection_are_unchanged(offline_assets):
    offline_assets.config['WTF_CSRF_ENABLED'] = True

    @offline_assets.route('/asset-contract-form', methods=['GET', 'POST'])
    def csrf_form():
        return render_template_string('<input name="csrf_token" value="{{ csrf_token() }}">' + 'form-body' * 400)

    client = offline_assets.test_client()
    with client.get('/asset-contract-form', headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
        assert response.status_code == 200
        assert b'csrf_token' in response.data
        assert 'Content-Encoding' not in response.headers
        assert not response.cache_control.public
        assert response.headers.getlist('Set-Cookie')
    with client.post('/asset-contract-form', headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
        assert response.status_code == 400
        assert 'Content-Encoding' not in response.headers
        assert not response.cache_control.public


def test_csrf_session_write_on_crawler_is_detected_before_cookie_save(offline_assets):
    # A future hook accidentally issuing a CSRF token must not make a crawler
    # response cacheable/compressed; Flask saves the cookie after after_request.
    endpoint = 'main.robots_txt'
    if endpoint not in offline_assets.view_functions:
        offline_assets.add_url_rule('/robots.txt', endpoint=endpoint, view_func=lambda: '')

    def token_crawler():
        return Response(generate_csrf() + 'robots' * 400, mimetype='text/plain')

    offline_assets.view_functions[endpoint] = token_crawler
    with offline_assets.test_client().get(
        '/robots.txt', headers={'Accept-Encoding': 'gzip'}, buffered=True
    ) as response:
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-store'
        assert 'Content-Encoding' not in response.headers
        assert response.headers.getlist('Set-Cookie')


def test_actual_guest_credentials_keep_existing_private_header_hook(offline_assets):
    with offline_assets.test_client().post(
        '/api/chat/guest-session', headers={'Accept-Encoding': 'gzip'}, buffered=True
    ) as response:
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-store'
        assert isinstance(response.json['auth_token'], str) and response.json['auth_token']
        assert response.json['expires_in'] > 0
        assert 'Content-Encoding' not in response.headers


def test_streams_keep_iterator_and_private_headers(offline_assets):
    @offline_assets.route('/api/asset-contract-stream')
    def chat_stream():
        @stream_with_context
        def chunks():
            yield 'data: synthetic-stream\n\n'
            yield 'data: private\n\n'

        return Response(chunks(), mimetype='text/event-stream')

    with offline_assets.test_client().get(
        '/api/asset-contract-stream', headers={'Accept-Encoding': 'gzip'}, buffered=True
    ) as response:
        assert response.data == b'data: synthetic-stream\n\ndata: private\n\n'
        assert response.headers['Cache-Control'] == 'no-store'
        assert 'Content-Encoding' not in response.headers
        assert 'Accept-Encoding' not in response.headers.get('Vary', '')


@pytest.mark.parametrize(
    'endpoint, path, mime',
    [
        ('main.robots_txt', '/robots.txt', 'text/plain'),
        ('main.sitemap_xml', '/sitemap.xml', 'application/xml'),
    ],
)
def test_crawlers_skip_session_db_and_page_chat_but_keep_private_cookies(
    offline_assets, monkeypatch, endpoint, path, mime
):
    if endpoint not in offline_assets.view_functions:
        offline_assets.add_url_rule(path, endpoint=endpoint, view_func=lambda: '')
    offline_assets.view_functions[endpoint] = lambda: Response(TEXT_BODY, mimetype=mime)
    offline_assets.config['SESSION_REVALIDATION_ENABLED'] = True
    identity = Mock(side_effect=AssertionError('Crawler session revalidation must be DB-free'))
    issue_chat = Mock(side_effect=AssertionError('Crawlers must not issue page chat credentials'))
    monkeypatch.setattr(AuthService, 'get_identity_state', identity)
    monkeypatch.setattr('app.services.conversation_service.issue_guest_credentials', issue_chat)
    client = offline_assets.test_client()
    with client.session_transaction() as state:
        state.update(user_id=17, auth_version=3)
    with client.get(path, headers={'Accept-Encoding': 'gzip'}, buffered=True) as private:
        assert private.status_code == 200
        assert private.headers['Cache-Control'] == 'no-store'
        assert 'Content-Encoding' not in private.headers
        assert not private.headers.getlist('Set-Cookie')
    with offline_assets.test_client().get(path, headers={'Accept-Encoding': 'gzip'}, buffered=True) as public:
        assert public.status_code == 200
        assert gzip.decompress(public.data) == TEXT_BODY
        assert public.headers['Cache-Control'] == 'public, max-age=300, must-revalidate'
    identity.assert_not_called()
    issue_chat.assert_not_called()
