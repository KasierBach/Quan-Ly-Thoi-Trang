"""Offline tests for the deliberately narrow HTTP asset policy."""

import gzip
import io
import random
from datetime import datetime, timezone

import pytest
from flask import Flask, Response, request, session
from werkzeug.http import parse_set_header
from werkzeug.wsgi import FileWrapper

from app.http_assets import _accepts_gzip, _prepare_asset_response, init_http_assets


BODY = b'body { color: #123456; background: white; }\n' * 80


@pytest.fixture
def asset_app(tmp_path):
    static = tmp_path / 'static'
    files = {
        'css/site.css': BODY,
        'js/site.js': b'const greeting = "hello";\n' * 100,
        'js/module.mjs': b'export const greeting = "hello";\n' * 100,
        'images/logo.svg': b'<svg><path d="M0 0 L10 10"/></svg>\n' * 100,
        'css/tiny.css': b'body { color: red; }',
        'js/large.js': b'x' * (1024 * 1024 + 1),
        'css/random.css': bytes(range(256)) * 3,
        'images/logo.png': b'\x89PNG\r\n' * 100,
        'fonts/site.woff2': b'woff2' * 200,
        'page.html': b'<input name="csrf_token" value="secret">' * 100,
        'data.json': b'{"auth_token": "secret"}' * 100,
        'uploads/site.css': BODY,
        'uploads/chat/site.js': BODY,
    }
    for name, content in files.items():
        target = static / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    application = Flask(__name__, static_folder=str(static), static_url_path='/static')
    application.config.update(
        SECRET_KEY='offline-asset-tests-only-not-a-deployed-key', SESSION_REFRESH_EACH_REQUEST=False
    )
    init_http_assets(application)
    return application


def vary_values(response):
    return {value.lower() for value in parse_set_header(', '.join(response.headers.getlist('Vary')))}


@pytest.mark.parametrize(
    'header, accepted',
    [
        ('', False),
        ('gzip', True),
        ('GZip', True),
        ('br, gzip', True),
        ('xgzip', False),
        ('gzip;q=0', False),
        ('gzip; q=0.000', False),
        ('gzip;q=.5', True),
        ('gzip; q = 0.5', True),
        ('gzip;q=1.000', True),
        ('br;q=1, gzip;q=.5', True),
        ('*', True),
        ('*;q=.5', True),
        ('*;q=0', False),
        ('gzip;q=0, *;q=1', False),
        ('gzip;q=.5, *;q=0', True),
        ('gzip;q=.5, identity;q=1', False),
        ('gzip;q=.5, identity;q=.5', True),
        ('gzip, identity;q=0', True),
        ('gzip;q=0, identity;q=0', False),
        ('gzip;q=bad', False),
        ('gzip;q=NaN', False),
        ('gzip;q=inf', False),
        ('gzip;q=-1', False),
        ('gzip;q=1.1', False),
        ('gzip;q=0.1234', False),
        ('gzip;level=1', False),
        ('gzip;q=.5;other=1', False),
        ('gzip;q=0;q=1', False),
        ('gzip;q=0, gzip;q=1', False),
        ('gzip;q=1, gzip;q=0', False),
        ('gzip;q=bad, *;q=1', False),
    ],
)
def test_accept_encoding_parsing(header, accepted):
    assert _accepts_gzip(header) is accepted


@pytest.mark.parametrize('path', ['css/site.css', 'js/site.js', 'images/logo.svg'])
def test_public_textual_assets_are_cached_and_actually_gzipped(asset_app, path):
    client = asset_app.test_client()
    with client.get(f'/static/{path}', buffered=True) as identity:
        raw = identity.data
        identity_etag = identity.headers['ETag']
        assert identity.status_code == 200
        assert identity.headers['Cache-Control'] == 'public, max-age=300, must-revalidate'
        assert 'Content-Encoding' not in identity.headers
        assert identity_etag.startswith('"')  # Flask's automatic file validator remains intact.
    with client.get(f'/static/{path}', headers={'Accept-Encoding': 'gzip'}, buffered=True) as encoded:
        assert encoded.status_code == 200
        assert encoded.headers['Content-Encoding'] == 'gzip'
        assert gzip.decompress(encoded.data) == raw
        assert len(encoded.data) < len(raw)
        assert int(encoded.headers['Content-Length']) == len(encoded.data)
        assert encoded.headers['ETag'] == 'W/' + identity_etag
        assert 'Last-Modified' in encoded.headers
        assert 'accept-encoding' in vary_values(encoded)
        assert 'immutable' not in encoded.headers['Cache-Control']
        assert encoded.data[4:8] == b'\0\0\0\0'  # Deterministic gzip mtime.
    with client.get(f'/static/{path}', headers={'Accept-Encoding': 'gzip'}, buffered=True) as repeated:
        assert repeated.data == encoded.data


@pytest.mark.parametrize('accept_encoding', ['', 'gzip', 'gzip;q=0', '*;q=.5'])
def test_static_head_matches_get_representation(asset_app, accept_encoding):
    client = asset_app.test_client()
    headers = {'Accept-Encoding': accept_encoding}
    with client.get('/static/css/site.css', headers=headers, buffered=True) as get_response:
        with client.head('/static/css/site.css', headers=headers, buffered=True) as head_response:
            assert head_response.data == b''
            assert head_response.status_code == get_response.status_code == 200
            for name in ('Content-Encoding', 'Content-Length', 'ETag', 'Last-Modified', 'Cache-Control', 'Vary'):
                assert head_response.headers.get(name) == get_response.headers.get(name)


@pytest.mark.parametrize('accept_encoding', ['', 'gzip'])
def test_automatic_etag_and_last_modified_conditional_304(asset_app, accept_encoding):
    client = asset_app.test_client()
    headers = {'Accept-Encoding': accept_encoding}
    with client.get('/static/css/site.css', headers=headers, buffered=True) as original:
        for conditional in ('If-None-Match', 'If-Modified-Since'):
            value = original.headers['ETag' if conditional == 'If-None-Match' else 'Last-Modified']
            for method in ('get', 'head'):
                with getattr(client, method)(
                    '/static/css/site.css', headers={**headers, conditional: value}, buffered=True
                ) as response:
                    assert response.status_code == 304
                    assert response.data == b''
                    assert response.headers['ETag'] == original.headers['ETag']
                    assert response.headers['Cache-Control'] == 'public, max-age=300, must-revalidate'
                    assert 'accept-encoding' in vary_values(response)
                    assert 'Content-Encoding' not in response.headers
                    assert 'Content-Length' not in response.headers


def test_weak_etag_is_valid_across_negotiation_without_strong_byte_collision(asset_app):
    client = asset_app.test_client()
    with client.get('/static/css/site.css', headers={'Accept-Encoding': 'gzip'}, buffered=True) as compressed:
        gzip_etag = compressed.headers['ETag']
    with client.get('/static/css/site.css', headers={'If-None-Match': gzip_etag}, buffered=True) as identity:
        assert identity.status_code == 304
        assert not identity.headers['ETag'].startswith('W/')
        assert 'Content-Encoding' not in identity.headers
    with client.get(
        '/static/css/site.css', headers={'Accept-Encoding': 'gzip', 'If-None-Match': '"old-file"'}, buffered=True
    ) as changed:
        assert changed.status_code == 200
        assert gzip.decompress(changed.data) == BODY


@pytest.mark.parametrize('accept_encoding', ['gzip;q=0', 'gzip;q=0, *;q=1', 'br', 'gzip;q=NaN'])
def test_encoding_refusal_stays_identity_but_varies(asset_app, accept_encoding):
    with asset_app.test_client().get(
        '/static/css/site.css', headers={'Accept-Encoding': accept_encoding}, buffered=True
    ) as response:
        assert response.data == BODY
        assert 'Content-Encoding' not in response.headers
        assert 'accept-encoding' in vary_values(response)


@pytest.mark.parametrize('path', ['css/tiny.css', 'js/large.js'])
def test_size_limits_keep_identity_without_losing_revalidation(asset_app, path):
    with asset_app.test_client().get(f'/static/{path}', headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
        assert response.status_code == 200
        assert 'Content-Encoding' not in response.headers
        assert response.headers['Cache-Control'] == 'public, max-age=300, must-revalidate'
        assert not response.headers['ETag'].startswith('W/')


@pytest.mark.parametrize('path', ['images/logo.png', 'fonts/site.woff2', 'page.html', 'data.json', 'uploads/site.css'])
def test_binary_html_json_and_uploads_are_outside_policy(asset_app, path):
    with asset_app.test_client().get(f'/static/{path}', headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
        assert response.status_code == 200
        assert 'Content-Encoding' not in response.headers
        assert response.headers['Cache-Control'] == 'no-cache'
        assert 'accept-encoding' not in vary_values(response)


def test_ranges_and_strong_preconditions_are_not_reencoded(asset_app):
    client = asset_app.test_client()
    with client.get(
        '/static/css/site.css', headers={'Accept-Encoding': 'gzip', 'Range': 'bytes=0-19'}, buffered=True
    ) as response:
        assert response.status_code == 206
        assert response.data == BODY[:20]
        assert response.headers['Content-Range'] == f'bytes 0-19/{len(BODY)}'
        assert 'Content-Encoding' not in response.headers
    with client.get('/static/css/site.css', buffered=True) as identity:
        etag = identity.headers['ETag']
    with client.get(
        '/static/css/site.css', headers={'Accept-Encoding': 'gzip', 'If-Match': etag}, buffered=True
    ) as response:
        assert response.status_code == 200
        assert response.data == BODY
        assert response.headers['ETag'] == etag
        assert 'Content-Encoding' not in response.headers


@pytest.mark.parametrize('cache_control', ['no-store', 'private, max-age=17', 'public, no-transform'])
def test_later_private_hooks_have_priority(asset_app, cache_control):
    @asset_app.after_request
    def private_policy(response):
        response.headers['Cache-Control'] = cache_control
        return response

    with asset_app.test_client().get(
        '/static/css/site.css', headers={'Accept-Encoding': 'gzip'}, buffered=True
    ) as response:
        assert response.headers['Cache-Control'] == cache_control
        assert response.data == BODY
        assert 'Content-Encoding' not in response.headers
        assert 'accept-encoding' not in vary_values(response)


@pytest.mark.parametrize(
    'headers, query',
    [
        ({'Authorization': 'Bearer synthetic-test-token'}, ''),
        ({'X-Chat-Token': 'synthetic-test-token'}, ''),
        ({'X-CSRFToken': 'synthetic-test-token'}, ''),
        ({'X-CSRF-Token': 'synthetic-test-token'}, ''),
        ({}, '?auth_token=synthetic-test-token'),
        ({}, '?version=untrusted'),
    ],
)
def test_credential_bearing_asset_requests_are_not_cached_or_compressed(asset_app, headers, query):
    with asset_app.test_client(use_cookies=False).get(
        '/static/css/site.css' + query, headers={'Accept-Encoding': 'gzip', **headers}, buffered=True
    ) as response:
        assert response.data == BODY
        assert response.headers['Cache-Control'] == 'no-store'
        assert 'Content-Encoding' not in response.headers
        assert 'Expires' not in response.headers


@pytest.mark.parametrize('pending_session', [False, True])
def test_set_cookie_and_pending_session_write_are_vetoed(asset_app, pending_session):
    @asset_app.after_request
    def write_cookie(response):
        if pending_session:
            session['csrf_token'] = 'synthetic-csrf-token'
        else:
            response.set_cookie('credential', 'synthetic-token')
        return response

    with asset_app.test_client().get(
        '/static/css/site.css', headers={'Accept-Encoding': 'gzip'}, buffered=True
    ) as response:
        assert response.headers['Cache-Control'] == 'no-store'
        assert 'Content-Encoding' not in response.headers
        assert response.headers.getlist('Set-Cookie')
        assert response.data == BODY


def test_authenticated_static_asset_is_public_without_cookie_rewrite(asset_app):
    client = asset_app.test_client()
    with client.session_transaction() as state:
        state['user_id'] = 17
    with client.get('/static/css/site.css', headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
        assert response.headers['Cache-Control'] == 'public, max-age=300, must-revalidate'
        assert gzip.decompress(response.data) == BODY
        assert response.headers['Content-Encoding'] == 'gzip'
        assert not response.headers.getlist('Set-Cookie')


@pytest.mark.parametrize('vary_headers', [['Origin', 'Cookie'], ['origin, ACCEPT-ENCODING', 'Cookie'], ['*']])
def test_vary_merges_all_lines_and_preserves_existing_tokens(asset_app, vary_headers):
    @asset_app.after_request
    def vary_policy(response):
        for value in vary_headers:
            response.headers.add('Vary', value)
        return response

    with asset_app.test_client().get(
        '/static/css/site.css', headers={'Accept-Encoding': 'gzip'}, buffered=True
    ) as response:
        values = vary_values(response)
        if vary_headers == ['*']:
            # Flask may add Cookie after all after_request hooks; keep wildcard
            # semantics without pretending we can override session-save headers.
            assert '*' in values
            assert 'accept-encoding' not in values
        else:
            assert values == {'origin', 'cookie', 'accept-encoding'}
            assert response.headers['Vary'].lower().count('accept-encoding') == 1


@pytest.mark.parametrize('max_age', [0, 60, 300, 3600])
def test_cache_max_age_is_scoped_and_bounded(asset_app, max_age):
    asset_app.config['HTTP_ASSET_CACHE_MAX_AGE'] = max_age
    with asset_app.test_client().get('/static/css/site.css', buffered=True) as response:
        assert response.headers['Cache-Control'] == f'public, max-age={max_age}, must-revalidate'
    assert asset_app.config['SEND_FILE_MAX_AGE_DEFAULT'] is None
    another = Flask('independent')
    another.config['HTTP_ASSET_CACHE_MAX_AGE'] = max_age
    init_http_assets(another)
    assert another.config['HTTP_ASSET_CACHE_MAX_AGE'] == max_age
    assert asset_app.config['HTTP_ASSET_CACHE_MAX_AGE'] == max_age


@pytest.mark.parametrize('max_age', [-1, 3601, True, '300', 1.5, None])
def test_invalid_max_age_configuration_is_rejected(max_age):
    application = Flask('invalid')
    application.config['HTTP_ASSET_CACHE_MAX_AGE'] = max_age
    with pytest.raises(ValueError, match='HTTP_ASSET_CACHE_MAX_AGE'):
        init_http_assets(application)


@pytest.mark.parametrize(
    'endpoint, path, mime',
    [('main.robots_txt', '/robots.txt', 'text/plain'), ('main.sitemap_xml', '/sitemap.xml', 'application/xml')],
)
def test_only_explicit_crawler_endpoints_get_gzip_and_validators(asset_app, endpoint, path, mime):
    def crawler():
        response = Response(BODY, mimetype=mime)
        response.last_modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return response

    asset_app.add_url_rule(path, endpoint=endpoint, view_func=crawler)
    client = asset_app.test_client()
    with client.get(path, headers={'Accept-Encoding': 'gzip'}, buffered=True) as original:
        assert gzip.decompress(original.data) == BODY
        assert original.headers['ETag'].startswith('W/')
        assert original.headers['Cache-Control'] == 'public, max-age=300, must-revalidate'
        etag = original.headers['ETag']
        modified = original.headers['Last-Modified']
        length = original.headers['Content-Length']
    with client.head(path, headers={'Accept-Encoding': 'gzip'}, buffered=True) as head:
        assert head.data == b''
        assert head.headers['Content-Encoding'] == 'gzip'
        assert head.headers['Content-Length'] == length
        assert head.headers['ETag'] == etag
    for conditional in ({'If-None-Match': etag}, {'If-Modified-Since': modified}):
        with client.get(path, headers={'Accept-Encoding': 'gzip', **conditional}, buffered=True) as not_modified:
            assert not_modified.status_code == 304
            assert not_modified.data == b''
            assert not_modified.headers['ETag'] == etag
            assert 'accept-encoding' in vary_values(not_modified)


@pytest.mark.parametrize('mime', ['text/html', 'application/xhtml+xml', 'application/json', 'text/event-stream'])
def test_allowlisted_endpoint_with_unsafe_mime_is_not_transformed(asset_app, mime):
    asset_app.add_url_rule('/robots.txt', endpoint='main.robots_txt', view_func=lambda: Response(BODY, mimetype=mime))
    with asset_app.test_client().get('/robots.txt', headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
        assert response.data == BODY
        assert 'Content-Encoding' not in response.headers
        assert 'Cache-Control' not in response.headers


@pytest.mark.parametrize(
    'path', ['/public.css', '/api/chat/history', '/socket.io/stream', '/uploads/style.css', '/page']
)
def test_textual_dynamic_responses_are_never_implicitly_opted_in(asset_app, path):
    asset_app.add_url_rule(path, view_func=lambda: Response(BODY, mimetype='text/css'))
    with asset_app.test_client().get(path, headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
        assert response.data == BODY
        assert 'Content-Encoding' not in response.headers
        assert 'Cache-Control' not in response.headers


def test_existing_content_encoding_is_never_doubled(asset_app):
    raw = gzip.compress(BODY, mtime=0)
    with asset_app.test_request_context('/static/css/site.css', headers={'Accept-Encoding': 'gzip'}):
        request.url_rule = asset_app.url_map._rules[0]
        request.view_args = {'filename': 'css/site.css'}
        response = Response(raw, mimetype='text/css', headers={'Content-Encoding': 'gzip', 'Vary': 'Origin'})
        result = _prepare_asset_response(response)
        assert result.data == raw
        assert gzip.decompress(result.data) == BODY
        assert result.headers['Content-Encoding'] == 'gzip'
        assert result.headers['Vary'] == 'Origin'
        assert 'Cache-Control' not in result.headers


def test_unknown_stream_is_not_consumed_even_when_endpoint_is_allowlisted(asset_app):
    consumed = []

    def stream():
        consumed.append('read')
        yield BODY

    with asset_app.test_request_context('/robots.txt', headers={'Accept-Encoding': 'gzip'}):
        asset_app.add_url_rule('/robots.txt', endpoint='main.robots_txt', view_func=lambda: '')
        request.url_rule = next(rule for rule in asset_app.url_map.iter_rules() if rule.endpoint == 'main.robots_txt')
        response = Response(stream(), mimetype='text/plain')
        result = _prepare_asset_response(response)
        assert consumed == []
        assert result.is_streamed
        assert 'Content-Encoding' not in result.headers
        assert 'Cache-Control' not in result.headers
        result.close()


def test_static_file_wrapper_is_closed_only_when_replaced(asset_app):
    with asset_app.test_request_context('/static/css/site.css', headers={'Accept-Encoding': 'gzip'}):
        request.url_rule = asset_app.url_map._rules[0]
        request.view_args = {'filename': 'css/site.css'}
        source = io.BytesIO(BODY)
        response = Response(FileWrapper(source), mimetype='text/css', direct_passthrough=True)
        response.content_length = len(BODY)
        result = _prepare_asset_response(response)
        assert source.closed
        assert result.direct_passthrough is False
        assert gzip.decompress(result.data) == BODY


def test_incompressible_small_payload_remains_identity(asset_app):
    # Fixed random seed is a byte fixture, not a synthetic performance benchmark.
    data = random.Random(7).randbytes(512)
    assert len(gzip.compress(data, mtime=0)) >= len(data)
    asset_app.add_url_rule(
        '/robots.txt', endpoint='main.robots_txt', view_func=lambda: Response(data, mimetype='text/plain')
    )
    with asset_app.test_client().get('/robots.txt', headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
        assert response.data == data
        assert 'Content-Encoding' not in response.headers


@pytest.mark.parametrize('cookie', ['guest=synthetic', 'session=invalid-test-cookie'])
def test_public_fixed_static_content_allows_existing_cookies(asset_app, cookie):
    with asset_app.test_client(use_cookies=False).get(
        '/static/css/site.css', headers={'Accept-Encoding': 'gzip', 'Cookie': cookie}, buffered=True
    ) as response:
        assert response.headers['Cache-Control'] == 'public, max-age=300, must-revalidate'
        assert gzip.decompress(response.data) == BODY
        assert not response.headers.getlist('Set-Cookie')


@pytest.mark.parametrize(
    'endpoint, path, mime',
    [
        ('main.robots_txt', '/robots.txt', 'text/plain'),
        ('main.sitemap_xml', '/sitemap.xml', 'application/xml'),
    ],
)
def test_crawler_cookie_is_not_public_or_compressed(asset_app, endpoint, path, mime):
    asset_app.add_url_rule(path, endpoint=endpoint, view_func=lambda: Response(BODY, mimetype=mime))
    with asset_app.test_client(use_cookies=False).get(
        path, headers={'Accept-Encoding': 'gzip', 'Cookie': 'guest=synthetic'}, buffered=True
    ) as response:
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.data == BODY
        assert 'Content-Encoding' not in response.headers


@pytest.mark.parametrize('private_directive', ['private', 'private="Set-Cookie"', 'no-store', 'no-transform'])
def test_multiple_cache_control_headers_cannot_hide_private_policy(asset_app, private_directive):
    @asset_app.after_request
    def separate_private_header(response):
        response.headers['Cache-Control'] = 'public, max-age=300'
        response.headers.add('Cache-Control', private_directive)
        return response

    with asset_app.test_client().get(
        '/static/css/site.css', headers={'Accept-Encoding': 'gzip'}, buffered=True
    ) as response:
        assert response.headers.getlist('Cache-Control') == ['public, max-age=300', private_directive]
        assert response.data == BODY
        assert 'Content-Encoding' not in response.headers


def test_client_no_transform_is_respected(asset_app):
    with asset_app.test_client().get(
        '/static/css/site.css', headers={'Accept-Encoding': 'gzip', 'Cache-Control': 'no-transform'}, buffered=True
    ) as response:
        assert response.data == BODY
        assert 'Content-Encoding' not in response.headers
        assert response.headers['Cache-Control'] == 'no-cache'


@pytest.mark.parametrize('path, method', [('/static/missing.css', 'get'), ('/static/css/site.css', 'post')])
def test_error_and_non_get_responses_are_not_cached_or_compressed(asset_app, path, method):
    with getattr(asset_app.test_client(), method)(path, headers={'Accept-Encoding': 'gzip'}, buffered=True) as response:
        assert response.status_code in {404, 405}
        assert 'Content-Encoding' not in response.headers
        assert not response.cache_control.public


def test_filelike_wrapper_is_recognized_and_closed_when_gzip_replaces_it(asset_app):
    class FilelikeWrapper:
        def __init__(self, filelike):
            self.filelike = filelike

        def __iter__(self):
            while chunk := self.filelike.read(8192):
                yield chunk

        def close(self):
            self.filelike.close()

    with asset_app.test_request_context('/static/css/site.css', headers={'Accept-Encoding': 'gzip'}):
        request.url_rule = next(rule for rule in asset_app.url_map.iter_rules() if rule.endpoint == 'static')
        request.view_args = {'filename': 'css/site.css'}
        source = io.BytesIO(BODY)
        response = Response(FilelikeWrapper(source), mimetype='text/css', direct_passthrough=True)
        response.content_length = len(BODY)
        result = _prepare_asset_response(response)
        assert source.closed
        assert result.direct_passthrough is False
        assert gzip.decompress(result.data) == BODY


def test_deceptive_sequence_over_body_cap_is_left_uncompressed(asset_app):
    with asset_app.test_request_context('/static/css/site.css', headers={'Accept-Encoding': 'gzip'}):
        request.url_rule = next(rule for rule in asset_app.url_map.iter_rules() if rule.endpoint == 'static')
        request.view_args = {'filename': 'css/site.css'}
        chunks = [b'x' * (1024 * 1024), b'y']
        response = Response(chunks, mimetype='text/css')
        response.content_length = len(BODY)  # Deliberately deceptive but still within the advertised bound.
        original = response.response
        result = _prepare_asset_response(response)
        assert result.response is original
        assert result.content_length == len(BODY)
        assert 'Content-Encoding' not in result.headers
        assert result.headers['Cache-Control'] == 'public, max-age=300, must-revalidate'


@pytest.mark.parametrize('direct_passthrough,seekable', [(False, True), (True, False)])
def test_unbufferable_file_wrappers_are_not_read_or_replaced(asset_app, direct_passthrough, seekable):
    class GuardedSource(io.BytesIO):
        def read(self, *args):
            raise AssertionError('An unrecognized file wrapper must not be consumed')

        def seekable(self):
            return seekable

    with asset_app.test_request_context('/static/css/site.css', headers={'Accept-Encoding': 'gzip'}):
        request.url_rule = next(rule for rule in asset_app.url_map.iter_rules() if rule.endpoint == 'static')
        request.view_args = {'filename': 'css/site.css'}
        source = GuardedSource(BODY)
        wrapper = FileWrapper(source)
        response = Response(wrapper, mimetype='text/css', direct_passthrough=direct_passthrough)
        response.content_length = len(BODY)
        result = _prepare_asset_response(response)
        assert result.response is wrapper
        assert result.direct_passthrough is direct_passthrough
        assert not source.closed
        assert 'Content-Encoding' not in result.headers
        assert 'Cache-Control' not in result.headers
        result.close()
        assert source.closed


def test_file_buffer_limit_does_not_read_or_leak_large_sources(asset_app):
    class UnreadableLargeFile(io.BytesIO):
        def read(self, *args):
            raise AssertionError('Bodies above the buffer bound must not be read')

    with asset_app.test_request_context('/static/css/site.css', headers={'Accept-Encoding': 'gzip'}):
        request.url_rule = next(rule for rule in asset_app.url_map.iter_rules() if rule.endpoint == 'static')
        request.view_args = {'filename': 'css/site.css'}
        source = UnreadableLargeFile()
        response = Response(FileWrapper(source), mimetype='text/css', direct_passthrough=True)
        response.content_length = 1024 * 1024 + 1
        result = _prepare_asset_response(response)
        assert result.direct_passthrough
        assert not source.closed
        assert 'Content-Encoding' not in result.headers
        result.close()
        assert source.closed
