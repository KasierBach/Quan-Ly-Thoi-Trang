"""Bounded in-process limiter tests, not load tests or production throughput claims.

Login uses its real 10/min decorator. The other HTTP routes inherit the default
(currently 300/min); 3/min is a TEST-ONLY override to keep requests minimal.
"""

from copy import copy
from unittest.mock import Mock

import pytest

from app import create_app, limiter
from app.database import close_db_pool
from app.services.auth_service import AuthService
from app.services.base_service import BaseService
from app.services.chat_service import ChatService
from app.services.main_service import MainService


@pytest.fixture
def rate_app(app, monkeypatch):
    monkeypatch.setattr(BaseService, 'get_connection', Mock(side_effect=AssertionError('Rate test attempted DB I/O')))
    # Decorators close over this singleton. Keep them intact, isolate only extension
    # state/storage, and restore it so enabling limits cannot leak into other tests.
    original = vars(limiter).copy()
    manager = copy(limiter.limit_manager)
    manager.set_default_limits([])
    manager._endpoint_hints = {}
    limiter.limit_manager = manager
    limiter._storage_options = limiter._storage_options.copy()
    limiter._headers_enabled = True
    limiter._key_prefix = 'phase4-offline'
    configuration = dict(app.config)
    configuration.update(
        RATELIMIT_ENABLED=True,
        RATELIMIT_STORAGE_URI='memory://',
        RATELIMIT_DEFAULT='3 per minute',
        RATELIMIT_HEADERS_ENABLED=True,
        WTF_CSRF_ENABLED=False,
    )
    application = None
    try:
        application = create_app(configuration)
        with application.app_context():
            limiter.reset()
        yield application
    finally:
        if application is not None:
            with application.app_context():
                limiter.reset()
            application.extensions['chat_socket_handlers'].close()
            close_db_pool(application)
        vars(limiter).clear()
        vars(limiter).update(original)


def test_login_real_decorator_blocks_eleventh_attempt_before_authentication(rate_app, monkeypatch):
    authenticate = Mock(return_value=None)  # Failed authentication, never synthetic API success.
    monkeypatch.setattr(AuthService, 'login_user', authenticate)
    browser = rate_app.test_client()
    for _ in range(10):
        assert browser.post('/login', data={'email': 'user@example.test', 'password': 'wrong'}).status_code == 400
    blocked = browser.post('/login', data={'email': 'user@example.test', 'password': 'wrong'})
    assert blocked.status_code == 429
    assert blocked.headers['X-RateLimit-Limit'] == '10'
    assert int(blocked.headers['Retry-After']) > 0
    assert authenticate.call_count == 10
    with browser.session_transaction() as state:
        assert 'user_id' not in state


@pytest.mark.parametrize(
    'path,body,service,name',
    [
        (
            '/contact',
            {'data': {'name': 'Test', 'email': 'invalid', 'message': 'Test'}},
            MainService,
            'add_contact_message',
        ),
        ('/subscribe_newsletter', {'data': {'email': 'invalid'}}, MainService, 'subscribe_newsletter'),
        ('/api/chat/send', {'json': []}, ChatService, 'send_message'),
    ],
)
def test_default_limited_routes_validate_then_block_without_mutation(rate_app, monkeypatch, path, body, service, name):
    mutate = Mock(side_effect=AssertionError('Invalid or rate-limited request reached mutation'))
    monkeypatch.setattr(service, name, mutate)
    browser = rate_app.test_client()
    for _ in range(3):
        assert browser.post(path, **body).status_code == 400
    blocked = browser.post(path, **body)
    assert blocked.status_code == 429
    assert blocked.headers['X-RateLimit-Limit'] == '3'
    assert int(blocked.headers['Retry-After']) > 0
    mutate.assert_not_called()


def test_default_limit_is_per_endpoint_remote_address_and_resettable(rate_app):
    browser = rate_app.test_client()
    body = {'email': 'invalid'}
    for _ in range(3):
        assert browser.post('/subscribe_newsletter', data=body).status_code == 400
    assert browser.post('/subscribe_newsletter', data=body).status_code == 429
    assert browser.post('/contact', data={'email': 'invalid'}).status_code == 400
    assert (
        browser.post('/subscribe_newsletter', data=body, environ_overrides={'REMOTE_ADDR': '127.0.0.2'}).status_code
        == 400
    )
    with rate_app.app_context():
        limiter.reset()
    assert browser.post('/subscribe_newsletter', data=body).status_code == 400
