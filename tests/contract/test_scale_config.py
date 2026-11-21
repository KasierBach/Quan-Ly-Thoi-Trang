"""Offline scale/local-load contracts. No DB fixture, server or network request."""

import ast
import csv
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import create_app, socketio
from app.config import Config
from app.sockets import ChatSocketHandlers
from app.services.conversation_service import ChatAccess, ChatAccessError, ChatIdentity, ConversationService
from tools.load_test import loopback_target, main, summarize_csv, validate_local_configuration, validate_test_database
from tools.verify_cross_worker import worker_url


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DSN = 'postgresql://fixture:fixture@127.0.0.1:55435/thua2_main_test'


@pytest.mark.parametrize(
    'target,expected',
    [
        ('http://localhost:4011/', 'http://127.0.0.1:4011'),
        ('http://127.0.0.1:4011', 'http://127.0.0.1:4011'),
        ('https://[::1]:4443', 'https://[::1]:4443'),
    ],
)
def test_load_target_is_canonical_literal_loopback(target, expected):
    assert loopback_target(target) == expected


@pytest.mark.parametrize(
    'target',
    [
        'https://example.com:443',
        'http://192.168.1.2:4011',
        'http://0.0.0.0:4011',
        'http://127.0.0.1.evil:4011',
        'http://127.0.0.1:4011@evil:80',
        'http://user@localhost:4011',
        'http://localhost',
        'http://localhost:4011/products',
        'http://localhost:4011?host=evil',
        'http://localhost:4011#fragment',
        'http://localhost:4011/\\evil',
        'http://localhost:4011\n',
        'ftp://127.0.0.1:21',
        'http://[::1%25eth0]:4011',
        'http://127.0.0.1:99999',
    ],
)
def test_load_target_refuses_remote_or_ambiguous_urls(target):
    with pytest.raises(ValueError):
        loopback_target(target)


@pytest.mark.parametrize(
    'dsn',
    [
        'postgresql://fixture:fixture@remote/thua2_main_test',
        'postgresql://fixture:fixture@localhost/production',
        LOCAL_DSN + '?host=remote',
        LOCAL_DSN + '#fragment',
        'postgresql://fixture:fixture@localhost:99999/thua2_main_test',
        'postgresql://fixture@localhost/thua2_main_test',
        '',
    ],
)
def test_load_configuration_refuses_nonlocal_db_before_requests(dsn):
    with pytest.raises(ValueError):
        validate_test_database(dsn)


def test_load_rejects_production_and_remote_environment():
    for environment in ({'APP_ENV': 'production'}, {'DATABASE_URL': LOCAL_DSN.replace('127.0.0.1', 'remote')}, {}):
        with pytest.raises(ValueError):
            validate_local_configuration('http://127.0.0.1:4011', environment)
    assert (
        validate_local_configuration('http://localhost:4011', {'SCALE_INTERNAL_DATABASE_CONFIRMED': 'true'})
        == 'http://127.0.0.1:4011'
    )
    with pytest.raises(ValueError):
        validate_local_configuration('http://localhost:4011', {'SCALE_INTERNAL_DATABASE_CONFIRMED': 'TRUE'})


def test_preview_never_spawns_load_process(monkeypatch, capsys):
    import tools.load_test as runner

    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('TEST_DATABASE_URL', raising=False)
    monkeypatch.delenv('APP_ENV', raising=False)
    monkeypatch.delenv('FLASK_ENV', raising=False)
    monkeypatch.delenv('SCALE_INTERNAL_DATABASE_CONFIRMED', raising=False)
    spawn = MagicMock(side_effect=AssertionError('Offline preview must not run Locust'))
    monkeypatch.setattr(runner.subprocess, 'run', spawn)
    assert main([]) == 0
    assert 'NOT RUN' in capsys.readouterr().out
    spawn.assert_not_called()
    monkeypatch.setenv('TEST_DATABASE_URL', LOCAL_DSN)
    with pytest.raises(SystemExit):
        main(['--execute'])
    spawn.assert_not_called()


def test_queue_environment_is_optional_and_blank_is_none(monkeypatch):
    monkeypatch.delenv('SOCKETIO_MESSAGE_QUEUE', raising=False)
    assert Config.from_environment()['SOCKETIO_MESSAGE_QUEUE'] is None
    monkeypatch.setenv('SOCKETIO_MESSAGE_QUEUE', '')
    assert Config.from_environment()['SOCKETIO_MESSAGE_QUEUE'] is None
    monkeypatch.setenv('SOCKETIO_MESSAGE_QUEUE', 'redis://redis:6379/1')
    assert Config.from_environment()['SOCKETIO_MESSAGE_QUEUE'] == 'redis://redis:6379/1'


def test_factory_injects_queue_without_connecting_or_losing_origins(app, monkeypatch):
    initialize = MagicMock()
    monkeypatch.setattr(socketio, 'init_app', initialize)
    queue_app = create_app(
        {
            **app.config,
            'SOCKETIO_MESSAGE_QUEUE': 'redis://redis:6379/1',
            'ALLOWED_ORIGINS': ['http://127.0.0.1:4011'],
        }
    )
    try:
        initialize.assert_called_once_with(
            queue_app, message_queue='redis://redis:6379/1', cors_allowed_origins=['http://127.0.0.1:4011']
        )
        initialize.reset_mock()
        single_app = create_app({**app.config, 'SOCKETIO_MESSAGE_QUEUE': None, 'ALLOWED_ORIGINS': None})
        try:
            initialize.assert_called_once_with(single_app)
        finally:
            single_app.extensions['chat_socket_handlers'].close()
    finally:
        queue_app.extensions['chat_socket_handlers'].close()


def test_scale_topology_keeps_single_worker_instances_and_shared_backplane():
    compose = (ROOT / 'docker-compose.scale.yml').read_text(encoding='utf-8')
    proxy = (ROOT / 'tools' / 'nginx.scale.conf').read_text(encoding='utf-8')
    assert '--workers, "1"' in compose and '--workers, "2"' not in compose
    assert '  web1:\n    <<: *web' in compose and '  web2:\n    <<: *web' in compose
    assert 'SOCKETIO_MESSAGE_QUEUE: redis://redis:6379/1' in compose
    assert 'RATELIMIT_STORAGE_URI: redis://redis:6379/0' in compose
    assert 'redis:7.4.2-alpine' in compose and 'POSTGRES_DB: thua2_main_test' in compose
    assert '${SCALE_SECRET_KEY:?' in compose and 'env_file:' not in compose
    assert 'internal: true' in compose and 'read_only: true' in compose
    assert '127.0.0.1:55435' not in compose and 'docker compose exec' in compose
    assert 'OAUTH_ENABLED: "false"' in compose and 'GEOCODE_NETWORK_ENABLED: "false"' in compose
    assert 'ip_hash;' in proxy and 'server web1:4000;' in proxy and 'server web2:4000;' in proxy
    assert 'proxy_http_version 1.1;' in proxy and 'proxy_buffering off;' in proxy
    assert 'proxy_set_header Upgrade $http_upgrade;' in proxy
    assert 'proxy_set_header X-Forwarded-For $remote_addr;' in proxy


def test_locust_guards_and_redirects_without_network(monkeypatch):
    # Stub Locust instead of importing gevent or starting any real runner.
    import sys

    def task(_weight):
        return lambda function: function

    events = SimpleNamespace(
        **{
            name: SimpleNamespace(add_listener=lambda function: function)
            for name in ('init_command_line_parser', 'init', 'test_start')
        }
    )
    monkeypatch.setitem(
        sys.modules, 'locust', SimpleNamespace(HttpUser=object, between=lambda *_: None, events=events, task=task)
    )
    spec = importlib.util.spec_from_file_location('offline_load_workload', ROOT / 'tests' / 'load' / 'locustfile.py')
    workload = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workload)
    monkeypatch.setenv('TEST_DATABASE_URL', LOCAL_DSN)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('APP_ENV', raising=False)
    monkeypatch.delenv('FLASK_ENV', raising=False)
    monkeypatch.delenv('SCALE_INTERNAL_DATABASE_CONFIRMED', raising=False)
    environment = SimpleNamespace(host='http://127.0.0.1:4011', parsed_options=SimpleNamespace(yes_local_load=True))
    user = workload.StorefrontUser()
    user.environment = environment
    user.client = MagicMock(base_url=environment.host)
    user.on_start()
    assert user.client.trust_env is False
    user.client.proxies.clear.assert_called_once()
    response = user.client.get.return_value.__enter__.return_value
    response.status_code = 302
    user.products()
    user.client.get.assert_called_once_with(
        environment.host + '/products', name='GET products', allow_redirects=False, timeout=10, catch_response=True
    )
    response.failure.assert_called_once()
    user.client.get.reset_mock()
    environment.host = 'https://example.com:443'
    with pytest.raises(SystemExit):
        workload.guard_run(environment)
    environment.host = 'http://127.0.0.1:4011'
    monkeypatch.setenv('DATABASE_URL', LOCAL_DSN.replace('127.0.0.1', 'remote'))
    with pytest.raises(ValueError):
        user.products()
    user.client.get.assert_not_called()


def test_csv_summary_is_measured_and_never_fills_missing_results(tmp_path):
    prefix = tmp_path / 'fixture'
    fields = ['Name', 'Request Count', 'Failure Count', '50%', '95%', 'Requests/s']
    with Path(str(prefix) + '_stats.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow(dict(zip(fields, ['Aggregated', '20', '2', '11', '35', '2'], strict=True)))
    with Path(str(prefix) + '_stats_history.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['Name', 'Requests/s'])
        writer.writeheader()
        writer.writerows([{'Name': 'Aggregated', 'Requests/s': '2'}, {'Name': 'Aggregated', 'Requests/s': '3'}])
    result = summarize_csv(prefix)
    assert (result['p50_ms'], result['p95_ms'], result['max_observed_rps_10s_window']) == (11, 35, 3)
    assert result['error_rate_percent'] == 10
    with pytest.raises(OSError):
        summarize_csv(tmp_path / 'unrun')


def test_other_process_only_call_target_is_rejected_without_creating_call(app, monkeypatch):
    caller, peer = ChatIdentity(user_id=1), ChatIdentity(user_id=3)
    local = ChatSocketHandlers(MagicMock(), app)
    other_process = ChatSocketHandlers(MagicMock(), app)
    local.clients['caller'] = caller
    other_process.clients['peer'] = peer
    local.generations['caller'] = object()
    access = ChatAccess(caller, conversation_id=7, conversation_type='direct')
    monkeypatch.setattr(local, '_access', lambda *_args, **_kwargs: access)
    monkeypatch.setattr(ConversationService, 'get_participants', lambda *_args, **_kwargs: [{'id': 1}, {'id': 3}])
    with app.test_request_context('/'):
        from flask import request

        request.sid = 'caller'
        with pytest.raises(ChatAccessError) as error:
            # Bypass only guarded_event's authentication wrapper, not the target logic.
            local.handle_call_user.__wrapped__(
                local,
                {
                    'call_id': 'local-only-contract',
                    'conversation_id': 7,
                    'offer': {'type': 'offer', 'sdp': 'v=0\r\n'},
                    'isVideo': False,
                },
            )
        assert error.value.status == 409
    assert not local.calls and not other_process.calls
    local.socketio.emit.assert_not_called()
    other_process.socketio.emit.assert_not_called()


def test_cross_worker_probe_accepts_only_exact_internal_worker_urls():
    assert worker_url('http://web1:4000') == 'http://web1:4000'
    assert worker_url('http://web2:4000/') == 'http://web2:4000'
    for value in (
        'http://127.0.0.1:4000',
        'http://web1:4000/path',
        'http://web1:4000?next=web2',
        'http://web1:4000@evil:80',
        'https://web1:4000',
        'http://web3:4000',
    ):
        with pytest.raises(ValueError):
            worker_url(value)


def test_new_load_sources_parse_offline():
    for path in (
        ROOT / 'tools' / 'load_test.py',
        ROOT / 'tools' / 'verify_cross_worker.py',
        ROOT / 'tests' / 'load' / 'locustfile.py',
    ):
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
