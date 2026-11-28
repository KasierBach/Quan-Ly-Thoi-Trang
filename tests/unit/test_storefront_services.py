from decimal import Decimal
from functools import partial
from unittest.mock import Mock

import psycopg2
import pytest

from app.database import CaseInsensitiveRecord
from app.services.order_service import OrderService
from app.services.product_service import ProductService
from app.services.wishlist_service import WishlistService
from app.validation import ValidationError


def record(**values):
    return CaseInsensitiveRecord(values)


@pytest.mark.parametrize(
    'items',
    [
        None,
        {},
        [None],
        [{}],
        [{'variant_id': 1, 'quantity': None}],
        [{'variant_id': 0, 'quantity': 1}],
        [{'variant_id': -1, 'quantity': 1}],
        [{'variant_id': True, 'quantity': 1}],
        [{'variant_id': '1.5', 'quantity': 1}],
        [{'variant_id': 1, 'quantity': False}],
        [{'variant_id': 1, 'quantity': 0}],
        [{'variant_id': 1, 'quantity': '-2'}],
        [{'variant_id': 1, 'quantity': '1.2'}],
        [{'variant_id': 1, 'quantity': 2147483648}],
        [{'variant_id': 1, 'quantity': 2147483647}, {'variant_id': 1, 'quantity': 1}],
        [{'variant_id': 1, 'quantity': '9' * 5000}],
    ],
)
def test_cart_validation_rejects_nonpositive_noninteger_and_overflow(items):
    with pytest.raises(ValidationError):
        ProductService.normalize_cart_items(items)


def test_cart_normalization_merges_variants_and_ignores_client_prices():
    items = [
        {'variant_id': '7', 'quantity': '2', 'price': '-999'},
        {'variant_id': 2, 'quantity': 1},
        {'variant_id': 7, 'quantity': 3},
    ]
    assert ProductService.normalize_cart_items(items) == [
        {'variant_id': 2, 'quantity': 1},
        {'variant_id': 7, 'quantity': 5},
    ]


def test_exact_cart_money_and_refresh_ignore_stale_metadata(monkeypatch):
    variant = record(
        ProductID=1,
        ProductName='Current',
        Price=Decimal('0.10'),
        Quantity=4,
        ColorName='Đen',
        SizeName='M',
        ImageURL='images/1.jpg',
    )
    monkeypatch.setattr(ProductService, 'get_variant_detail', Mock(return_value=variant))
    items = ProductService.refresh_cart_items([{'variant_id': 1, 'quantity': 3, 'price': '9999'}])
    assert items[0]['price'] == '0.10' and items[0]['product_name'] == 'Current'
    assert ProductService.cart_total(items) == Decimal('0.30')
    with pytest.raises(ValidationError, match='chỉ còn'):
        ProductService.refresh_cart_items([{'variant_id': 1, 'quantity': 5}], require_stock=True)


def test_missing_cart_variant_is_not_silently_ordered(monkeypatch):
    monkeypatch.setattr(ProductService, 'get_variant_detail', Mock(return_value=None))
    with pytest.raises(ValidationError, match='tồn tại'):
        ProductService.refresh_cart_items([{'variant_id': 1, 'quantity': 1}])
    assert ProductService.refresh_cart_items([{'variant_id': 1, 'quantity': 1}], drop_missing=True) == []


@pytest.mark.parametrize(
    'sort,order_sql',
    [
        ('newest', 'p.CreatedAt DESC, sp.ProductID DESC'),
        ('price_asc', 'sp.Price ASC, sp.ProductID ASC'),
        ('price_desc', 'sp.Price DESC, sp.ProductID ASC'),
        ('name_asc', 'sp.ProductName ASC, sp.ProductID ASC'),
        ('price; DROP TABLE Products', 'p.CreatedAt DESC, sp.ProductID DESC'),
    ],
)
def test_search_uses_same_filters_decimal_bounds_and_stable_sort(fake_db, sort, order_sql):
    fake_db.cursor.fetchone.return_value = (25,)
    fake_db.cursor.fetchall.return_value = []
    result = ProductService.search_products('shirt', 1, '0.10', '10.20', 2, 3, 1, 100, 24, sort)
    assert result['current_page'] == 2 and result['offset'] == 24
    count_call, list_call = fake_db.cursor.execute.call_args_list
    filters = ('shirt', 1, Decimal('0.10'), Decimal('10.20'), 2, 3, True)
    assert count_call.args[1] == filters
    assert list_call.args[1] == filters + (24, 24)
    assert f'ORDER BY {order_sql}' in list_call.args[0]
    assert 'JOIN Products p ON p.ProductID = sp.ProductID' in list_call.args[0]
    assert 'DROP TABLE' not in list_call.args[0]
    fake_db.connection.close.assert_called_once()


@pytest.mark.parametrize(
    'overrides',
    [
        {'min_price': 'NaN'},
        {'max_price': 'Infinity'},
        {'min_price': '-1'},
        {'min_price': '2', 'max_price': '1'},
        {'category_id': 0},
        {'color_id': -1},
        {'size_id': True},
        {'in_stock_only': 2},
        {'page': 0},
        {'per_page': 0},
    ],
)
def test_search_bad_filters_do_not_query(fake_db, overrides):
    values = dict(
        search_term='',
        category_id=None,
        min_price=None,
        max_price=None,
        color_id=None,
        size_id=None,
        in_stock_only=0,
        page=1,
        per_page=12,
        sort_by='newest',
    )
    values.update(overrides)
    with pytest.raises(ValidationError):
        ProductService.search_products(**values)
    fake_db.connection.cursor.assert_not_called()


@pytest.mark.parametrize(
    'method,args',
    [
        (ProductService.get_variant_detail, (0,)),
        (ProductService.get_variant_quantity, (-1,)),
        (ProductService.get_product_by_id, (True,)),
        (ProductService.get_product_variants, ('1.1',)),
        (ProductService.get_variant_by_details, (1, 2, 0)),
        (ProductService.get_featured_products, (0,)),
        (ProductService.get_best_selling_products, (101,)),
        (ProductService.search_autocomplete, ('x' * 201,)),
    ],
)
def test_product_reads_reject_invalid_ids_and_limits_before_db(fake_db, method, args):
    with pytest.raises(ValidationError):
        method(*args)
    fake_db.connection.cursor.assert_not_called()


def test_autocomplete_preserves_external_image_and_exact_price(app, fake_db):
    fake_db.cursor.fetchall.return_value = [
        record(
            ProductID=1,
            ProductName='Áo',
            Price=Decimal('123.45'),
            ImageURL='https://images.example.test/one.jpg',
            CategoryName='Áo',
        )
    ]
    with app.test_request_context():
        result = ProductService.search_autocomplete('Áo')
    assert result[0]['image'] == 'https://images.example.test/one.jpg'
    assert result[0]['price'] == '123.45'


def test_recently_viewed_preserves_order_aliases_images_and_prices(app, fake_db):
    fake_db.cursor.fetchall.return_value = [
        record(ProductID=2, ProductName='Second', Price=Decimal('0.20'), ImageURL=None, CategoryName='Áo'),
        record(ProductID=1, ProductName='First', Price=Decimal('0.10'), ImageURL='images/1.jpg', CategoryName='Áo'),
    ]
    with app.test_request_context():
        result = ProductService.get_recently_viewed_products([1, '2', 1, 'bad', 0, True])
    assert [item['product_id'] for item in result] == [1, 2]
    assert [item['price'] for item in result] == ['0.10', '0.20']
    assert result[0]['image_url'] == '/static/images/1.jpg'
    assert fake_db.cursor.execute.call_args.args[1] == ((1, 2),)


@pytest.mark.parametrize(
    'overrides',
    [
        {'user_id': 0},
        {'cart_items': []},
        {'cart_items': [{'variant_id': 1, 'quantity': -1}]},
        {'payment_method': 'Thẻ tín dụng/ghi nợ'},
        {'shipping_address': ' '},
        {'shipping_address': 'x' * 501},
        {'recipient_name': 'x' * 256},
        {'recipient_phone': 'x' * 21},
        {'recipient_phone': 'abcdefghij'},
        {'recipient_email': 'not email'},
        {'notes': 'x' * 2001},
    ],
)
def test_create_order_validates_before_writes(fake_db, overrides):
    values = dict(
        user_id=1,
        payment_method=OrderService.PAYMENT_METHOD,
        shipping_address='Address',
        cart_items=[{'variant_id': 1, 'quantity': 1}],
        recipient_name='Recipient',
        recipient_phone='0900000001',
        recipient_email='one@example.test',
        notes='',
    )
    values.update(overrides)
    result = OrderService.create_order(**values)
    assert result['success'] is False and result['status_code'] == 400
    fake_db.connection.cursor.assert_not_called()


def test_order_creation_snapshots_recipient_and_merges_items_in_one_transaction(fake_db):
    fake_db.cursor.fetchone.return_value = record(OrderID=9)
    result = OrderService.create_order(
        1,
        OrderService.PAYMENT_METHOD,
        ' Address ',
        [
            {'variant_id': 2, 'quantity': 2, 'price': 0},
            {'variant_id': 1, 'quantity': 1},
            {'variant_id': 2, 'quantity': 1},
        ],
        recipient_name=' Recipient ',
        recipient_phone=' 0900000001 ',
        recipient_email=' ONE@example.TEST ',
        notes=' note ',
    )
    assert result == {'success': True, 'order_id': 9}
    calls = fake_db.cursor.execute.call_args_list
    assert calls[0].args[1] == (1, OrderService.PAYMENT_METHOD, 'Address')
    assert 'recipient_name = %s' in calls[1].args[0]
    assert calls[1].args[1] == ('Recipient', '0900000001', 'one@example.test', 'note', 9)
    assert [call.args[1] for call in calls[2:]] == [(9, 1, 1), (9, 2, 3)]
    fake_db.connection.commit.assert_called_once()
    fake_db.connection.rollback.assert_not_called()
    fake_db.connection.close.assert_called_once()


def test_order_failure_rolls_back_all_items_and_hides_error(app, fake_db):
    fake_db.cursor.fetchone.return_value = record(OrderID=1)
    fake_db.cursor.execute.side_effect = [None, None, psycopg2.OperationalError('secret host/user/password')]
    with app.app_context():
        result = OrderService.create_order(
            1,
            OrderService.PAYMENT_METHOD,
            'Address',
            [{'variant_id': 1, 'quantity': 1}, {'variant_id': 2, 'quantity': 1}],
        )
    assert result['success'] is False and result['status_code'] == 503
    assert 'secret' not in result['message']
    fake_db.connection.rollback.assert_called_once()
    fake_db.connection.commit.assert_not_called()
    fake_db.connection.close.assert_called_once()


def test_cancel_order_scopes_owner_and_locks_pending(fake_db):
    fake_db.cursor.fetchone.return_value = record(Status='Pending')
    assert OrderService.cancel_order(10, 2)['success'] is True
    first, second = fake_db.cursor.execute.call_args_list
    assert 'CustomerID = %s FOR UPDATE' in first.args[0] and first.args[1] == (10, 2)
    assert second.args[1] == (10, 'Cancelled')
    fake_db.connection.commit.assert_called_once()


@pytest.mark.parametrize(
    'order,expected',
    [
        (None, 404),
        (record(Status='Processing'), 409),
        (record(Status='Shipped'), 409),
        (record(Status='Cancelled'), 409),
    ],
)
def test_cancel_unknown_or_nonpending_order_never_mutates(fake_db, order, expected):
    fake_db.cursor.fetchone.return_value = order
    result = OrderService.cancel_order(1, 2)
    assert result['status_code'] == expected
    assert fake_db.cursor.execute.call_count == 1
    fake_db.connection.commit.assert_not_called()


@pytest.mark.parametrize('status', list(OrderService.STATUS_TRANSITIONS))
def test_admin_same_order_state_is_idempotent(fake_db, status):
    fake_db.cursor.fetchone.return_value = record(Status=status)
    assert OrderService.update_order_status(1, status)['success'] is True
    assert fake_db.cursor.execute.call_count == 1


@pytest.mark.parametrize(
    'before,after',
    [
        ('Pending', 'Processing'),
        ('Pending', 'Cancelled'),
        ('Processing', 'Shipped'),
        ('Processing', 'Cancelled'),
        ('Shipped', 'Delivered'),
    ],
)
def test_admin_forward_transition_uses_lock_and_atomic_proc(fake_db, before, after):
    fake_db.cursor.fetchone.return_value = record(Status=before)
    assert OrderService.update_order_status(1, after)['success'] is True
    assert 'FOR UPDATE' in fake_db.cursor.execute.call_args_list[0].args[0]
    assert fake_db.cursor.execute.call_args.args[1] == (1, after)


@pytest.mark.parametrize(
    'before,after',
    [('Pending', 'Delivered'), ('Shipped', 'Cancelled'), ('Delivered', 'Pending'), ('Cancelled', 'Processing')],
)
def test_admin_backward_or_invalid_transition_does_not_write(fake_db, before, after):
    fake_db.cursor.fetchone.return_value = record(Status=before)
    assert OrderService.update_order_status(1, after)['status_code'] == 409
    assert fake_db.cursor.execute.call_count == 1


@pytest.mark.parametrize(
    'method,args', [(OrderService.get_user_order_detail, (5, 2)), (OrderService.get_order_detail, (5,))]
)
def test_order_details_expose_canonical_price_and_compatibility_aliases(fake_db, method, args):
    fake_db.cursor.fetchone.return_value = record(OrderID=5, CustomerID=2)
    fake_db.cursor.fetchall.return_value = [
        record(Price=Decimal('0.10'), UnitPrice=Decimal('0.10'), Subtotal=Decimal('0.20'))
    ]
    result = method(*args)
    sql = fake_db.cursor.execute.call_args.args[0]
    assert 'od.Price, od.Price AS UnitPrice' in sql and 'od.Price * od.Quantity AS Subtotal' in sql
    assert result['items'][0].Price == Decimal('0.10')
    if len(args) == 2:
        assert 'o.CustomerID = %s' in fake_db.cursor.execute.call_args_list[0].args[0]
        assert fake_db.cursor.execute.call_args_list[0].args[1] == args


def test_foreign_order_detail_does_not_query_items(fake_db):
    fake_db.cursor.fetchone.return_value = None
    assert OrderService.get_user_order_detail(1, 2) is None
    assert fake_db.cursor.execute.call_count == 1


@pytest.mark.parametrize('page,per_page', [(-2, 0), (None, None), ('bad', 'bad')])
def test_admin_pagination_defaults_are_safe(fake_db, page, per_page):
    fake_db.cursor.fetchone.return_value = (0,)
    fake_db.cursor.fetchall.return_value = []
    products = ProductService.get_admin_products(page, per_page, 'DROP TABLE')
    orders = OrderService.get_orders_admin('', page, per_page)
    for result in (products, orders):
        assert result['current_page'] == 1 and result['per_page'] == 20
        assert result['start_index'] == 0 and result['end_index'] == 0
    assert fake_db.cursor.execute.call_args.args[1] == [20, 0]


@pytest.mark.parametrize(
    'method,args',
    [
        (ProductService.add_product, (' ', '', '1', 1, '0')),
        (ProductService.add_product, ('Name', '', 'NaN', 1, '0')),
        (ProductService.add_product, ('Name', '', '1.001', 1, '0')),
        (ProductService.add_product, ('Name', '', '1', 0, '0')),
        (ProductService.update_product, (0, 'Name', '', '1', 1, '0', '')),
        (ProductService.update_product, (1, 'Name', '', '1', 1, '0', 'x' * 256)),
        (partial(ProductService.add_variant, actor_id=2, reason=None), (1, 1, 1, '-1')),
        (partial(ProductService.add_variant, actor_id=2, reason=None), (1, 1, 1, True)),
        (partial(ProductService.add_variant, actor_id=2, reason=None), (1, 1, 1, '1.1')),
        (partial(ProductService.add_variant, actor_id=2, reason=None), (1, 1, 1, '1')),
        (ProductService.delete_variant, (0,)),
        (ProductService.delete_product, ('1.1',)),
    ],
)
def test_catalog_invalid_mutations_reject_before_connection(fake_db, method, args):
    assert method(*args)['status_code'] == 400
    fake_db.connection.cursor.assert_not_called()


def test_catalog_add_uses_decimal_and_invalidates_after_commit(fake_db, monkeypatch):
    fake_db.cursor.fetchone.return_value = record(ProductID=1)
    invalidation = Mock()
    monkeypatch.setattr(ProductService, 'invalidate_catalog', invalidation)
    result = ProductService.add_product(' Shirt ', ' Description ', '0.10', 1, '0.20')
    assert result['product_id'] == 1
    assert fake_db.cursor.execute.call_args.args[1] == ('Shirt', 'Description', Decimal('0.10'), Decimal('0.20'), 1)
    fake_db.connection.commit.assert_called_once()
    invalidation.assert_called_once()


def test_zero_stock_variant_is_valid(fake_db):
    assert ProductService.add_variant(1, 1, 1, '0', actor_id=2, reason=None)['success'] is True
    fake_db.cursor.execute.assert_called_once()
    assert fake_db.cursor.execute.call_args.args[1] == (1, 1, 1, 0)


@pytest.mark.parametrize('delta', [None, '0', '+0', '--1', '1.5', '1e2', '-2147483648'])
def test_stock_adjustment_validates_before_db_connection(fake_db, delta):
    assert ProductService.adjust_variant_stock(1, 9, delta, actor_id=2, reason='Damaged')['status_code'] == 400
    fake_db.connection.cursor.assert_not_called()


@pytest.mark.parametrize('delta,expected', [('-5', 0), ('+3', 8)])
def test_stock_adjustment_locks_variant_and_records_adjustment(fake_db, delta, expected):
    fake_db.cursor.fetchone.return_value = record(Quantity=5)
    result = ProductService.adjust_variant_stock(1, 9, delta, actor_id=2, reason=' Recount ')
    assert result == {'success': True, 'quantity': expected}
    lock, update, history = fake_db.cursor.execute.call_args_list
    assert 'FOR UPDATE' in lock.args[0] and lock.args[1] == (1, 9)
    assert update.args[1] == (expected, 1, 9)
    assert 'INSERT INTO InventoryAdjustments' in history.args[0]
    assert history.args[1] == ('Recount', int(delta), None, 2, 1, 9)
    fake_db.connection.commit.assert_called_once()


def test_stock_adjustment_rolls_back_if_history_insert_fails(app, fake_db):
    fake_db.cursor.fetchone.return_value = record(Quantity=5)
    fake_db.cursor.execute.side_effect = [None, None, psycopg2.OperationalError('history unavailable')]
    with app.app_context():
        result = ProductService.adjust_variant_stock(1, 9, '-1', actor_id=2, reason='Damaged')
    assert result['status_code'] == 503
    fake_db.connection.rollback.assert_called_once()
    fake_db.connection.commit.assert_not_called()


@pytest.mark.parametrize(
    'variant,delta,status',
    [(None, '-1', 404), (record(Quantity=0), '-1', 409), (record(Quantity=2_147_483_647), '+1', 409)],
)
def test_stock_adjustment_does_not_write_missing_or_out_of_range_variant(fake_db, variant, delta, status):
    fake_db.cursor.fetchone.return_value = variant
    assert ProductService.adjust_variant_stock(1, 9, delta, actor_id=2, reason='Damaged')['status_code'] == status
    fake_db.cursor.execute.assert_called_once()
    fake_db.connection.commit.assert_not_called()


@pytest.mark.parametrize('method,args', [(ProductService.delete_product, (1,)), (ProductService.delete_variant, (1,))])
def test_order_referenced_catalog_entities_are_not_deleted(fake_db, method, args):
    fake_db.cursor.fetchone.side_effect = [record(ProductID=1, VariantID=1), (1,)]
    assert method(*args)['status_code'] == 409
    assert not any('DELETE FROM' in call.args[0] for call in fake_db.cursor.execute.call_args_list)
    fake_db.connection.commit.assert_not_called()


def test_deleting_unordered_product_cleans_dependents_in_one_transaction(fake_db):
    fake_db.cursor.fetchone.side_effect = [record(ProductID=1), None]
    result = ProductService.delete_product(1)
    assert result['success'] is True
    statements = [call.args[0] for call in fake_db.cursor.execute.call_args_list]
    for table in ('Wishlist', 'Reviews', 'ProductComments', 'ProductVariants', 'Products'):
        assert f'DELETE FROM {table} WHERE ProductID = %s' in statements
    fake_db.connection.commit.assert_called_once()


@pytest.mark.parametrize(
    'method,args',
    [
        (WishlistService.get_wishlist_by_user, (0,)),
        (WishlistService.add_to_wishlist, (1, 0)),
        (WishlistService.remove_from_wishlist, (1, False)),
    ],
)
def test_wishlist_invalid_ids_do_not_query(fake_db, method, args):
    with pytest.raises(ValidationError):
        method(*args)
    fake_db.connection.cursor.assert_not_called()


def test_wishlist_atomic_duplicate_returns_conflict(fake_db):
    fake_db.cursor.fetchone.side_effect = [record(ProductID=1), None]
    result = WishlistService.add_to_wishlist(2, 1)
    assert result['status_code'] == 409
    sql, params = fake_db.cursor.execute.call_args.args
    assert 'ON CONFLICT (CustomerID, ProductID) DO NOTHING' in sql
    assert params == (2, 1)


def test_wishlist_delete_is_owner_scoped(fake_db):
    fake_db.cursor.fetchone.return_value = record(WishlistID=3)
    assert WishlistService.remove_from_wishlist(2, 3)['success'] is True
    sql, params = fake_db.cursor.execute.call_args.args
    assert 'WishlistID = %s AND CustomerID = %s' in sql and params == (3, 2)


def test_wishlist_error_hides_database_secrets_and_rolls_back(app, fake_db):
    fake_db.cursor.execute.side_effect = psycopg2.OperationalError('private database password')
    with app.app_context():
        result = WishlistService.add_to_wishlist(2, 1)
    assert result['status_code'] == 503 and 'private' not in result['message']
    fake_db.connection.rollback.assert_called_once()
    fake_db.connection.close.assert_called_once()


@pytest.mark.parametrize(
    'method,args',
    [
        (ProductService.get_variant_detail, (3,)),
        (ProductService.get_variant_quantity, (3,)),
        (ProductService.get_product_by_id, (3,)),
        (ProductService.get_product_variants, (3,)),
        (ProductService.get_variant_by_details, (3, 2, 1)),
    ],
)
def test_product_lookup_executes_parameterized_query_and_closes(fake_db, method, args):
    row = record(ProductID=3, VariantID=3, Quantity=4)
    fake_db.cursor.fetchone.return_value = row
    fake_db.cursor.fetchall.return_value = [row]
    value = method(*args)
    assert value == (
        4
        if method == ProductService.get_variant_quantity
        else [row]
        if method == ProductService.get_product_variants
        else row
    )
    assert fake_db.cursor.execute.call_args.args[1] == args
    fake_db.connection.close.assert_called_once()


def test_missing_variant_quantity_is_zero(fake_db):
    fake_db.cursor.fetchone.return_value = None
    assert ProductService.get_variant_quantity(1) == 0


@pytest.mark.parametrize(
    'method,prefix', [(ProductService.get_all_colors, 'colors:'), (ProductService.get_all_sizes, 'sizes:')]
)
def test_attributes_cache_reuses_real_rows_per_app(app, fake_db, method, prefix):
    fake_db.cursor.fetchall.return_value = [record(ColorID=1, SizeID=1)]
    with app.app_context():
        first = method()
        second = method()
    assert first == second
    assert fake_db.cursor.execute.call_count == 1


@pytest.mark.parametrize('method', [ProductService.get_featured_products, ProductService.get_best_selling_products])
def test_catalog_feature_lists_bind_limit_and_stable_tie_break(fake_db, method):
    fake_db.cursor.fetchall.return_value = []
    assert method(4) == []
    sql, params = fake_db.cursor.execute.call_args.args
    assert params == (4,)
    assert 'ProductID' in sql.split('ORDER BY', 1)[1]
    fake_db.connection.close.assert_called_once()


@pytest.mark.parametrize(
    'method,args',
    [
        (ProductService.add_product, ('Name', '', '1', 1, '0')),
        (ProductService.update_product, (1, 'Name', '', '1', 1, '0', '')),
        (partial(ProductService.add_variant, actor_id=2, reason='Restock'), (1, 1, 1, 1)),
        (ProductService.delete_product, (1,)),
        (ProductService.delete_variant, (1,)),
    ],
)
def test_catalog_database_write_failure_rolls_back_and_hides_secrets(app, fake_db, method, args):
    fake_db.cursor.execute.side_effect = psycopg2.OperationalError('secret-password')
    with app.app_context():
        result = method(*args)
    assert result['status_code'] == 503 and 'secret' not in result['message']
    fake_db.connection.rollback.assert_called_once()
    fake_db.connection.commit.assert_not_called()
    fake_db.connection.close.assert_called_once()


@pytest.mark.parametrize('code', ['23503', '23505'])
def test_catalog_integrity_errors_are_conflicts(fake_db, code):
    class DatabaseConflict(psycopg2.IntegrityError):
        @property
        def pgcode(self):
            return code

    fake_db.cursor.execute.side_effect = DatabaseConflict('private')
    assert ProductService.add_variant(1, 1, 1, 1, actor_id=2, reason='Restock')['status_code'] == 409
    fake_db.connection.rollback.assert_called_once()


def test_update_product_success_invalidates_only_after_commit(fake_db, monkeypatch):
    invalidation = Mock()
    monkeypatch.setattr(ProductService, 'invalidate_catalog', invalidation)
    assert ProductService.update_product(1, 'Name', '', '0.10', 1, '0', '')['success'] is True
    assert fake_db.cursor.execute.call_args.args[1][2] == Decimal('0.10')
    fake_db.connection.commit.assert_called_once()
    invalidation.assert_called_once()


def test_update_missing_product_is_not_false_success(fake_db):
    fake_db.cursor.rowcount = 0
    assert ProductService.update_product(1, 'Name', '', '1', 1, '0', '')['status_code'] == 404
    fake_db.connection.commit.assert_not_called()


@pytest.mark.parametrize('method', [ProductService.delete_product, ProductService.delete_variant])
def test_missing_catalog_delete_is_not_false_success(fake_db, method):
    fake_db.cursor.fetchone.return_value = None
    assert method(1)['status_code'] == 404
    fake_db.connection.commit.assert_not_called()


def test_delete_unused_variant_commits_only_its_id(fake_db):
    fake_db.cursor.fetchone.side_effect = [record(VariantID=1), None]
    assert ProductService.delete_variant(1)['success'] is True
    assert fake_db.cursor.execute.call_args.args == ('DELETE FROM ProductVariants WHERE VariantID = %s', (1,))
    fake_db.connection.commit.assert_called_once()


@pytest.mark.parametrize('status', [[], {}, True, 'Unknown'])
def test_admin_order_status_wrong_types_reject_before_query(fake_db, status):
    assert OrderService.update_order_status(1, status)['status_code'] == 400
    with pytest.raises(ValidationError):
        OrderService.get_orders_admin(status, 1, 20)
    fake_db.connection.cursor.assert_not_called()


@pytest.mark.parametrize('sort', [[], {}, True])
def test_catalog_nonstring_sort_falls_back_safely(fake_db, sort):
    fake_db.cursor.fetchone.return_value = (1,)
    fake_db.cursor.fetchall.return_value = []
    ProductService.get_admin_products(1, 20, sort)
    assert 'ORDER BY p.CreatedAt DESC, p.ProductID DESC' in fake_db.cursor.execute.call_args.args[0]


def test_admin_missing_order_status_is_not_false_success(fake_db):
    fake_db.cursor.fetchone.return_value = None
    assert OrderService.update_order_status(1, 'Processing')['status_code'] == 404


@pytest.mark.parametrize(
    'method,args', [(OrderService.cancel_order, (1, 1)), (OrderService.update_order_status, (1, 'Processing'))]
)
def test_order_status_db_failure_rolls_back_and_hides_error(app, fake_db, method, args):
    fake_db.cursor.execute.side_effect = psycopg2.OperationalError('secret-password')
    with app.app_context():
        result = method(*args)
    assert result['status_code'] == 503 and 'secret' not in result['message']
    fake_db.connection.rollback.assert_called_once()
    fake_db.connection.close.assert_called_once()


def test_customer_orders_are_scoped_by_customer(fake_db):
    fake_db.cursor.fetchall.return_value = []
    assert OrderService.get_customer_orders(2) == []
    assert fake_db.cursor.execute.call_args.args[1] == (2,)
    assert 'WHERE CustomerID = %s' in fake_db.cursor.execute.call_args.args[0]


def test_wishlist_read_includes_original_price_and_is_owner_scoped(fake_db):
    fake_db.cursor.fetchall.return_value = []
    assert WishlistService.get_wishlist_by_user(3) == []
    sql, params = fake_db.cursor.execute.call_args.args
    assert 'p.OriginalPrice' in sql and 'w.CustomerID = %s' in sql and params == (3,)
    fake_db.connection.close.assert_called_once()


def test_wishlist_add_missing_product_has_no_insert(fake_db):
    fake_db.cursor.fetchone.return_value = None
    assert WishlistService.add_to_wishlist(1, 1)['status_code'] == 404
    assert fake_db.cursor.execute.call_count == 1


def test_wishlist_add_existing_product_persists_and_commits(fake_db):
    fake_db.cursor.fetchone.side_effect = [record(ProductID=1), record(WishlistID=1)]
    assert WishlistService.add_to_wishlist(1, 1)['success'] is True
    fake_db.connection.commit.assert_called_once()


def test_wishlist_remove_unknown_owner_returns_404(fake_db):
    fake_db.cursor.fetchone.return_value = None
    assert WishlistService.remove_from_wishlist(2, 3)['status_code'] == 404
    fake_db.connection.commit.assert_not_called()


def test_wishlist_remove_failure_rolls_back(app, fake_db):
    fake_db.cursor.execute.side_effect = psycopg2.OperationalError('secret')
    with app.app_context():
        assert WishlistService.remove_from_wishlist(1, 1)['status_code'] == 503
    fake_db.connection.rollback.assert_called_once()
