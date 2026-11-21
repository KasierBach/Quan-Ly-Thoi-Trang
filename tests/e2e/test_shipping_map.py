"""Authored-only browser contracts: synthetic orders, DB disabled, no external network.

These tests intentionally use neutral locally fulfilled tiles. Passing them is
not evidence of a real online map or live geocoding/carrier integration.
"""

import base64
from datetime import datetime
from decimal import Decimal
import threading
from urllib.parse import urlsplit
from unittest.mock import Mock

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from app import create_app
from app.database import CaseInsensitiveRecord
from app.routes.shipping import shipping_bp
from app.services.geocode_service import GeocodeService
from app.services.order_service import OrderService
from tests.conftest import TestConfig
from tests.e2e.stream_cleanup import CloseOnExhaustion


pytestmark = pytest.mark.e2e
ADDRESS = '1 Synthetic Test Street'  # Same spelling as db/seed_test.sql; never a real address.
NEUTRAL_TILE = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
)


@pytest.fixture
def shipping_map_server(monkeypatch):
    # No database fixtures, schema mutations, real credentials or geocode calls.
    config = {key: getattr(TestConfig, key) for key in dir(TestConfig) if key.isupper()}
    config.update(
        GEOCODE_ENABLED=True,
        GEOCODE_NETWORK_ENABLED=False,
        GEOCODE_ALLOW_PUBLIC_ADDRESS_QUERIES=False,
        GEOCODE_USER_AGENT='SyntheticMapTests/1.0',
        GEOCODE_CONTACT='maps@example.test',
    )
    application = create_app(config)
    if 'shipping' not in application.blueprints:
        application.register_blueprint(shipping_bp)
    order = CaseInsensitiveRecord(
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
    monkeypatch.setattr(
        OrderService,
        'get_user_order_detail',
        lambda order_id, user_id: {'order': order, 'items': []} if (order_id, user_id) == (11, 1) else None,
    )
    http = Mock(side_effect=AssertionError('Browser map tests must never call a provider'))
    monkeypatch.setattr('app.services.geocode_service.requests.get', http)
    monkeypatch.setattr('requests.sessions.Session.request', Mock(side_effect=AssertionError('External HTTP disabled')))
    with application.app_context():
        GeocodeService.cache().set(GeocodeService.cache_key(ADDRESS), {'lat': 0.0, 'lon': 0.0})
        state = application.session_interface.get_signing_serializer(application)
        signed_session = state.dumps(
            {'user_id': 1, 'user_name': 'Synthetic Customer', 'role': 'customer', 'auth_version': 1}
        )

    def serve(environ, start_response):
        return CloseOnExhaustion(application(environ, start_response))

    server = make_server('127.0.0.1', 0, serve, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', application, signed_session
        http.assert_not_called()
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
        handlers = application.extensions.get('chat_socket_handlers')
        if handlers is not None:
            handlers.close()


@pytest.fixture
def shipping_map_page(browser, shipping_map_server):
    base_url, application, signed_session = shipping_map_server
    context = browser.new_context(base_url=base_url, viewport={'width': 390, 'height': 844})
    context.add_cookies([{'name': application.config['SESSION_COOKIE_NAME'], 'value': signed_session, 'url': base_url}])
    context.route('https://**/*', lambda route: route.abort())
    # Fulfillment is local and neutral, not a real-world map tile assertion.
    tiles = []

    def local_tile(route):
        tiles.append(route.request.url)
        route.fulfill(status=200, content_type='image/png', body=NEUTRAL_TILE)

    context.route('https://tile.openstreetmap.org/**', local_tile)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        yield page, tiles, errors
    finally:
        context.close()


def test_explicit_click_reads_synthetic_positive_cache_and_local_neutral_tiles(shipping_map_page):
    page, tiles, errors = shipping_map_page
    lookups = []
    page.on('request', lambda request: lookups.append(request.url) if '/shipping/geocode/' in request.url else None)
    page.goto('/order/11')
    page.wait_for_function('() => typeof window.L !== "undefined"')
    button = page.get_by_role('button', name='Hiển thị vị trí theo địa chỉ', exact=True)
    expect(button).to_be_visible()
    expect(page.locator('#shipping-map-canvas')).to_be_hidden()
    assert lookups == [] and tiles == []
    expect(page.locator('#shipping-address-map')).to_contain_text('Tra cứu địa chỉ bên ngoài đang tắt')
    with page.expect_response(lambda response: urlsplit(response.url).path == '/shipping/geocode/11') as result:
        button.click()
    assert result.value.status == 200
    assert result.value.json()['source'] == 'shipping_address'
    assert result.value.json()['lat'] == 0.0
    expect(page.locator('#shipping-map-canvas')).to_be_visible()
    expect(page.locator('.leaflet-marker-icon')).to_have_attribute('alt', 'Vị trí ước tính của địa chỉ nhận hàng')
    expect(page.locator('.leaflet-control-attribution')).to_contain_text('OpenStreetMap')
    expect(page.locator('[data-map-status]')).to_have_text(
        'Vị trí ước tính từ địa chỉ, không phải theo dõi đơn vị vận chuyển'
    )
    page.wait_for_function('() => document.querySelector(".leaflet-tile-loaded") !== null')
    assert len(lookups) == 1 and tiles
    assert all('Synthetic' not in url and not urlsplit(url).query for url in tiles)
    assert page.locator('iframe').count() == 0
    assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth')
    page.get_by_role('button', name='Ẩn bản đồ', exact=True).click()
    expect(page.locator('#shipping-map-canvas')).to_be_hidden()
    expect(button).to_be_focused()
    assert not errors


def test_disabled_configuration_hides_map_without_network(shipping_map_page, shipping_map_server):
    page, tiles, errors = shipping_map_page
    shipping_map_server[1].config['GEOCODE_ENABLED'] = False
    page.goto('/order/11')
    expect(page.get_by_role('button', name='Hiển thị vị trí theo địa chỉ', exact=True)).to_have_count(0)
    expect(page.locator('#shipping-address-map')).to_have_count(0)
    expect(page.get_by_text(ADDRESS, exact=True)).to_be_visible()
    assert tiles == [] and not errors


@pytest.mark.parametrize('status', [429, 503])
def test_friendly_errors_leave_no_map_and_allow_manual_retry(shipping_map_page, status):
    page, tiles, errors = shipping_map_page
    page.route(
        '**/shipping/geocode/11',
        lambda route: route.fulfill(
            status=status,
            content_type='application/json',
            body='{"success":false,"message":"Synthetic failure"}',
        ),
    )
    page.goto('/order/11')
    page.wait_for_function('() => typeof window.L !== "undefined"')
    button = page.get_by_role('button', name='Hiển thị vị trí theo địa chỉ', exact=True)
    button.click()
    expect(page.locator('[data-map-status]')).to_contain_text('Vui lòng thử lại sau')
    expect(button).to_be_enabled()
    expect(page.locator('#shipping-map-canvas')).to_be_hidden()
    assert tiles == [] and not errors


def test_missing_cached_point_does_not_fabricate_coordinates(shipping_map_page, shipping_map_server):
    page, tiles, errors = shipping_map_page
    with shipping_map_server[1].app_context():
        GeocodeService.cache().clear()
    page.goto('/order/11')
    page.wait_for_function('() => typeof window.L !== "undefined"')
    with page.expect_response(lambda response: urlsplit(response.url).path == '/shipping/geocode/11') as result:
        page.get_by_role('button', name='Hiển thị vị trí theo địa chỉ', exact=True).click()
    assert result.value.status == 503 and 'lat' not in result.value.json()
    expect(page.locator('#shipping-map-canvas')).to_be_hidden()
    assert tiles == [] and not errors


def test_tile_failure_is_not_presented_as_a_real_online_map(shipping_map_page):
    page, _, errors = shipping_map_page
    page.route('https://tile.openstreetmap.org/**', lambda route: route.abort())
    page.goto('/order/11')
    page.wait_for_function('() => typeof window.L !== "undefined"')
    page.get_by_role('button', name='Hiển thị vị trí theo địa chỉ', exact=True).click()
    expect(page.locator('[data-map-status]')).to_contain_text('không tải được nền bản đồ')
    assert not errors
