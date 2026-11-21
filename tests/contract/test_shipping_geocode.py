"""Shipping endpoint/template contracts: real owner service guards, fake rows, no DB/network."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest
import requests
from werkzeug.exceptions import Forbidden

from app.database import CaseInsensitiveRecord
from app.routes.shipping import shipping_bp
from app.services.geocode_service import GeocodeService
from app.services.order_service import OrderService


ROOT = Path(__file__).resolve().parents[2]
ADDRESS = '1 Synthetic Test Street'


@pytest.fixture
def shipping_app(app, monkeypatch):
    if 'shipping' not in app.blueprints:
        app.register_blueprint(shipping_bp)
    app.config.update(
        GEOCODE_ENABLED=True,
        GEOCODE_NETWORK_ENABLED=False,
        GEOCODE_ALLOW_PUBLIC_ADDRESS_QUERIES=False,
        GEOCODE_USER_AGENT='SyntheticMapTests/1.0',
        GEOCODE_CONTACT='maps@example.test',
    )
    http = Mock(side_effect=AssertionError('Unmocked geocode HTTP request'))
    monkeypatch.setattr('app.services.geocode_service.requests.get', http)
    monkeypatch.setattr(GeocodeService, '_next_request_at', 0.0)
    with app.app_context():
        GeocodeService.cache().set(GeocodeService.cache_key(ADDRESS), {'lat': 0.0, 'lon': 0.0})
    yield app, http


def fixture_order():
    return CaseInsensitiveRecord(
        OrderID=11,
        CustomerID=1,
        ShippingAddress=ADDRESS,
        Status='Pending',
        OrderDate=datetime(2026, 4, 2, 10),
        TotalAmount=Decimal('199000'),
        PaymentMethod='cod',
        CustomerName='Synthetic Customer',
        CustomerPhone='',
        CustomerEmail='customer@example.test',
        recipient_name='',
        recipient_phone='',
        recipient_email='',
        notes='Synthetic fixture',
    )


def test_owner_uses_actual_owner_scoped_order_query(auth_client, shipping_app, fake_db):
    fake_db.cursor.fetchone.return_value = fixture_order()
    fake_db.cursor.fetchall.return_value = []
    response = auth_client.get('/shipping/geocode/11')
    assert response.status_code == 200
    assert response.json == {
        'success': True,
        'lat': 0.0,
        'lon': 0.0,
        'approximate': True,
        'source': 'shipping_address',
        'attribution': '© OpenStreetMap contributors',
    }
    first = fake_db.cursor.execute.call_args_list[0]
    assert 'o.OrderID = %s AND o.CustomerID = %s' in first.args[0]
    assert first.args[1] == (11, 1)
    assert ADDRESS not in response.get_data(as_text=True)
    assert response.headers['Cache-Control'] == 'private, no-store, max-age=0'
    assert 'Cookie' in response.vary
    fake_db.connection.commit.assert_not_called()
    shipping_app[1].assert_not_called()


@pytest.mark.parametrize('order_id', [11, 999])
def test_foreign_and_nonexistent_id_are_indistinguishable(auth_client, shipping_app, fake_db, order_id):
    fake_db.cursor.fetchone.return_value = None
    response = auth_client.get(f'/shipping/geocode/{order_id}')
    assert response.status_code == 404
    assert response.json == {'success': False, 'message': 'Không tìm thấy đơn hàng.'}
    assert fake_db.cursor.execute.call_count == 1
    assert fake_db.cursor.execute.call_args.args[1] == (order_id, 1)
    assert response.headers['Cache-Control'].startswith('private, no-store')
    shipping_app[1].assert_not_called()


def test_admin_role_uses_actual_admin_order_query(admin_client, shipping_app, fake_db):
    fake_db.cursor.fetchone.return_value = fixture_order()
    fake_db.cursor.fetchall.return_value = []
    response = admin_client.get('/shipping/geocode/11')
    assert response.status_code == 200
    first = fake_db.cursor.execute.call_args_list[0]
    assert first.args[1] == (11,)
    assert 'AND o.CustomerID' not in first.args[0]
    shipping_app[1].assert_not_called()


def test_forged_is_admin_boolean_does_not_bypass_role_guard(auth_client, shipping_app, fake_db):
    with auth_client.session_transaction() as state:
        state['is_admin'] = True
    fake_db.cursor.fetchone.return_value = None
    response = auth_client.get('/shipping/geocode/11')
    assert response.status_code == 404
    assert fake_db.cursor.execute.call_args.args[1] == (11, 1)


def test_guest_always_gets_private_json_not_login_redirect(client, shipping_app, fake_db):
    response = client.get('/shipping/geocode/11')
    assert response.status_code == 401 and response.is_json
    assert 'Location' not in response.headers
    assert response.headers['Cache-Control'].startswith('private, no-store')
    fake_db.cursor.execute.assert_not_called()
    shipping_app[1].assert_not_called()


def test_blueprint_http_exception_is_safe_private_json(auth_client, shipping_app, fake_db, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise Forbidden('Synthetic internal detail')

    monkeypatch.setattr(OrderService, 'get_user_order_detail', forbidden)
    response = auth_client.get('/shipping/geocode/11')
    assert response.status_code == 403 and response.is_json
    assert response.json == {'success': False, 'message': 'Không thể xem vị trí theo địa chỉ.'}
    assert 'Synthetic internal detail' not in response.get_data(as_text=True)
    assert response.headers['Cache-Control'].startswith('private, no-store')
    assert 'Cookie' in response.vary
    fake_db.cursor.execute.assert_not_called()
    shipping_app[1].assert_not_called()


def test_disabled_feature_returns_503_even_with_positive_cache(auth_client, shipping_app, fake_db):
    shipping_app[0].config['GEOCODE_ENABLED'] = False
    fake_db.cursor.fetchone.return_value = fixture_order()
    response = auth_client.get('/shipping/geocode/11')
    assert response.status_code == 503 and response.json['success'] is False
    assert 'lat' not in response.json
    shipping_app[1].assert_not_called()


def test_arbitrary_query_or_provider_url_is_rejected_without_order_read(auth_client, shipping_app, fake_db):
    response = auth_client.get('/shipping/geocode/11?q=Synthetic&url=https://private.invalid')
    assert response.status_code == 400
    fake_db.cursor.execute.assert_not_called()
    shipping_app[1].assert_not_called()


def test_get_is_read_only_csrf_safe_without_exemption(auth_client, shipping_app, fake_db):
    shipping_app[0].config['WTF_CSRF_ENABLED'] = True
    fake_db.cursor.fetchone.return_value = fixture_order()
    fake_db.cursor.fetchall.return_value = []
    assert auth_client.get('/shipping/geocode/11').status_code == 200
    fake_db.connection.commit.assert_not_called()


def test_timeout_returns_503_not_placeholder_coordinates(auth_client, shipping_app, fake_db):
    app, http = shipping_app
    app.config.update(GEOCODE_NETWORK_ENABLED=True, GEOCODE_ALLOW_PUBLIC_ADDRESS_QUERIES=True)
    with app.app_context():
        GeocodeService.cache().clear()
    http.side_effect = requests.Timeout('Synthetic provider timeout')
    fake_db.cursor.fetchone.return_value = fixture_order()
    response = auth_client.get('/shipping/geocode/11')
    assert response.status_code == 503 and response.json['success'] is False
    assert 'lat' not in response.json and ADDRESS not in response.get_data(as_text=True)
    http.assert_called_once()


def test_existing_limiter_decorator_enforces_five_per_minute(monkeypatch):
    from app import create_app, limiter
    from tests.conftest import TestConfig, sign_in

    config = {key: getattr(TestConfig, key) for key in dir(TestConfig) if key.isupper()}
    config.update(
        RATELIMIT_ENABLED=True,
        RATELIMIT_STORAGE_URI='memory://',
        GEOCODE_ENABLED=True,
        GEOCODE_NETWORK_ENABLED=False,
        GEOCODE_USER_AGENT='SyntheticMapTests/1.0',
        GEOCODE_CONTACT='maps@example.test',
    )
    app = create_app(config)
    if 'shipping' not in app.blueprints:
        app.register_blueprint(shipping_bp)
    monkeypatch.setattr(
        OrderService, 'get_user_order_detail', lambda order_id, user_id: {'order': fixture_order(), 'items': []}
    )
    http = Mock(side_effect=AssertionError('Rate test must never geocode externally'))
    monkeypatch.setattr('app.services.geocode_service.requests.get', http)
    try:
        with app.app_context():
            limiter.reset()
            GeocodeService.cache().set(GeocodeService.cache_key(ADDRESS), {'lat': 0, 'lon': 0})
        client = sign_in(app.test_client())
        for _ in range(5):
            assert client.get('/shipping/geocode/11').status_code == 200
        response = client.get('/shipping/geocode/11')
        assert response.status_code == 429
        assert response.is_json and response.json['success'] is False
        assert response.headers['Retry-After'] == '60'
        assert response.headers['Cache-Control'].startswith('private, no-store')
        http.assert_not_called()
    finally:
        handlers = app.extensions.get('chat_socket_handlers')
        if handlers is not None:
            handlers.close()


def test_template_configured_opt_in_local_assets_caption_and_privacy(auth_client, shipping_app, fake_db):
    fake_db.cursor.fetchone.return_value = fixture_order()
    fake_db.cursor.fetchall.return_value = []
    response = auth_client.get('/order/11')
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    section = soup.select_one('#shipping-address-map')
    assert section is not None and section['data-geocode-url'] == '/shipping/geocode/11'
    assert section.select_one('[data-map-show]').text == 'Hiển thị vị trí theo địa chỉ'
    assert section.select_one('[data-map-canvas]').has_attr('hidden')
    assert 'Vị trí ước tính từ địa chỉ, không phải theo dõi đơn vị vận chuyển' in section.text
    assert 'OpenStreetMap' in section.text and 'vùng tọa độ' in section.text
    assert 'Tra cứu địa chỉ bên ngoài đang tắt' in section.text
    assert soup.select_one('script[src="/static/vendor/leaflet/leaflet.js"]') is not None
    assert soup.select_one('script[src="/static/js/order-map.js"]') is not None
    assert not section.select('iframe')
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert response.headers['Referrer-Policy'] == 'same-origin'
    shipping_app[1].assert_not_called()


@pytest.mark.parametrize('key', ['GEOCODE_ENABLED', 'GEOCODE_USER_AGENT', 'GEOCODE_CONTACT'])
def test_unconfigured_map_button_and_assets_are_absent(auth_client, shipping_app, fake_db, key):
    shipping_app[0].config[key] = False if key == 'GEOCODE_ENABLED' else None
    fake_db.cursor.fetchone.return_value = fixture_order()
    fake_db.cursor.fetchall.return_value = []
    response = auth_client.get('/order/11')
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('#shipping-address-map') is None
    assert soup.select_one('script[src*="leaflet"]') is None
    assert ADDRESS in soup.text
    shipping_app[1].assert_not_called()


def test_map_script_only_uses_fixed_tiles_canonical_fetch_and_safe_text():
    script = (ROOT / 'app/static/js/order-map.js').read_text(encoding='utf-8')
    assert "button.addEventListener('click', async" in script
    assert 'https://tile.openstreetmap.org/{z}/{x}/{y}.png' in script
    assert "referrerPolicy: 'origin'" in script
    assert 'Number.isFinite(data.lat)' in script and 'Number.isFinite(data.lon)' in script
    assert "redirect: 'error'" in script and "credentials: 'same-origin'" in script
    assert 'popup.textContent = caption' in script
    assert 'innerHTML' not in script and 'iframe' not in script and 'display_name' not in script
    assert "window.addEventListener('pagehide', clearMap)" in script
    assert (ROOT / 'app/static/vendor/leaflet/leaflet.js').exists()


@pytest.mark.parametrize(
    'path',
    [
        '/static/vendor/leaflet/leaflet.js',
        '/static/vendor/leaflet/leaflet.css',
        '/static/vendor/leaflet/images/marker-icon.png',
        '/static/vendor/leaflet/images/marker-shadow.png',
        '/static/js/order-map.js',
        '/static/css/order-map.css',
    ],
)
def test_all_map_assets_are_served_locally_without_external_requests(client, shipping_app, path):
    response = client.get(path)
    try:
        assert response.status_code == 200
        assert response.data
        assert 'Location' not in response.headers
        shipping_app[1].assert_not_called()
    finally:
        response.close()


def test_nonshipping_routes_keep_existing_private_header_policy(auth_client, shipping_app, fake_db):
    fake_db.cursor.fetchone.return_value = fixture_order()
    fake_db.cursor.fetchall.return_value = []
    response = auth_client.get('/order/11')
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('order_id', [0, 2147483648])
def test_invalid_integer_ids_are_safe_private_json_404(auth_client, shipping_app, fake_db, order_id):
    response = auth_client.get(f'/shipping/geocode/{order_id}')
    assert response.status_code == 404 and response.is_json
    assert response.json == {'success': False, 'message': 'Không tìm thấy đơn hàng.'}
    fake_db.cursor.execute.assert_not_called()
    shipping_app[1].assert_not_called()


def test_database_failure_returns_safe_private_json_503(auth_client, shipping_app, fake_db, caplog):
    import psycopg2

    fake_db.cursor.execute.side_effect = psycopg2.OperationalError('Synthetic failure')
    response = auth_client.get('/shipping/geocode/11')
    assert response.status_code == 503 and response.is_json
    assert 'lat' not in response.json and ADDRESS not in response.get_data(as_text=True)
    assert 'Synthetic failure' not in caplog.text
    shipping_app[1].assert_not_called()
