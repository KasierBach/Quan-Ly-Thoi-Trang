from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import psycopg2
import pytest

from app.database import CaseInsensitiveRecord
from app.services.auth_service import AuthService
from app.services.cart_service import CartService
from app.services.category_service import CategoryService
from app.services.feedback_service import FeedbackService
from app.services.order_service import OrderService
from app.services.product_service import ProductService
from app.services.wishlist_service import WishlistService
from app.validation import ValidationError
import app.routes.cart as cart_routes


ROOT = Path(__file__).resolve().parents[2]


def record(**values):
    return CaseInsensitiveRecord(values)


@pytest.fixture
def catalog(monkeypatch):
    products = {
        1: record(
            ProductID=1,
            ProductName='Áo chính',
            Description='Mô tả thật <script>alert(1)</script>',
            CategoryID=1,
            CategoryName='Áo',
            Price=Decimal('0.10'),
            OriginalPrice=Decimal('0.20'),
            ImageURL='images/1.jpg',
            AverageRating=0,
            ReviewCount=0,
        ),
        2: record(
            ProductID=2,
            ProductName='Mua ngay',
            Description='Thật',
            CategoryID=1,
            CategoryName='Áo',
            Price=Decimal('0.20'),
            OriginalPrice=Decimal('0.00'),
            ImageURL='images/2.jpg',
            AverageRating=0,
            ReviewCount=0,
        ),
    }
    variants = {
        1: record(
            VariantID=1,
            ProductID=1,
            ProductName='Áo chính',
            Price=Decimal('0.10'),
            Quantity=5,
            ColorID=1,
            ColorName='Đen',
            SizeID=1,
            SizeName='M',
            ImageURL='images/1.jpg',
        ),
        2: record(
            VariantID=2,
            ProductID=2,
            ProductName='Mua ngay',
            Price=Decimal('0.20'),
            Quantity=3,
            ColorID=1,
            ColorName='Đen',
            SizeID=1,
            SizeName='M',
            ImageURL='images/2.jpg',
        ),
        3: record(
            VariantID=3,
            ProductID=1,
            ProductName='Áo chính',
            Price=Decimal('0.10'),
            Quantity=0,
            ColorID=2,
            ColorName='Trắng',
            SizeID=1,
            SizeName='M',
            ImageURL='images/1.jpg',
        ),
    }
    monkeypatch.setattr(ProductService, 'get_variant_detail', lambda vid: variants.get(vid))
    monkeypatch.setattr(OrderService, 'get_checkout_order', lambda *_: None)
    monkeypatch.setattr(ProductService, 'get_product_by_id', lambda pid: products.get(pid))
    monkeypatch.setattr(
        ProductService, 'get_product_variants', lambda pid: [v for v in variants.values() if v.ProductID == pid]
    )
    monkeypatch.setattr(
        ProductService,
        'get_variant_by_details',
        lambda pid, cid, sid: next(
            (v for v in variants.values() if (v.ProductID, v.ColorID, v.SizeID) == (pid, cid, sid)), None
        ),
    )
    monkeypatch.setattr(CategoryService, 'get_all_categories', lambda: [record(CategoryID=1, CategoryName='Áo')])
    monkeypatch.setattr(ProductService, 'get_all_colors', lambda: [record(ColorID=1, ColorName='Đen')])
    monkeypatch.setattr(ProductService, 'get_all_sizes', lambda: [record(SizeID=1, SizeName='M')])
    monkeypatch.setattr(
        AuthService,
        'get_customer_profile',
        lambda _: record(FullName='Khách hàng', PhoneNumber='0900000001', Email='one@example.test', Address='Address'),
    )
    monkeypatch.setattr(
        FeedbackService,
        'get_product_reviews',
        lambda _: {
            'success': True,
            'reviews': [],
            'total_reviews': 0,
            'average_rating': 0,
            'rating_breakdown': {},
        },
    )
    monkeypatch.setattr(FeedbackService, 'get_product_comments', lambda _: {'success': True, 'comments': []})
    return variants, products


def set_cart(client, items, key='cart'):
    with client.session_transaction() as state:
        state[key] = items


def checkout_fields(**overrides):
    data = dict(
        shipping_address='Address',
        full_name='Recipient',
        phone='0900000001',
        email='one@example.test',
        payment_method=OrderService.PAYMENT_METHOD,
        shipping_method='standard',
        order_notes='note',
    )
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    'path,data',
    [
        ('/add_to_cart', {'variant_id': 1, 'quantity': '0'}),
        ('/add_to_cart', {'variant_id': '-1', 'quantity': '1'}),
        ('/add_to_cart', {'variant_id': 1, 'quantity': '1.2'}),
        ('/add_to_cart', {'variant_id': 1, 'quantity': '9' * 5000}),
        ('/buy_now', {'variant_id': 1, 'quantity': '-1'}),
        ('/update_cart', {'variant_id': 1}),
        ('/update_cart', {'variant_id': 'bad', 'quantity': 1}),
        ('/remove_from_cart', {'variant_id': 0}),
        ('/api/get_variant', {'product_id': 1, 'color_id': -2, 'size_id': 1}),
        ('/api/track_product_view', {'product_id': '-1'}),
    ],
)
def test_mutations_return_json_400_for_invalid_integers(client, catalog, path, data):
    response = client.post(path, data=data, headers={'Accept': 'application/json'})
    assert response.status_code == 400
    assert response.is_json and response.json['success'] is False


@pytest.mark.parametrize('path', ['/update_cart', '/remove_from_cart', '/add_to_wishlist'])
@pytest.mark.parametrize('payload', [None, [], 'text', 1, True])
def test_nonobject_json_never_crashes_or_mutates(auth_client, catalog, path, payload):
    response = auth_client.post(path, data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 400 and response.json['success'] is False


def test_accumulated_cart_quantity_cannot_exceed_stock(client, catalog):
    set_cart(client, [{'variant_id': 1, 'quantity': 4, 'price': '999'}])
    response = client.post(
        '/add_to_cart', data={'variant_id': 1, 'quantity': 2}, headers={'Accept': 'application/json'}
    )
    assert response.status_code == 409 and response.json['success'] is False
    with client.session_transaction() as state:
        assert state['cart'][0]['quantity'] == 4


def test_cart_add_rehydrates_exact_price_and_merges_duplicate_session_rows(client, catalog):
    set_cart(client, [{'variant_id': 1, 'quantity': 1, 'price': '99'}, {'variant_id': 1, 'quantity': 1, 'price': '-1'}])
    response = client.post(
        '/add_to_cart', data={'variant_id': 1, 'quantity': 1}, headers={'Accept': 'application/json'}
    )
    assert response.status_code == 200 and response.json['total'] == '0.30'
    assert response.json['cart_count'] == 3 and response.json['item_count'] == 1
    assert response.json['items'][0]['price'] == '0.10'
    with client.session_transaction() as state:
        assert 'cart' not in state
        assert CartService.load(state['cart_id'])[1] == [{'variant_id': 1, 'quantity': 3}]


def test_update_cart_returns_authoritative_subtotal_after_manual_quantity(client, catalog):
    set_cart(client, [{'variant_id': 1, 'quantity': 2, 'price': '99'}])
    response = client.post('/update_cart', data={'variant_id': 1, 'quantity': 4})
    assert response.status_code == 200
    assert response.json['price'] == '0.10' and response.json['subtotal'] == '0.40'
    assert response.json['quantity'] == 4 and response.json['total'] == '0.40'
    assert response.json['items'][0]['subtotal'] == '0.40'
    with client.session_transaction() as state:
        assert CartService.load(state['cart_id'])[1][0]['quantity'] == 4


@pytest.mark.parametrize('path', ['/update_cart', '/remove_from_cart'])
def test_missing_cart_item_is_not_false_success(client, catalog, path):
    response = client.post(path, data={'variant_id': 2, 'quantity': 1})
    assert response.status_code == 404 and response.json['success'] is False


def test_cart_stock_change_is_rejected_without_losing_previous_quantity(client, catalog):
    set_cart(client, [{'variant_id': 1, 'quantity': 2, 'price': '0.10'}])
    response = client.post('/update_cart', data={'variant_id': 1, 'quantity': 6})
    assert response.status_code == 409
    with client.session_transaction() as state:
        assert state['cart'][0]['quantity'] == 2


def test_zero_price_item_removal_reports_item_count_not_zero_total(client, catalog):
    variants, _ = catalog
    variants[1].Price = Decimal('0')
    set_cart(client, [{'variant_id': 1, 'quantity': 1}, {'variant_id': 2, 'quantity': 1}])
    response = client.post('/remove_from_cart', data={'variant_id': 2})
    assert response.status_code == 200 and response.json['total'] == '0.00'
    assert response.json['item_count'] == 1


def test_html_cart_add_referrer_is_local_and_has_fallback(client, catalog):
    response = client.post(
        '/add_to_cart', data={'variant_id': 1}, headers={'Referer': 'https://evil.example.test/steal'}
    )
    assert response.status_code == 302 and response.location == '/product/1'
    response = client.post('/add_to_cart', data={'variant_id': 1}, headers={'Referer': 'http://localhost/product/1'})
    assert response.location == '/product/1'


def reviewed_checkout_fields(client, checkout_url='/checkout', **overrides):
    page = client.get(checkout_url)
    assert page.status_code == 200
    soup = BeautifulSoup(page.data, 'html.parser')
    return checkout_fields(checkout_review=soup.select_one('[name=checkout_review]')['value'], **overrides)


def test_buy_now_only_orders_its_draft_and_preserves_normal_cart(auth_client, catalog, monkeypatch):
    set_cart(auth_client, [{'variant_id': 1, 'quantity': 2}])
    start = auth_client.post('/buy_now', data={'variant_id': 2, 'quantity': 3})
    assert start.location.startswith('/checkout?buy_now=1&draft=')
    fields = reviewed_checkout_fields(auth_client, start.location, buy_now='1')
    other = auth_client.post('/buy_now', data={'variant_id': 1, 'quantity': 1})
    assert other.location != start.location
    submit = Mock(return_value={'success': True, 'order_id': 10})
    monkeypatch.setattr(OrderService, 'create_order', submit)
    response = auth_client.post(start.location, data=fields)
    assert response.status_code == 302 and response.location == '/order_confirmation/10'
    assert submit.call_args.args[3][0]['variant_id'] == 2
    assert submit.call_args.args[3][0]['quantity'] == 3
    assert submit.call_args.kwargs['recipient_name'] == 'Recipient'
    with auth_client.session_transaction() as state:
        assert 'temp_cart' not in state
        assert state['cart'][0]['variant_id'] == 1


def test_buy_now_validation_failure_renders_same_mode_and_entered_fields(auth_client, catalog, monkeypatch):
    start = auth_client.post('/buy_now', data={'variant_id': 2, 'quantity': 1})
    monkeypatch.setattr(
        OrderService,
        'create_order',
        Mock(
            return_value={
                'success': False,
                'message': 'Địa chỉ không hợp lệ',
                'status_code': 400,
            }
        ),
    )
    fields = reviewed_checkout_fields(auth_client, start.location, buy_now='1', shipping_address='Kept input')
    response = auth_client.post(start.location, data=fields)
    assert response.status_code == 400
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('#checkoutForm')['action'] == start.location
    assert soup.select_one('[name=shipping_address]').get_text() == 'Kept input'
    assert 'Mua ngay' in soup.get_text()


def test_checkout_keeps_delivery_fields_and_refreshes_review_after_transaction_conflict(
    auth_client, catalog, monkeypatch
):
    variants, _ = catalog
    auth_client.post('/add_to_cart', data={'variant_id': 1})
    fields = reviewed_checkout_fields(auth_client, shipping_address='Alternate Address', order_notes='Call first')

    def price_changes(*args, **kwargs):
        variants[1].Price = Decimal('1.50')
        return {'success': False, 'message': 'Giá đã thay đổi', 'status_code': 409}

    monkeypatch.setattr(OrderService, 'create_order', price_changes)
    response = auth_client.post('/checkout', data=fields)
    assert response.status_code == 409
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('[name=shipping_address]').get_text() == 'Alternate Address'
    assert soup.select_one('[name=order_notes]').get_text() == 'Call first'
    fields['checkout_review'] = soup.select_one('[name=checkout_review]')['value']

    submit = Mock(return_value={'success': True, 'order_id': 10})
    monkeypatch.setattr(OrderService, 'create_order', submit)
    assert auth_client.post('/checkout', data=fields).location == '/order_confirmation/10'
    assert submit.call_args.kwargs['reviewed_prices'] == {1: '1.50'}


def test_guest_buy_now_drafts_from_same_session_survive_sign_in(app, client, catalog, monkeypatch):
    client.get('/login')
    second_tab = app.test_client()
    second_tab.set_cookie('session', client.get_cookie('session').value)
    first_draft = client.post('/buy_now', data={'variant_id': 1}).location
    second_draft = second_tab.post('/buy_now', data={'variant_id': 2}).location
    client.set_cookie('session', second_tab.get_cookie('session').value)

    login = client.get(first_draft)
    next_page = parse_qs(urlsplit(login.location).query)['next'][0]
    assert next_page == first_draft
    monkeypatch.setattr(
        AuthService,
        'login_user',
        lambda *_: record(CustomerID=1, FullName='Buyer', Role='customer', AuthVersion=1, DarkModeEnabled=False),
    )
    signed_in = client.post('/login', data={'email': 'buyer@example.test', 'password': 'TestPass1!', 'next': next_page})
    assert signed_in.location == first_draft
    first_page = client.get(first_draft).get_data(as_text=True)
    second_page = client.get(second_draft).get_data(as_text=True)
    assert 'Áo chính' in first_page and 'Mua ngay' in second_page


@pytest.mark.parametrize('changed', ['price', 'quantity'])
def test_checkout_requires_reconfirmation_when_reviewed_order_changes(auth_client, catalog, monkeypatch, changed):
    variants, _ = catalog
    auth_client.post('/add_to_cart', data={'variant_id': 1})
    fields = reviewed_checkout_fields(auth_client)
    if changed == 'price':
        variants[1].Price = Decimal('1.50')
    else:
        auth_client.post('/update_cart', data={'variant_id': 1, 'quantity': 2})

    submit = Mock(return_value={'success': True, 'order_id': 10})
    monkeypatch.setattr(OrderService, 'create_order', submit)
    response = auth_client.post('/checkout', data=fields)
    assert response.status_code == 409
    submit.assert_not_called()
    soup = BeautifulSoup(response.data, 'html.parser')
    replacement = soup.select_one('[name=checkout_review]')['value']
    assert replacement != fields['checkout_review']
    response = auth_client.post('/checkout', data={**fields, 'checkout_review': replacement})
    assert response.location == '/order_confirmation/10'
    assert submit.call_args.args[3][0]['quantity'] == (2 if changed == 'quantity' else 1)
    assert submit.call_args.kwargs['reviewed_prices'] == {1: '1.50' if changed == 'price' else '0.10'}


@pytest.mark.parametrize('query,form', [('1', '0'), ('2', '1'), ('1', 'bad')])
def test_checkout_rejects_conflicting_or_unknown_mode(auth_client, catalog, query, form):
    response = auth_client.post(f'/checkout?buy_now={query}', data=checkout_fields(buy_now=form))
    assert response.status_code == 400


@pytest.mark.parametrize(
    'overrides',
    [
        {'shipping_method': 'express'},
        {'discount_code': 'WELCOME10'},
        {'payment_method': 'Ví MoMo'},
        {'full_name': ' '},
        {'phone': ''},
        {'phone': 'abcdefghij'},
        {'email': 'not-email'},
        {'shipping_address': 'x' * 501},
        {'order_notes': 'x' * 2001},
    ],
)
def test_checkout_rejects_unimplemented_or_invalid_fields_before_order_write(auth_client, catalog, fake_db, overrides):
    set_cart(auth_client, [{'variant_id': 1, 'quantity': 1}])
    response = auth_client.post('/checkout', data=reviewed_checkout_fields(auth_client, **overrides))
    assert response.status_code == 400
    fake_db.connection.cursor.assert_not_called()
    with auth_client.session_transaction() as state:
        assert state['cart']


@pytest.mark.parametrize(
    'path,data',
    [
        ('/add_to_wishlist', {'product_id': 1}),
        ('/remove_from_wishlist', {'wishlist_id': 1}),
        ('/add_review', {'product_id': 1, 'rating': 5, 'comment': 'Text'}),
        ('/add_comment', {'product_id': 1, 'content': 'Text'}),
        ('/cancel_order/1', {}),
    ],
)
def test_customer_json_actions_require_login_even_form_posts(client, path, data):
    response = client.post(path, data=data)
    assert response.status_code == 401 and response.is_json
    assert response.json['success'] is False


def test_wishlist_uses_session_owner_and_passes_service_http_status(auth_client, monkeypatch):
    add = Mock(return_value={'success': False, 'message': 'Exists', 'status_code': 409})
    remove = Mock(return_value={'success': False, 'message': 'Missing', 'status_code': 404})
    monkeypatch.setattr(WishlistService, 'add_to_wishlist', add)
    monkeypatch.setattr(WishlistService, 'remove_from_wishlist', remove)
    assert auth_client.post('/add_to_wishlist', json={'product_id': 5, 'user_id': 999}).status_code == 409
    assert auth_client.post('/remove_from_wishlist', json={'wishlist_id': 6, 'user_id': 999}).status_code == 404
    add.assert_called_once_with(1, 5)
    remove.assert_called_once_with(1, 6)


def test_feedback_routes_validate_text_and_return_service_conflict(auth_client, monkeypatch):
    add = Mock(return_value={'success': False, 'message': 'Missing product', 'status_code': 404})
    monkeypatch.setattr(FeedbackService, 'add_review', add)
    response = auth_client.post('/add_review', data={'product_id': 1, 'rating': 5, 'comment': 'Text'})
    assert response.status_code == 404
    response = auth_client.post('/add_review', data={'product_id': 1, 'rating': 5, 'comment': ' '})
    assert response.status_code == 400
    assert add.call_count == 1
    response = auth_client.post('/add_comment', data={'product_id': 1, 'content': ' '})
    assert response.status_code == 400


@pytest.mark.parametrize('path', ['/order/7', '/order_confirmation/7'])
def test_foreign_order_route_is_not_found_and_owner_scoped(auth_client, monkeypatch, path):
    detail = Mock(return_value=None)
    monkeypatch.setattr(OrderService, 'get_user_order_detail', detail)
    response = auth_client.get(path)
    assert response.status_code == 404
    detail.assert_called_once_with(7, 1)


def test_cancel_order_preserves_committed_success_if_notification_fails(auth_client, monkeypatch):
    cancel = Mock(return_value={'success': True})
    monkeypatch.setattr(OrderService, 'cancel_order', cancel)
    monkeypatch.setattr(AuthService, 'get_customer_profile', Mock(side_effect=RuntimeError('email failure')))
    monkeypatch.setattr(cart_routes, 'send_email', Mock())
    response = auth_client.post('/cancel_order/9')
    assert response.status_code == 200 and response.json['success'] is True
    cancel.assert_called_once_with(9, 1)
    cart_routes.send_email.assert_not_called()


def test_form_json_endpoint_db_failure_is_json_503(client, monkeypatch):
    monkeypatch.setattr(ProductService, 'get_variant_detail', Mock(side_effect=psycopg2.OperationalError('private')))
    set_cart(client, [{'variant_id': 1, 'quantity': 1}])
    response = client.post('/update_cart', data={'variant_id': 1, 'quantity': 1})
    assert response.status_code == 503 and response.is_json
    assert 'private' not in response.json['message']


def test_track_view_checks_product_and_deduplicates_bounded_ids(client, catalog):
    with client.session_transaction() as state:
        state['recently_viewed'] = [2, 1, 'bad', 1, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert client.post('/api/track_product_view', data={'product_id': 1}).status_code == 200
    with client.session_transaction() as state:
        assert state['recently_viewed'][:2] == [1, 2]
        assert len(state['recently_viewed']) == 10 and 'bad' not in state['recently_viewed']
    assert client.post('/api/track_product_view', data={'product_id': 99}).status_code == 404


@pytest.mark.parametrize('poison', [None, '2', {'2': True}, 2], ids=['null', 'string', 'mapping', 'integer'])
def test_product_detail_recovers_nonlist_recently_viewed(client, catalog, poison):
    cart = [{'variant_id': 2, 'quantity': 1}]
    with client.session_transaction() as state:
        state.update(recently_viewed=poison, cart=cart)
    response = client.get('/product/1')
    assert response.status_code == 200
    assert response.mimetype == 'text/html'
    with client.session_transaction() as state:
        assert state['recently_viewed'] == [1]
        assert state['cart'] == cart


@pytest.mark.parametrize('poison', [None, '2', {'2': True}, 2], ids=['null', 'string', 'mapping', 'integer'])
def test_track_view_recovers_nonlist_recently_viewed(client, catalog, poison):
    cart = [{'variant_id': 2, 'quantity': 1}]
    with client.session_transaction() as state:
        state.update(recently_viewed=poison, cart=cart)
    response = client.post('/api/track_product_view', json={'product_id': 1})
    assert response.status_code == 200
    assert response.json == {'success': True}
    with client.session_transaction() as state:
        assert state['recently_viewed'] == [1]
        assert state['cart'] == cart


def test_identical_tracking_does_not_rewrite_session(client, catalog, monkeypatch):
    _, products = catalog
    product_read = Mock(return_value=products[1])
    monkeypatch.setattr(ProductService, 'get_product_by_id', product_read)
    before = {'recently_viewed': [1, 2], 'cart': [{'variant_id': 2, 'quantity': 1}]}
    with client.session_transaction() as state:
        state.update(before)
    for _ in range(2):
        response = client.post('/api/track_product_view', json={'product_id': 1})
        assert response.status_code == 200
        assert response.json == {'success': True}
        assert 'Set-Cookie' not in response.headers
    with client.session_transaction() as state:
        assert dict(state) == before
    assert product_read.call_count == 2
    product_read.assert_called_with(1)


@pytest.mark.parametrize('per_page', ['', 'bad', '13'], ids=['empty', 'nonnumeric', 'unsupported-size'])
def test_invalid_per_page_defaults_to_12_without_resetting_page_or_sort(client, catalog, monkeypatch, per_page):
    _, products = catalog
    search = Mock(
        return_value={'products': [products[1]], 'total_records': 25, 'total_pages': 3, 'current_page': 2, 'offset': 12}
    )
    monkeypatch.setattr(ProductService, 'search_products', search)
    response = client.get('/products', query_string={'page': '2', 'per_page': per_page, 'sort': 'price_asc'})
    assert response.status_code == 200
    search.assert_called_once_with('', None, None, None, None, None, 0, 2, 12, 'price_asc')
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('#filterForm input[name=per_page]')['value'] == '12'
    assert soup.select_one('#filterForm input[name=sort]')['value'] == 'price_asc'


def test_products_filters_pagination_and_sort_controls_preserve_state(client, catalog, monkeypatch):
    _, products = catalog
    search = Mock(
        return_value={'products': [products[1]], 'total_records': 49, 'total_pages': 3, 'current_page': 2, 'offset': 24}
    )
    monkeypatch.setattr(ProductService, 'search_products', search)
    response = client.get(
        '/products?search=shirt&category=1&color=1&size=1&min_price=0.10&max_price=10.20&in_stock=1&page=2&per_page=24&sort=price_asc'
    )
    assert response.status_code == 200
    assert search.call_args.args == ('shirt', 1, Decimal('0.10'), Decimal('10.20'), 1, 1, 1, 2, 24, 'price_asc')
    soup = BeautifulSoup(response.data, 'html.parser')
    for link in soup.select('.page-link'):
        assert 'per_page=24' in link['href'] and 'color=1' in link['href'] and 'sort=price_asc' in link['href']
    assert soup.select_one('#filterForm input[name=per_page]')['value'] == '24'
    assert soup.select_one('#filterForm input[name=sort]')['value'] == 'price_asc'
    for name in ('category', 'min_price', 'max_price', 'color', 'size', 'in_stock'):
        field = soup.select_one(f'#filterForm [name={name}]')
        assert soup.find('label', attrs={'for': field['id']}).get_text(strip=True)
        assert not field.has_attr('onchange')
    sort_field = soup.select_one('#sortForm select[name=sort]')
    assert soup.find('label', attrs={'for': sort_field['id']}).get_text(strip=True)
    assert not sort_field.has_attr('onchange')
    assert soup.select_one('#sortForm button[type=submit]')
    assert soup.select_one('.wishlist-add-btn')['data-product-id'] == '1'
    assert soup.select_one('#product-list-top .badge.bg-primary').get_text(strip=True) == '49'
    assert soup.select_one('#catalogFilterPanel summary .badge').get_text(strip=True).startswith('5')


def test_invalid_catalog_price_range_renders_filter_correction(app, client, catalog, monkeypatch):
    app.config['DB_CONNECT_ENABLED'] = True  # Use the catalog fixture's category options.
    search = Mock()
    monkeypatch.setattr(ProductService, 'search_products', search)
    response = client.get(
        '/products?search=shirt&category=1&color=1&size=1&min_price=10.20&max_price=0.10&in_stock=1&per_page=24&sort=price_asc'
    )
    assert response.status_code == 400
    search.assert_not_called()
    soup = BeautifulSoup(response.data, 'html.parser')
    message = soup.select_one('#filterForm [role=alert]')
    assert message.get_text(strip=True) == 'Giá tối thiểu không được lớn hơn giá tối đa'
    for name, value in [('min_price', '10.20'), ('max_price', '0.10')]:
        field = soup.select_one(f'#filterForm input[name={name}]')
        assert field['value'] == value
        assert field['aria-invalid'] == 'true' and field['aria-describedby'] == message['id']
    for name in ('category', 'color', 'size'):
        assert soup.select_one(f'#filterForm select[name={name}] option[selected]')['value'] == '1'
    assert soup.select_one('#filterForm input[name=in_stock]').has_attr('checked')
    for name, value in [('search', 'shirt'), ('per_page', '24'), ('sort', 'price_asc')]:
        assert soup.select_one(f'#filterForm input[name={name}]')['value'] == value


@pytest.mark.parametrize('query', ['min_price=NaN', 'max_price=Infinity', 'min_price=-1'])
def test_bad_catalog_prices_render_filter_error_without_searching(client, catalog, monkeypatch, query):
    search = Mock()
    monkeypatch.setattr(ProductService, 'search_products', search)
    response = client.get('/products?' + query)
    assert response.status_code == 400
    assert BeautifulSoup(response.data, 'html.parser').select_one('#catalogPriceError')
    search.assert_not_called()


@pytest.mark.parametrize('query', ['color=-1', 'size=1.2', 'in_stock=2'])
def test_bad_product_filters_return_400_without_database_query(client, fake_db, query):
    assert client.get('/products?' + query).status_code == 400
    fake_db.connection.cursor.assert_not_called()


def test_product_paging_bad_values_fall_back_without_500(client, catalog, monkeypatch):
    search = Mock(return_value={'products': [], 'total_records': 0, 'total_pages': 1, 'current_page': 1, 'offset': 0})
    monkeypatch.setattr(ProductService, 'search_products', search)
    assert client.get('/products?page=' + '9' * 5000 + '&per_page=0&sort=unknown').status_code == 200
    assert search.call_args.args[-3:] == (1, 12, 'newest')


@pytest.mark.parametrize('path', ['/cart', '/product/1', '/products', '/wishlist', '/order_confirmation/1'])
def test_storefront_rendered_scripts_parse_without_global_redeclaration(
    auth_client, catalog, monkeypatch, path, tmp_path
):
    variants, products = catalog
    set_cart(auth_client, [{'variant_id': 1, 'quantity': 2}])
    monkeypatch.setattr(
        ProductService,
        'search_products',
        lambda *args: {
            'products': list(products.values()),
            'total_records': 2,
            'total_pages': 1,
            'current_page': 1,
            'offset': 0,
        },
    )
    monkeypatch.setattr(
        WishlistService,
        'get_wishlist_by_user',
        lambda _: [
            record(
                WishlistID=1,
                ProductID=1,
                ProductName='Áo chính',
                Price=Decimal('0.10'),
                OriginalPrice=Decimal('0.20'),
                CategoryName='Áo',
                ImageURL='images/1.jpg',
                AddedDate=datetime(2026, 1, 1),
            )
        ],
    )
    monkeypatch.setattr(
        OrderService,
        'get_user_order_detail',
        lambda *_: {
            'order': record(
                OrderID=1,
                OrderDate=datetime(2026, 1, 1),
                TotalAmount=Decimal('0.20'),
                Status='Pending',
                PaymentMethod=OrderService.PAYMENT_METHOD,
                ShippingAddress='Address',
                recipient_name='Recipient',
                recipient_phone='0900000001',
                recipient_email='one@example.test',
                notes='Note',
                CustomerName='Fallback',
                CustomerPhone='Fallback',
            ),
            'items': [
                record(
                    ProductName='Áo chính',
                    ColorName='Đen',
                    SizeName='M',
                    Quantity=2,
                    Price=Decimal('0.10'),
                    UnitPrice=Decimal('0.10'),
                    Subtotal=Decimal('0.20'),
                )
            ],
        },
    )
    response = auth_client.get(path)
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    scripts = [
        node.get_text()
        for node in soup.find_all('script')
        if not node.get('src')
        and node.get('type', '') not in {'application/json', 'application/ld+json', 'text/template'}
    ]
    for data_script in soup.select('script[type="application/ld+json"]'):
        assert isinstance(json.loads(data_script.get_text()), (dict, list))
    script_path = tmp_path / 'storefront-rendered.js'
    script_path.write_text('\n'.join(scripts), encoding='utf-8')
    checked = subprocess.run(
        ['node', '--check', str(script_path)], capture_output=True, text=True, timeout=15, check=False
    )
    assert checked.returncode == 0, checked.stderr
    assert '0.1' in response.get_data(as_text=True)
    if path == '/product/1':
        assert soup.select_one('#addToCartBtn').has_attr('disabled')
        assert soup.select_one('#buyNowBtn')['formaction'] == '/buy_now'
        assert soup.select_one('#buyNowBtn').has_attr('disabled')
        assert soup.select_one('#productPurchaseForm [name=csrf_token]')
        assert soup.select_one('#product-description').get_text() == products[1].Description
        assert soup.select_one('#product-description script') is None
        detail_scripts = response.get_data(as_text=True).split(
            '<script type="application/json" id="variants-data">', 1
        )[1]
        assert 'Math.random' not in detail_scripts
        assert 'Cảm ơn bạn đã báo cáo' not in response.get_data(as_text=True)
        assert 'Object.assign(window' in response.get_data(as_text=True)


def test_guest_product_detail_has_safe_handlers_and_no_fabricated_description(client, catalog):
    response = client.get('/product/1')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('#submit-review') is None and soup.select_one('#submit-comment') is None
    assert "getElementById('submit-review')?.addEventListener" in html
    assert "getElementById('submit-comment')?.addEventListener" in html
    assert '$(' not in html.split('<script type="application/json" id="variants-data">', 1)[1]
    assert 'via.placeholder.com' not in html
    assert '&lt;script&gt;' in html


def test_storefront_csrf_remains_enforced(app, client, catalog):
    app.config['WTF_CSRF_ENABLED'] = True
    response = client.post(
        '/add_to_cart', data={'variant_id': 1, 'quantity': 1}, headers={'Accept': 'application/json'}
    )
    assert response.status_code == 400
    with client.session_transaction() as state:
        assert 'cart' not in state


def test_empty_cart_checkout_redirects_to_cart(auth_client, catalog):
    assert auth_client.get('/checkout').location == '/cart'


def test_buy_now_zero_stock_and_missing_variants_return_conflicts(client, catalog):
    headers = {'Accept': 'application/json'}
    assert client.post('/buy_now', data={'variant_id': 3, 'quantity': 1}, headers=headers).status_code == 409
    assert client.post('/buy_now', data={'variant_id': 999, 'quantity': 1}, headers=headers).status_code == 404
    assert client.post('/add_to_cart', data={'variant_id': 999, 'quantity': 1}, headers=headers).status_code == 404


def test_buy_now_json_returns_checkout_url(client, catalog):
    response = client.post('/buy_now', json={'variant_id': 1, 'quantity': 1})
    assert response.status_code == 200 and response.json['checkout_url'].startswith('/checkout?buy_now=1&draft=')


def test_get_variant_success_reports_current_stock_including_sold_out(client, catalog):
    response = client.post('/api/get_variant', json={'product_id': 1, 'color_id': 2, 'size_id': 1})
    assert response.status_code == 200 and response.json['quantity'] == 0
    assert response.json['variant_id'] == 3
    assert client.post('/api/get_variant', data={'product_id': 1, 'color_id': 1, 'size_id': 2}).status_code == 404


def test_product_autocomplete_empty_and_bounded_query(client, monkeypatch):
    autocomplete = Mock(return_value=[])
    monkeypatch.setattr(ProductService, 'search_autocomplete', autocomplete)
    assert client.get('/api/search_autocomplete?q= ').json['products'] == []
    assert client.get('/api/search_autocomplete?q=shirt').status_code == 200
    autocomplete.assert_called_once_with('shirt')
    assert client.get('/api/search_autocomplete?q=' + 'x' * 201).status_code == 400


def test_recently_viewed_api_returns_lowercase_price_contract(client, monkeypatch):
    recent = Mock(return_value=[{'product_id': 1, 'price': '0.10', 'image_url': '/static/images/1.jpg'}])
    monkeypatch.setattr(ProductService, 'get_recently_viewed_products', recent)
    response = client.get('/api/get_recently_viewed')
    assert response.json['products'][0]['price'] == '0.10'
    recent.assert_called_once_with([])


def test_checkout_json_result_uses_only_authoritative_cart(auth_client, catalog, monkeypatch):
    set_cart(auth_client, [{'variant_id': 1, 'quantity': 1, 'price': '0.01'}])
    create = Mock(return_value={'success': True, 'order_id': 9})
    monkeypatch.setattr(OrderService, 'create_order', create)
    response = auth_client.post(
        '/checkout', data=reviewed_checkout_fields(auth_client), headers={'Accept': 'application/json'}
    )
    assert response.status_code == 200 and response.json['confirmation_url'] == '/order_confirmation/9'
    assert create.call_args.args[3][0]['price'] == '0.10'
    with auth_client.session_transaction() as state:
        assert 'cart' not in state
        assert CartService.load(state['cart_id'])[1] == []


def test_stock_rejected_checkout_keeps_cart(auth_client, catalog, monkeypatch):
    set_cart(auth_client, [{'variant_id': 1, 'quantity': 6}])
    create = Mock(return_value={'success': False, 'message': 'Hết hàng', 'status_code': 409})
    monkeypatch.setattr(OrderService, 'create_order', create)
    response = auth_client.post(
        '/checkout', data=reviewed_checkout_fields(auth_client), headers={'Accept': 'application/json'}
    )
    assert response.status_code == 409
    create.assert_called_once()
    with auth_client.session_transaction() as state:
        assert state['cart'][0]['quantity'] == 6


def test_checkout_cart_error_uses_a_public_message(auth_client, catalog, monkeypatch):
    set_cart(auth_client, [{'variant_id': 1, 'quantity': 1}])
    failure = Mock(side_effect=ValidationError('Internal cart diagnostic'))
    monkeypatch.setattr(ProductService, 'refresh_cart_items', failure)
    response = auth_client.get('/checkout', headers={'Accept': 'application/json'})
    assert response.status_code == 409
    assert response.json['message'].startswith('Giỏ hàng đã thay đổi')
    assert b'Internal cart diagnostic' not in response.data


def test_cancel_order_failure_passes_service_http_status(auth_client, monkeypatch):
    monkeypatch.setattr(
        OrderService,
        'cancel_order',
        Mock(
            return_value={
                'success': False,
                'message': 'Only Pending',
                'status_code': 409,
            }
        ),
    )
    assert auth_client.post('/cancel_order/1').status_code == 409


def test_successful_cancel_optional_email_escapes_customer_name(auth_client, monkeypatch):
    monkeypatch.setattr(OrderService, 'cancel_order', Mock(return_value={'success': True}))
    monkeypatch.setattr(
        AuthService,
        'get_customer_profile',
        Mock(return_value=record(Email='one@example.test', FullName='<img src=x onerror=alert(1)>')),
    )
    notify = Mock(return_value=True)
    monkeypatch.setattr(cart_routes, 'send_email', notify)
    response = auth_client.post('/cancel_order/1')
    assert response.status_code == 200
    assert '&lt;img' in notify.call_args.args[2]


def test_currency_fraction_in_cart_is_not_rounded_to_zero(client, catalog):
    set_cart(client, [{'variant_id': 1, 'quantity': 3}])
    response = client.get('/cart')
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('#price-1').get_text().strip() == '0.1 đ'
    assert soup.select_one('#subtotal-1').get_text().strip() == '0.3 đ'
    assert soup.select_one('#total').get_text().strip() == '0.3 đ'


def test_currency_integer_display_keeps_main_grouping(client, catalog):
    variants, _ = catalog
    variants[1].Price = Decimal('199000.00')
    set_cart(client, [{'variant_id': 1, 'quantity': 2}])
    soup = BeautifulSoup(client.get('/cart').data, 'html.parser')
    assert soup.select_one('#price-1').get_text().strip() == '199,000 đ'
    assert soup.select_one('#subtotal-1').get_text().strip() == '398,000 đ'
