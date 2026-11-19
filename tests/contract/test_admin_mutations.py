from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.services.attribute_service import AttributeService
from app.services.product_service import ProductService
from app.services.order_service import OrderService
from app.validation import ValidationError


PRODUCT = {
    'product_name': 'Test Product',
    'description': 'Test',
    'price': '123.45',
    'original_price': '150.00',
    'category_id': '1',
}


@pytest.mark.parametrize('path', ['/admin/products/add', '/admin/products/manage'])
@pytest.mark.parametrize(
    'outcome', [{'success': True, 'product_id': 4}, {'success': False, 'message': 'Product failed'}]
)
def test_admin_product_create_routes_pass_exact_money(admin_client, monkeypatch, path, outcome):
    create = MagicMock(return_value=outcome)
    monkeypatch.setattr(ProductService, 'add_product', create)
    response = admin_client.post(path, data=PRODUCT)
    assert response.status_code == 302
    assert create.call_args.args[2] == Decimal('123.45')
    assert create.call_args.args[4] == Decimal('150.00')


@pytest.mark.parametrize(
    'invalid',
    [
        {'product_name': ''},
        {'price': 'NaN'},
        {'price': '1.001'},
        {'original_price': '1'},
        {'description': '\x00'},
        {'category_id': 'x'},
    ],
)
@pytest.mark.parametrize('path', ['/admin/products/add', '/admin/products/manage'])
def test_admin_product_invalid_does_not_write(admin_client, monkeypatch, path, invalid):
    create = MagicMock()
    monkeypatch.setattr(ProductService, 'add_product', create)
    assert admin_client.post(path, data={**PRODUCT, **invalid}).status_code == 302
    create.assert_not_called()


@pytest.mark.parametrize(
    'path,service,field',
    [('/admin/colors/add', 'add_color', 'color_name'), ('/admin/sizes/add', 'add_size', 'size_name')],
)
@pytest.mark.parametrize('value', ['Test Value', ''])
def test_admin_attribute_add_reports_validation_and_success(admin_client, monkeypatch, path, service, field, value):
    call = MagicMock(return_value={'success': True})
    if not value:
        call.side_effect = ValidationError('Invalid name')
    monkeypatch.setattr(AttributeService, service, call)
    assert admin_client.post(path, data={field: value}).status_code == 302
    call.assert_called_once()


@pytest.mark.parametrize(
    'path,service', [('/admin/colors/delete/9', 'delete_color'), ('/admin/sizes/delete/9', 'delete_size')]
)
def test_admin_attribute_delete_uses_record_id(admin_client, monkeypatch, path, service):
    call = MagicMock(return_value={'success': False, 'message': 'Referenced'})
    monkeypatch.setattr(AttributeService, service, call)
    assert admin_client.post(path).status_code == 302
    call.assert_called_once_with(9)


@pytest.mark.parametrize('with_product', [True, False])
def test_admin_variant_delete_redirect_is_local(admin_client, monkeypatch, with_product):
    remove = MagicMock(return_value={'success': True})
    monkeypatch.setattr(ProductService, 'delete_variant', remove)
    response = admin_client.post(
        '/admin/variants/delete/9',
        data={'product_id': '1' if with_product else 'bad'},
        headers={'Referer': 'https://evil.test'},
    )
    assert response.status_code == 302
    assert response.headers['Location'].startswith('/admin/')
    remove.assert_called_once_with(9)


@pytest.mark.parametrize('status', ['Processing', 'Invalid', ''])
def test_admin_status_update_validates_before_service(admin_client, monkeypatch, status):
    update = MagicMock(return_value={'success': True})
    monkeypatch.setattr(OrderService, 'update_order_status', update)
    response = admin_client.post('/admin/orders/update_status', data={'order_id': '2', 'status': status})
    assert response.status_code == 302
    if status == 'Processing':
        update.assert_called_once_with(2, 'Processing')
    else:
        update.assert_not_called()


def test_admin_status_service_conflict_returns_error_flash(admin_client, monkeypatch):
    monkeypatch.setattr(
        OrderService, 'update_order_status', lambda *_: {'success': False, 'message': 'Order is terminal'}
    )
    response = admin_client.post('/admin/orders/update_status', data={'order_id': '2', 'status': 'Processing'})
    assert response.status_code == 302
    with admin_client.session_transaction() as session:
        assert any('terminal' in message for _, message in session.get('_flashes', []))


def test_admin_product_delete_conflict_preserves_route(admin_client, monkeypatch):
    monkeypatch.setattr(ProductService, 'delete_product', lambda _: {'success': False, 'message': 'Order history'})
    response = admin_client.post('/admin/products/delete/1')
    assert response.headers['Location'] == '/admin/products/manage'


def test_admin_variant_zero_stock_is_supported(admin_client, monkeypatch):
    add = MagicMock(return_value={'success': True})
    monkeypatch.setattr(ProductService, 'add_variant', add)
    response = admin_client.post(
        '/admin/products/add_variant', data={'product_id': '1', 'color_id': '1', 'size_id': '1', 'quantity': '0'}
    )
    assert response.status_code == 302
    add.assert_called_once_with(1, 1, 1, 0)
