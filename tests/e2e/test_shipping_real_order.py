from pathlib import Path

import pytest
from playwright.sync_api import expect

from app.services.geocode_service import GeocodeService
from tests.e2e.test_customer_admin import login


pytestmark = pytest.mark.e2e


def test_real_order_owner_uses_explicit_cached_map_without_external_address_lookup(gui_page, live_app, db_connection):
    page = gui_page
    application = live_app[1]
    application.config.update(
        TESTING=True,
        GEOCODE_ENABLED=True,
        GEOCODE_NETWORK_ENABLED=False,
        GEOCODE_ALLOW_PUBLIC_ADDRESS_QUERIES=False,
        GEOCODE_USER_AGENT='SyntheticRealOrderMap/1.0',
        GEOCODE_CONTACT='maps@example.test',
    )
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT ShippingAddress FROM Orders WHERE OrderID=1 AND CustomerID=1')
        address = cursor.fetchone().ShippingAddress
    with application.app_context():
        GeocodeService.cache().set(GeocodeService.cache_key(address), {'lat': 10.0, 'lon': 106.0}, timeout=43200)
    external_queries = []
    page.on('request', lambda request: external_queries.append(request.url) if 'nominatim' in request.url else None)
    tile = Path(__file__).resolve().parents[2] / 'app' / 'static' / 'images' / 'default.jpg'
    page.route(
        'https://tile.openstreetmap.org/**', lambda route: route.fulfill(path=str(tile), content_type='image/jpeg')
    )
    login(page)
    page.goto('/my_account#orders')
    page.locator('a[href="/order/1"]').click()
    page.wait_for_function('() => typeof window.L !== "undefined"')
    expect(page.locator('#shipping-map-canvas')).not_to_be_visible()
    page.get_by_role('button', name='Hiển thị vị trí theo địa chỉ', exact=True).click()
    expect(page.locator('#shipping-map-canvas')).to_be_visible()
    expect(page.locator('.leaflet-marker-icon')).to_have_attribute('alt', 'Vị trí ước tính của địa chỉ nhận hàng')
    expect(page.locator('[data-map-status]')).to_contain_text('không phải theo dõi đơn vị vận chuyển')
    assert external_queries == []
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT ShippingAddress FROM Orders WHERE OrderID=1')
        assert cursor.fetchone().ShippingAddress == address
    page.get_by_role('button', name='Ẩn bản đồ', exact=True).click()
    expect(page.locator('#shipping-map-canvas')).not_to_be_visible()
    assert not page.test_errors, page.test_errors
