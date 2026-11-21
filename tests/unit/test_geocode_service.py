"""Geocode service tests: synthetic strings, mock every HTTP request, no database."""

from unittest.mock import Mock

from flask import Flask
import pytest
import requests

from app.config import Config
from app.services import geocode_service as module
from app.services.geocode_service import GeocodeError, GeocodeService


ADDRESS = '1 Synthetic Test Street'


@pytest.fixture
def configured(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        GEOCODE_ENABLED=True,
        GEOCODE_NETWORK_ENABLED=True,
        GEOCODE_ALLOW_PUBLIC_ADDRESS_QUERIES=True,
        GEOCODE_USER_AGENT='SyntheticMapTests/1.0',
        GEOCODE_CONTACT='maps@example.test',
    )
    http = Mock(side_effect=AssertionError('Unmocked geocode HTTP request'))
    # No socket/network operation can originate from the service under test.
    monkeypatch.setattr(module.requests, 'get', http)
    monkeypatch.setattr(GeocodeService, '_next_request_at', 0.0)
    with app.app_context():
        yield app, http


def provider_response(http, payload=None, status=200, headers=None):
    response = Mock(status_code=status, headers=headers or {})
    response.json.return_value = payload if payload is not None else [{'lat': '0', 'lon': '0'}]
    http.side_effect = None
    http.return_value = response
    return response


def test_default_and_absent_configuration_disable_all_network(configured):
    app, http = configured
    assert Config.GEOCODE_ENABLED is False
    assert Config.GEOCODE_NETWORK_ENABLED is False
    assert Config.GEOCODE_ALLOW_PUBLIC_ADDRESS_QUERIES is False
    app.config.pop('GEOCODE_USER_AGENT')
    with pytest.raises(GeocodeError) as error:
        GeocodeService.geocode(ADDRESS)
    assert error.value.status_code == 503
    http.assert_not_called()


@pytest.mark.parametrize(
    'key,value',
    [
        ('GEOCODE_ENABLED', False),
        ('GEOCODE_ENABLED', 'true'),
        ('GEOCODE_USER_AGENT', ''),
        ('GEOCODE_USER_AGENT', 'python-requests/2.0'),
        ('GEOCODE_USER_AGENT', 'curl/8.0'),
        ('GEOCODE_USER_AGENT', 'Mozilla/5.0'),
        ('GEOCODE_USER_AGENT', 'SyntheticMapTests/1.0\r\nOther: header'),
        ('GEOCODE_CONTACT', None),
        ('GEOCODE_CONTACT', 'not-a-contact'),
        ('GEOCODE_CONTACT', 'person@example.test\r\nOther: header'),
        ('GEOCODE_CONTACT', 'http://contact.example.test'),
        ('GEOCODE_CONTACT', 'https://user:pass@contact.example.test'),
        ('GEOCODE_CONTACT', 'https://contact.example.test?q=address'),
        ('GEOCODE_CONTACT', 'https://contact.example.test#state'),
        ('GEOCODE_CONTACT', 'https://contact.example.test:invalid'),
        ('GEOCODE_CONTACT', 'https://contact.example.test:444'),
    ],
)
def test_identity_contact_and_feature_are_required(configured, key, value):
    app, http = configured
    app.config[key] = value
    assert GeocodeService.is_configured() is False
    with pytest.raises(GeocodeError):
        GeocodeService.geocode(ADDRESS)
    http.assert_not_called()


def test_placeholder_contact_never_enables_a_non_test_app(configured):
    app, http = configured
    app.config['TESTING'] = False
    assert GeocodeService.is_configured() is False
    with pytest.raises(GeocodeError):
        GeocodeService.geocode(ADDRESS)
    http.assert_not_called()


@pytest.mark.parametrize('flag', ['GEOCODE_NETWORK_ENABLED', 'GEOCODE_ALLOW_PUBLIC_ADDRESS_QUERIES'])
def test_network_and_public_address_opt_in_are_both_required(configured, flag):
    app, http = configured
    app.config[flag] = False
    assert GeocodeService.is_configured() is True
    assert GeocodeService.network_enabled() is False
    with pytest.raises(GeocodeError) as error:
        GeocodeService.geocode(ADDRESS)
    assert error.value.status_code == 503
    http.assert_not_called()


def test_fixed_https_request_has_real_config_headers_no_redirects_or_metadata(configured):
    app, http = configured
    response = provider_response(
        http, [{'lat': '0', 'lon': '0', 'display_name': '<script>bad</script>', 'url': 'javascript:bad'}]
    )
    assert GeocodeService.geocode(ADDRESS) == {'lat': 0.0, 'lon': 0.0}
    http.assert_called_once_with(
        'https://nominatim.openstreetmap.org/search',
        params={'q': ADDRESS.casefold(), 'format': 'jsonv2', 'limit': 1, 'addressdetails': 0},
        headers={
            'User-Agent': 'SyntheticMapTests/1.0 (maps@example.test)',
            'Accept': 'application/json',
            'Accept-Language': 'vi,en;q=0.8',
        },
        timeout=(3, 5),
        allow_redirects=False,
        verify=True,
    )
    response.close.assert_called_once()
    assert 'display_name' not in GeocodeService.cache().get(GeocodeService.cache_key(ADDRESS))


def test_cache_normalizes_whitespace_case_unicode_and_uses_only_hash(configured):
    _, http = configured
    provider_response(http, [{'lat': '12.5', 'lon': '-20.25'}])
    first = GeocodeService.geocode('  1 Synthetic\nTest   Street  ')
    first['lat'] = 85.0
    assert GeocodeService.geocode('1 SYNTHETIC TEST STREET') == {'lat': 12.5, 'lon': -20.25}
    key = GeocodeService.cache_key(ADDRESS)
    assert len(key.rsplit(':', 1)[1]) == 64
    assert 'street' not in key and ADDRESS not in repr(GeocodeService.cache()._cache)
    assert GeocodeService.cache_key('Synthetic Café') == GeocodeService.cache_key('Synthetic Cafe\u0301')
    http.assert_called_once()


def test_prepopulated_real_cache_read_validates_and_works_without_network(configured):
    app, http = configured
    app.config['GEOCODE_NETWORK_ENABLED'] = False
    store = GeocodeService.cache()
    store.set(GeocodeService.cache_key(ADDRESS), {'lat': 0, 'lon': 0, 'ignored': 'raw metadata'})
    assert GeocodeService.geocode(ADDRESS) == {'lat': 0.0, 'lon': 0.0}
    assert store.default_timeout == 43200 and store.max_entries == 256
    http.assert_not_called()


@pytest.mark.parametrize('lat,lon', [(90, 180), (-90, -180), (0, 0), (12.5, -20.5)])
def test_cache_inclusive_valid_coordinate_bounds(configured, lat, lon):
    _, http = configured
    GeocodeService.cache().set(GeocodeService.cache_key(ADDRESS), {'lat': lat, 'lon': lon})
    assert GeocodeService.geocode(ADDRESS) == {'lat': float(lat), 'lon': float(lon)}
    http.assert_not_called()


@pytest.mark.parametrize(
    'lat,lon',
    [
        (True, 1),
        (1, False),
        ('0', 1),
        (1, '0'),
        (91, 1),
        (1, 181),
        (-91, 1),
        (1, -181),
        (float('nan'), 0),
        (0, float('inf')),
        (None, 0),
    ],
)
def test_invalid_prepopulated_cache_is_discarded_not_treated_as_map(configured, lat, lon):
    app, http = configured
    app.config['GEOCODE_NETWORK_ENABLED'] = False
    key = GeocodeService.cache_key(ADDRESS)
    GeocodeService.cache().set(key, {'lat': lat, 'lon': lon})
    with pytest.raises(GeocodeError) as error:
        GeocodeService.geocode(ADDRESS)
    assert error.value.status_code == 503
    assert GeocodeService.cache().get(key) is None
    http.assert_not_called()


@pytest.mark.parametrize(
    'payload',
    [
        [],
        {},
        [None],
        [{'lat': True, 'lon': 0}],
        [{'lat': '91', 'lon': '0'}],
        [{'lat': '0', 'lon': '-181'}],
        [{'lat': 'NaN', 'lon': '0'}],
        [{'lat': '0', 'lon': '1e999'}],
        [{'lat': 0}],
        [{'lat': 1, 'lon': 2}, {'lat': 3, 'lon': 4}],
    ],
)
def test_empty_malformed_or_out_of_range_provider_results_never_cache_or_fallback(configured, payload):
    _, http = configured
    response = provider_response(http, payload)
    with pytest.raises(GeocodeError) as error:
        GeocodeService.geocode(ADDRESS)
    assert error.value.status_code == (404 if payload == [] else 503)
    assert GeocodeService.cache().get(GeocodeService.cache_key(ADDRESS)) is None
    http.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize(
    'failure', [requests.Timeout('q=1 Synthetic Test Street'), requests.ConnectionError('q=1 Synthetic Test Street')]
)
def test_provider_failure_is_friendly_private_and_not_retried(configured, failure, caplog):
    _, http = configured
    http.side_effect = failure
    with pytest.raises(GeocodeError) as error:
        GeocodeService.geocode(ADDRESS)
    assert error.value.status_code == 503
    assert ADDRESS not in str(error.value) and ADDRESS not in caplog.text
    assert GeocodeService.cache().get(GeocodeService.cache_key(ADDRESS)) is None
    http.assert_called_once()


@pytest.mark.parametrize('status', [301, 302, 403, 500, 503])
def test_provider_status_does_not_follow_redirect_or_fake_coordinates(configured, status):
    _, http = configured
    provider_response(http, status=status)
    with pytest.raises(GeocodeError) as error:
        GeocodeService.geocode(ADDRESS)
    assert error.value.status_code == 503
    http.assert_called_once()
    assert not GeocodeService.cache()._cache


def test_public_rate_gate_rejects_new_address_without_sleep_or_retry(configured, monkeypatch):
    _, http = configured
    provider_response(http)
    clock = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    GeocodeService.geocode(ADDRESS)
    with pytest.raises(GeocodeError) as error:
        GeocodeService.geocode('2 Synthetic Test Street')
    assert error.value.status_code == 429 and error.value.retry_after == 1
    assert GeocodeService.geocode(ADDRESS) == {'lat': 0.0, 'lon': 0.0}  # Positive cache bypasses provider gate.
    http.assert_called_once()
    clock[0] = 101.0
    GeocodeService.geocode('2 Synthetic Test Street')
    assert http.call_count == 2


def test_inflight_gate_is_process_global_across_app_instances(configured):
    _, http = configured
    with GeocodeService._provider_lock, pytest.raises(GeocodeError) as error:
        GeocodeService.geocode(ADDRESS)
    assert error.value.status_code == 429
    http.assert_not_called()


def test_provider_429_creates_bounded_cooldown_without_retry(configured, monkeypatch):
    _, http = configured
    monkeypatch.setattr(module.time, 'monotonic', lambda: 100.0)
    response = provider_response(http, status=429, headers={'Retry-After': '120'})
    with pytest.raises(GeocodeError) as error:
        GeocodeService.geocode(ADDRESS)
    assert error.value.status_code == 429 and error.value.retry_after == 120
    response.close.assert_called_once()
    with pytest.raises(GeocodeError) as next_error:
        GeocodeService.geocode('2 Synthetic Test Street')
    assert next_error.value.status_code == 429 and next_error.value.retry_after == 120
    http.assert_called_once()


@pytest.mark.parametrize(
    'retry_after',
    [
        '-1',
        'garbage',
        'Wed, 21 Oct 2030 07:28:00 GMT',
        '12345',
    ],
)
def test_invalid_retry_after_falls_back_and_closes_response(configured, monkeypatch, retry_after):
    _, http = configured
    monkeypatch.setattr(module.time, 'monotonic', lambda: 100.0)
    response = provider_response(http, status=429, headers={'Retry-After': retry_after})
    with pytest.raises(GeocodeError) as error:
        GeocodeService.geocode(ADDRESS)
    assert error.value.status_code == 429 and error.value.retry_after == 60
    assert GeocodeService._next_request_at == 160.0
    response.close.assert_called_once()
    http.assert_called_once()


@pytest.mark.parametrize('retry_after,expected', [('0', 1), ('9999', 3600)])
def test_numeric_retry_after_is_clamped_and_response_is_closed(configured, monkeypatch, retry_after, expected):
    _, http = configured
    monkeypatch.setattr(module.time, 'monotonic', lambda: 100.0)
    response = provider_response(http, status=429, headers={'Retry-After': retry_after})
    with pytest.raises(GeocodeError) as error:
        GeocodeService.geocode(ADDRESS)
    assert error.value.status_code == 429 and error.value.retry_after == expected
    assert GeocodeService._next_request_at == 100.0 + expected
    response.close.assert_called_once()


def test_positive_cache_expires_at_twelve_hours_and_is_size_bounded(configured, monkeypatch):
    app, http = configured
    app.config['GEOCODE_NETWORK_ENABLED'] = False
    clock = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    store = GeocodeService.cache()
    store.set(GeocodeService.cache_key(ADDRESS), {'lat': 0, 'lon': 0})
    clock[0] += 43199
    assert GeocodeService.geocode(ADDRESS)['lat'] == 0
    clock[0] += 1
    with pytest.raises(GeocodeError):
        GeocodeService.geocode(ADDRESS)
    for index in range(257):
        store.set(GeocodeService.cache_key(f'{index} Synthetic Test Street'), {'lat': 0, 'lon': 0})
    assert len(store._cache) == 256
    assert store.get(GeocodeService.cache_key('0 Synthetic Test Street')) is None
    http.assert_not_called()


@pytest.mark.parametrize('address', [None, True, 1, '', '  ', 'x' * 501, 'Synthetic\x00Street'])
def test_invalid_addresses_never_reach_http(configured, address):
    _, http = configured
    with pytest.raises(GeocodeError) as error:
        GeocodeService.geocode(address)
    assert error.value.status_code == 422
    http.assert_not_called()
