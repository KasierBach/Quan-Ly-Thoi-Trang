from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.main_service import MainService
from tools import docker_healthcheck


@pytest.mark.parametrize('public_url,ready', [('https://store.example.test:8443/catalog', True), ('', False)])
def test_docker_probe_uses_canonical_host_for_trusted_flask_routes(app, client, monkeypatch, public_url, ready):
    app.config['TRUSTED_HOSTS'] = ['store.example.test']
    monkeypatch.setenv('PUBLIC_BASE_URL', public_url)
    monkeypatch.setattr(MainService, 'check_health', Mock(return_value=True))

    connection = Mock()

    def request(method, path, *, headers):
        with client.open(path, method=method, headers=headers, base_url='http://127.0.0.1:4000') as response:
            connection.getresponse.return_value = SimpleNamespace(status=response.status_code)

    connection.request.side_effect = request
    open_connection = Mock(return_value=connection)
    monkeypatch.setattr(docker_healthcheck, 'HTTPConnection', open_connection)

    assert docker_healthcheck.is_ready() is ready
    open_connection.assert_called_once_with('127.0.0.1', 4000, timeout=3)
    connection.close.assert_called_once()
