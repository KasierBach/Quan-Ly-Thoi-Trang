"""Bounded HTTP caching and gzip for public assets, never for application pages.

This intentionally does not register a general MIME-based compressor. HTML,
JSON, chat/socket traffic, uploads, and arbitrary streamed responses are outside
its endpoint allowlist, even when a client asks for gzip.
"""

import gzip
import io
import re
from pathlib import PurePosixPath
from time import time

from flask import current_app, request, session
from werkzeug.http import http_date, parse_cache_control_header, parse_set_header


_MIN_GZIP_BYTES = 500
_MAX_GZIP_BYTES = 1024 * 1024
_GZIP_LEVEL = 6
_CRAWLER_MIMETYPES = {
    'main.robots_txt': {'text/plain'},
    'main.sitemap_xml': {'application/xml', 'text/xml'},
}
_STATIC_MIMETYPES = {
    '.css': {'text/css'},
    '.js': {'application/javascript', 'text/javascript', 'application/x-javascript'},
    '.svg': {'image/svg+xml'},
}
_TOKEN_HEADERS = {'Authorization', 'Proxy-Authorization', 'X-Chat-Token', 'X-CSRFToken', 'X-CSRF-Token'}
_QVALUE = re.compile(r'(?:0(?:\.\d{0,3})?|\.\d{1,3}|1(?:\.0{0,3})?)\Z')


def init_http_assets(app):
    """Register before other after-request hooks, so their privacy rules win.

    The only configurable setting is asset freshness, not global send_file or
    compression behavior. Limit overrides to one hour; unversioned URLs must
    never acquire a one-year immutable policy.
    """
    max_age = app.config.setdefault('HTTP_ASSET_CACHE_MAX_AGE', 300)
    if isinstance(max_age, bool) or not isinstance(max_age, int) or not 0 <= max_age <= 3600:
        raise ValueError('HTTP_ASSET_CACHE_MAX_AGE must be an integer between 0 and 3600 seconds')
    app.after_request(_prepare_asset_response)


def _accepts_gzip(header):
    """Honor explicit refusals, wildcard fallback, and identity preference.

    Accept the common ``q=.5`` spelling as well as RFC qvalues. Invalid or
    conflicting duplicate entries fail closed: an explicit gzip refusal cannot
    be overridden by a wildcard or another gzip entry.
    """
    qualities = {}
    for item in header.split(','):
        parts = [part.strip() for part in item.split(';')]
        coding = parts[0].lower()
        if coding not in {'gzip', 'identity', '*'}:
            continue
        quality = 1.0
        if len(parts) > 1:
            name, separator, value = parts[1].partition('=')
            value = value.strip()
            if len(parts) != 2 or name.strip().lower() != 'q' or not separator or not _QVALUE.fullmatch(value):
                quality = 0.0
            else:
                quality = float(value)
        qualities[coding] = min(qualities.get(coding, quality), quality)
    gzip_quality = qualities.get('gzip', qualities.get('*', 0.0))
    return gzip_quality > 0 and gzip_quality >= qualities.get('identity', 0.0)


def _asset_kind(response):
    if request.endpoint in _CRAWLER_MIMETYPES:
        return 'crawler' if response.mimetype in _CRAWLER_MIMETYPES[request.endpoint] else None
    if request.endpoint != 'static':
        return None
    filename = (request.view_args or {}).get('filename', '').replace('\\', '/')
    path = PurePosixPath(filename)
    if path.is_absolute() or '..' in path.parts or any(part.lower() == 'uploads' for part in path.parts):
        return None
    return 'static' if response.mimetype in _STATIC_MIMETYPES.get(path.suffix.lower(), ()) else None


def _static_file(response):
    """Recognize finite native Werkzeug/Gunicorn file responses, not generators."""
    if not response.direct_passthrough:
        return None
    wrapper = response.response
    source = getattr(wrapper, 'file', None)
    if source is None:
        source = getattr(wrapper, 'filelike', None)
    if isinstance(source, io.IOBase) and source.readable() and source.seekable():
        return source
    return None


def _bounded_body(response, source):
    length = response.content_length
    if length is None or length < 0 or length > _MAX_GZIP_BYTES:
        return None
    if response.is_sequence:
        chunks = []
        size = 0
        for chunk in response.iter_encoded():
            size += len(chunk)
            if size > _MAX_GZIP_BYTES:
                return None
            chunks.append(chunk)
        data = b''.join(chunks)
    elif source is not None:
        # Do not consume/replace the original file wrapper unless gzip wins.
        position = source.tell()
        try:
            data = source.read(_MAX_GZIP_BYTES + 1)
        finally:
            source.seek(position)
    else:
        return None
    return data if len(data) == length and len(data) <= _MAX_GZIP_BYTES else None


def _credential_bearing(response, kind):
    app = current_app
    return (
        bool(request.query_string)
        or (kind == 'crawler' and ('Cookie' in request.headers or session.get('user_id') is not None))
        or any(header in request.headers or header in response.headers for header in _TOKEN_HEADERS)
        or 'Set-Cookie' in response.headers
        or session.modified
        or (bool(session) and app.session_interface.should_set_cookie(app, session))
    )


def _vary_on_encoding(response):
    # Merge every Vary header line, preserving Cookie/Origin and case-insensitive
    # deduplication. A wildcard already varies on everything.
    vary = parse_set_header(', '.join(response.headers.getlist('Vary')))
    if '*' not in vary:
        vary.add('Accept-Encoding')
    response.headers['Vary'] = vary.to_header()


def _weak_etag(response):
    # Retain Flask's automatic source validator, but never use a strong ETag for
    # two different byte representations. Weak comparison permits GET/HEAD 304s;
    # range/strong-precondition requests continue through Flask as identity.
    etag, _ = response.get_etag()
    if etag is not None:
        response.set_etag(etag, weak=True)


def _prepare_asset_response(response):
    if request.method not in {'GET', 'HEAD'} or response.status_code not in {200, 304}:
        return response
    kind = _asset_kind(response)
    if kind is None:
        return response
    cache = parse_cache_control_header(', '.join(response.headers.getlist('Cache-Control')))
    request_cache = parse_cache_control_header(request.headers.get('Cache-Control'))
    if (
        any(directive in cache for directive in ('no-store', 'private', 'no-transform'))
        or 'no-transform' in request_cache
        or 'Content-Encoding' in response.headers
    ):
        return response
    if (
        any(header in request.headers for header in ('Range', 'If-Range', 'If-Match'))
        or 'Content-Range' in response.headers
        or 'X-Sendfile' in response.headers
        or response.headers.get('Content-Disposition', '').lower().startswith('attachment')
    ):
        return response
    source = _static_file(response) if kind == 'static' else None
    if not response.is_sequence and source is None:
        return response
    if _credential_bearing(response, kind):
        # Flask saves session cookies after after_request. Detect pending writes
        # as well as already-set cookies, without replacing the session interface.
        response.headers['Cache-Control'] = 'no-store'
        response.headers.pop('Expires', None)
        return response

    max_age = current_app.config['HTTP_ASSET_CACHE_MAX_AGE']
    response.headers['Cache-Control'] = f'public, max-age={max_age}, must-revalidate'
    response.headers['Expires'] = http_date(time() + max_age)
    _vary_on_encoding(response)
    gzip_allowed = _accepts_gzip(request.headers.get('Accept-Encoding', ''))
    data = None
    if gzip_allowed or (kind == 'crawler' and response.get_etag()[0] is None):
        data = _bounded_body(response, source)
    if kind == 'crawler' and data is not None and response.get_etag()[0] is None:
        response.add_etag()
    if gzip_allowed and data is not None and len(data) >= _MIN_GZIP_BYTES:
        compressed = gzip.compress(data, compresslevel=_GZIP_LEVEL, mtime=0)
        if len(compressed) < len(data):
            _weak_etag(response)
            if response.status_code == 200:
                original = response.response
                response.direct_passthrough = False
                response.set_data(compressed)
                if source is not None:
                    original.close()
                response.headers['Content-Encoding'] = 'gzip'
                response.headers.pop('Accept-Ranges', None)
    if response.status_code == 200:
        response.make_conditional(request)
    return response
