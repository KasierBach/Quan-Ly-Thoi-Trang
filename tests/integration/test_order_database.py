"""Database-level transactions, stock locks, lifecycle guards, and revenue."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import threading
from time import monotonic, sleep
from uuid import uuid4

from bs4 import BeautifulSoup
import psycopg2
import pytest

from app.database import CaseInsensitiveCursor


pytestmark = pytest.mark.integration


def _scalar(connection, query, parameters=()):
    with connection.cursor() as cursor:
        cursor.execute(query, parameters)
        row = cursor.fetchone()
        return row[0] if row else None


def _new_order(connection, customer_id=1):
    return _scalar(connection, 'SELECT sp_CreateOrder(%s, %s, %s)', (customer_id, 'cod', 'Synthetic Order Test Street'))


def _add(connection, order_id, variant_id, quantity):
    return _scalar(connection, 'SELECT sp_AddOrderDetail(%s, %s, %s)', (order_id, variant_id, quantity))


def _status(connection, order_id, status):
    return _scalar(connection, 'SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, status))


def _stock(connection, variant_id=1):
    return _scalar(connection, 'SELECT Quantity FROM ProductVariants WHERE VariantID = %s', (variant_id,))


def _total(connection, order_id):
    return _scalar(connection, 'SELECT TotalAmount FROM Orders WHERE OrderID = %s', (order_id,))


def _reject(connection, query, parameters=(), code='23514'):
    with connection.cursor() as cursor:
        cursor.execute('SAVEPOINT expected_order_error')
        with pytest.raises(psycopg2.Error) as raised:
            cursor.execute(query, parameters)
        cursor.execute('ROLLBACK TO SAVEPOINT expected_order_error')
        cursor.execute('RELEASE SAVEPOINT expected_order_error')
    assert raised.value.pgcode == code


def _connect(database_url):
    connection = psycopg2.connect(database_url, cursor_factory=CaseInsensitiveCursor, connect_timeout=5)
    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = '10s'")
        cursor.execute("SET lock_timeout = '5s'")
    return connection


def test_create_order_uses_persisted_price_and_updates_stock_total(db_connection):
    stock_one, stock_two = _stock(db_connection, 1), _stock(db_connection, 2)
    order_id = _new_order(db_connection)
    assert _add(db_connection, order_id, 1, 2) == 0
    assert _add(db_connection, order_id, 2, 3) == 0
    assert _stock(db_connection, 1) == stock_one - 2
    assert _stock(db_connection, 2) == stock_two - 3
    assert _total(db_connection, order_id) == Decimal('1595000.00')
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT Price, Quantity FROM OrderDetails WHERE OrderID = %s ORDER BY VariantID', (order_id,))
        rows = cursor.fetchall()
        assert rows[0].Price == Decimal('199000.00')
        assert rows[1].Price == Decimal('399000.00')
        cursor.execute('UPDATE Products SET Price = 299000 WHERE ProductID = 1')
    assert _total(db_connection, order_id) == Decimal('1595000.00')
    assert _scalar(
        db_connection, 'SELECT Price FROM OrderDetails WHERE OrderID = %s AND VariantID = 1', (order_id,)
    ) == Decimal('199000.00')


@pytest.mark.parametrize('quantity', [0, -1, -2147483648, None])
def test_order_quantity_rejected_in_function_and_direct_insert(db_connection, quantity):
    before = _stock(db_connection)
    order_id = _new_order(db_connection)
    _reject(db_connection, 'SELECT sp_AddOrderDetail(%s, 1, %s)', (order_id, quantity))
    _reject(
        db_connection,
        """INSERT INTO OrderDetails (OrderID, VariantID, Quantity, Price)
                             VALUES (%s, 1, %s, 199000)""",
        (order_id, quantity),
    )
    assert _stock(db_connection) == before
    assert _total(db_connection, order_id) == 0
    assert _scalar(db_connection, 'SELECT COUNT(*) FROM OrderDetails WHERE OrderID = %s', (order_id,)) == 0


def test_negative_stock_and_price_constraints(db_connection):
    _reject(db_connection, 'UPDATE ProductVariants SET Quantity = -1 WHERE VariantID = 1')
    _reject(db_connection, 'UPDATE Products SET Price = -1 WHERE ProductID = 1')
    _reject(db_connection, 'SELECT sp_AddProductVariant(1, 1, 1, -1)')
    assert _stock(db_connection) == 98


def test_partial_order_failure_rolls_back_order_all_details_stock_and_total(db_connection):
    stock_one, stock_two = _stock(db_connection, 1), _stock(db_connection, 2)
    order_count = _scalar(db_connection, 'SELECT COUNT(*) FROM Orders')
    details_count = _scalar(db_connection, 'SELECT COUNT(*) FROM OrderDetails')
    order_id = _new_order(db_connection)
    _add(db_connection, order_id, 1, 2)
    with pytest.raises(psycopg2.Error) as raised:
        _add(db_connection, order_id, 2, stock_two + 1)
    assert raised.value.pgcode == '23514'
    db_connection.rollback()
    assert _stock(db_connection, 1) == stock_one
    assert _stock(db_connection, 2) == stock_two
    assert _scalar(db_connection, 'SELECT COUNT(*) FROM Orders') == order_count
    assert _scalar(db_connection, 'SELECT COUNT(*) FROM OrderDetails') == details_count
    assert _total(db_connection, order_id) is None


def test_duplicate_variant_lines_cancel_all_reserved_units_once(db_connection):
    before = _stock(db_connection)
    order_id = _new_order(db_connection)
    _add(db_connection, order_id, 1, 2)
    _add(db_connection, order_id, 1, 3)
    total = _total(db_connection, order_id)
    assert _stock(db_connection) == before - 5
    assert _status(db_connection, order_id, 'Cancelled') == 0
    assert _stock(db_connection) == before
    assert _status(db_connection, order_id, 'Cancelled') == 0
    assert _stock(db_connection) == before
    assert _total(db_connection, order_id) == total
    # Old trigger returned cancelled stock a second time when details deleted.
    _reject(db_connection, 'DELETE FROM OrderDetails WHERE OrderID = %s', (order_id,))
    _reject(db_connection, 'DELETE FROM Orders WHERE OrderID = %s', (order_id,))
    assert _stock(db_connection) == before


def test_pending_detail_update_delete_and_variant_transfer_use_inventory_delta(db_connection):
    before_one, before_two = _stock(db_connection, 1), _stock(db_connection, 2)
    order_id = _new_order(db_connection)
    _add(db_connection, order_id, 1, 2)
    with db_connection.cursor() as cursor:
        cursor.execute('UPDATE OrderDetails SET Quantity = 5 WHERE OrderID = %s', (order_id,))
    assert _stock(db_connection) == before_one - 5
    assert _total(db_connection, order_id) == Decimal('995000.00')
    with db_connection.cursor() as cursor:
        cursor.execute('UPDATE OrderDetails SET Quantity = 1 WHERE OrderID = %s', (order_id,))
    assert _stock(db_connection) == before_one - 1
    with db_connection.cursor() as cursor:
        cursor.execute(
            """UPDATE OrderDetails SET VariantID = 2, Quantity = 2, Price = 399000
                          WHERE OrderID = %s""",
            (order_id,),
        )
    assert _stock(db_connection, 1) == before_one
    assert _stock(db_connection, 2) == before_two - 2
    assert _total(db_connection, order_id) == Decimal('798000.00')
    _reject(db_connection, 'UPDATE OrderDetails SET Quantity = 1000 WHERE OrderID = %s', (order_id,))
    assert _stock(db_connection, 2) == before_two - 2
    assert _total(db_connection, order_id) == Decimal('798000.00')
    with db_connection.cursor() as cursor:
        cursor.execute('DELETE FROM OrderDetails WHERE OrderID = %s', (order_id,))
    assert _stock(db_connection, 2) == before_two
    assert _total(db_connection, order_id) == 0


def test_pending_parent_delete_restocks_once_despite_detail_cascade(db_connection):
    before_one, before_two = _stock(db_connection, 1), _stock(db_connection, 2)
    order_id = _new_order(db_connection)
    _add(db_connection, order_id, 1, 2)
    _add(db_connection, order_id, 1, 3)
    _add(db_connection, order_id, 2, 1)
    with db_connection.cursor() as cursor:
        cursor.execute('DELETE FROM Orders WHERE OrderID = %s', (order_id,))
    assert _stock(db_connection, 1) == before_one
    assert _stock(db_connection, 2) == before_two
    assert _scalar(db_connection, 'SELECT COUNT(*) FROM OrderDetails WHERE OrderID = %s', (order_id,)) == 0


def test_detail_identity_cannot_move_between_orders(db_connection):
    order_one = _new_order(db_connection)
    order_two = _new_order(db_connection)
    before = _stock(db_connection)
    _add(db_connection, order_one, 1, 1)
    _reject(db_connection, 'UPDATE OrderDetails SET OrderID = %s WHERE OrderID = %s', (order_two, order_one))
    _reject(db_connection, 'UPDATE Orders SET CustomerID = 3 WHERE OrderID = %s', (order_one,))
    _reject(db_connection, 'UPDATE Orders SET TotalAmount = 999 WHERE OrderID = %s', (order_one,))
    assert _stock(db_connection) == before - 1
    assert _total(db_connection, order_one) == Decimal('199000.00')
    assert _total(db_connection, order_two) == 0


@pytest.mark.parametrize('status', ['Processing', 'Shipped', 'Delivered', 'Cancelled'])
def test_details_immutable_once_order_leaves_pending(db_connection, status):
    order_id = _new_order(db_connection)
    _add(db_connection, order_id, 1, 1)
    if status != 'Cancelled':
        _status(db_connection, order_id, 'Processing')
        if status in {'Shipped', 'Delivered'}:
            _status(db_connection, order_id, 'Shipped')
        if status == 'Delivered':
            _status(db_connection, order_id, 'Delivered')
    else:
        _status(db_connection, order_id, status)
    before = _stock(db_connection)
    _reject(db_connection, 'SELECT sp_AddOrderDetail(%s, 1, 1)', (order_id,))
    _reject(
        db_connection,
        """INSERT INTO OrderDetails (OrderID, VariantID, Quantity, Price)
                             VALUES (%s, 1, 1, 199000)""",
        (order_id,),
    )
    _reject(db_connection, 'UPDATE OrderDetails SET Quantity = 2 WHERE OrderID = %s', (order_id,))
    _reject(db_connection, 'UPDATE OrderDetails SET Price = 1 WHERE OrderID = %s', (order_id,))
    _reject(db_connection, 'DELETE FROM OrderDetails WHERE OrderID = %s', (order_id,))
    _reject(db_connection, 'DELETE FROM Orders WHERE OrderID = %s', (order_id,))
    assert _stock(db_connection) == before
    assert _total(db_connection, order_id) == Decimal('199000.00')


@pytest.mark.parametrize('terminal', ['Delivered', 'Cancelled'])
def test_finished_order_metadata_and_status_are_immutable(db_connection, terminal):
    order_id = _new_order(db_connection)
    _add(db_connection, order_id, 1, 1)
    if terminal == 'Delivered':
        for next_status in ['Processing', 'Shipped', 'Delivered']:
            _status(db_connection, order_id, next_status)
    else:
        _status(db_connection, order_id, 'Cancelled')
    before = _stock(db_connection)
    for next_status in ['Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled']:
        if next_status != terminal:
            _reject(db_connection, 'SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, next_status))
    assert _status(db_connection, order_id, terminal) == 0
    _reject(db_connection, "UPDATE Orders SET ShippingAddress = 'changed' WHERE OrderID = %s", (order_id,))
    _reject(db_connection, "UPDATE Orders SET notes = 'changed' WHERE OrderID = %s", (order_id,))
    assert _stock(db_connection) == before


def test_status_graph_and_empty_order_guard_apply_to_direct_sql(db_connection):
    order_id = _new_order(db_connection)
    _reject(db_connection, 'SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, 'Processing'))
    _add(db_connection, order_id, 1, 1)
    for invalid in ['Shipped', 'Delivered', 'invalid', None]:
        _reject(db_connection, 'UPDATE Orders SET Status = %s WHERE OrderID = %s', (invalid, order_id))
    _status(db_connection, order_id, 'Processing')
    _reject(db_connection, "UPDATE Orders SET Status = 'Pending' WHERE OrderID = %s", (order_id,))
    _reject(db_connection, "UPDATE Orders SET Status = 'Delivered' WHERE OrderID = %s", (order_id,))
    _status(db_connection, order_id, 'Shipped')
    _reject(db_connection, "UPDATE Orders SET Status = 'Cancelled' WHERE OrderID = %s", (order_id,))
    _status(db_connection, order_id, 'Delivered')
    _reject(db_connection, "INSERT INTO Orders (CustomerID, Status) VALUES (1, 'Delivered')")
    _reject(db_connection, 'INSERT INTO Orders (CustomerID, TotalAmount) VALUES (1, 100)')


def test_processing_cancellation_returns_stock_and_repeat_is_noop(db_connection):
    before = _stock(db_connection)
    order_id = _new_order(db_connection)
    _add(db_connection, order_id, 1, 3)
    _status(db_connection, order_id, 'Processing')
    _status(db_connection, order_id, 'Cancelled')
    _status(db_connection, order_id, 'Cancelled')
    assert _stock(db_connection) == before


def test_concurrent_orders_cannot_oversell_stock(db_connection, database_url):
    with db_connection.cursor() as cursor:
        cursor.execute('UPDATE ProductVariants SET Quantity = 1 WHERE VariantID = 1')
    db_connection.commit()
    barrier = threading.Barrier(2)

    def buy():
        connection = _connect(database_url)
        try:
            order_id = _new_order(connection)
            barrier.wait(timeout=5)
            try:
                _add(connection, order_id, 1, 1)
                connection.commit()
                return ('ok', order_id)
            except psycopg2.Error as error:
                connection.rollback()
                return ('rejected', error.pgcode)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(buy), executor.submit(buy)]
        results = [future.result(timeout=20) for future in futures]
    assert sorted(result[0] for result in results) == ['ok', 'rejected']
    assert next(result[1] for result in results if result[0] == 'rejected') == '23514'
    assert _stock(db_connection) == 0
    assert _scalar(db_connection, 'SELECT COUNT(*) FROM Orders WHERE OrderID > 3') == 1
    assert _scalar(db_connection, 'SELECT SUM(Quantity) FROM OrderDetails WHERE OrderID > 3') == 1
    winner = next(result[1] for result in results if result[0] == 'ok')
    assert _total(db_connection, winner) == Decimal('199000.00')


def test_conditional_stock_update_rechecks_after_competing_transaction(db_connection, database_url):
    with db_connection.cursor() as cursor:
        cursor.execute('UPDATE ProductVariants SET Quantity = 1 WHERE VariantID = 1')
    order_one, order_two = _new_order(db_connection), _new_order(db_connection)
    db_connection.commit()
    first = _connect(database_url)
    worker_started = threading.Event()
    try:
        _add(first, order_one, 1, 1)  # uncommitted lock + reservation

        def competing():
            connection = _connect(database_url)
            try:
                worker_started.set()
                try:
                    _add(connection, order_two, 1, 1)
                    connection.commit()
                    return 'unexpected-success'
                except psycopg2.Error as error:
                    connection.rollback()
                    return error.pgcode
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(competing)
            assert worker_started.wait(timeout=5)
            first.commit()
            assert future.result(timeout=15) == '23514'
    finally:
        first.rollback()
        first.close()
    assert _stock(db_connection) == 0
    assert _total(db_connection, order_two) == 0
    assert _scalar(db_connection, 'SELECT COUNT(*) FROM OrderDetails WHERE OrderID = %s', (order_two,)) == 0


def test_admin_stock_adjustment_applies_to_stock_after_concurrent_checkout(db_connection, database_url, monkeypatch):
    from app.services.base_service import BaseService
    from app.services.product_service import ProductService

    before = _stock(db_connection)
    checkout = _connect(database_url)
    adjustment = _connect(database_url)
    checkout_pid = checkout.get_backend_pid()
    adjustment_pid = adjustment.get_backend_pid()
    try:
        order_id = _new_order(checkout)
        _add(checkout, order_id, 1, 2)
        monkeypatch.setattr(BaseService, 'get_connection', lambda: adjustment)

        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(ProductService.adjust_variant_stock, 1, 1, '-3', actor_id=2, reason='Damaged items')
            try:
                deadline = monotonic() + 4
                while not _scalar(
                    db_connection, 'SELECT %s = ANY(pg_blocking_pids(%s))', (checkout_pid, adjustment_pid)
                ):
                    if monotonic() >= deadline:
                        pytest.fail('Stock adjustment did not wait for the checkout transaction')
                    sleep(0.01)
                checkout.commit()
            finally:
                checkout.rollback()
            assert future.result(timeout=5) == {'success': True, 'quantity': before - 5}
    finally:
        checkout.close()
        adjustment.close()
    assert _stock(db_connection) == before - 5
    assert _total(db_connection, order_id) == Decimal('398000.00')
    with db_connection.cursor() as cursor:
        cursor.execute("""
            SELECT variant_id, actor_id, actor_name, reason, quantity_before, quantity_after
            FROM InventoryAdjustments WHERE product_id = 1
        """)
        assert [tuple(row.values()) for row in cursor.fetchall()] == [
            (1, 2, 'Test Admin', 'Damaged items', before - 2, before - 5),
        ]


def test_concurrent_repeat_cancellation_restores_inventory_exactly_once(db_connection, database_url):
    before = _stock(db_connection)
    order_id = _new_order(db_connection)
    _add(db_connection, order_id, 1, 2)
    _add(db_connection, order_id, 1, 3)
    db_connection.commit()
    barrier = threading.Barrier(4)

    def cancel():
        connection = _connect(database_url)
        try:
            barrier.wait(timeout=5)
            result = _status(connection, order_id, 'Cancelled')
            connection.commit()
            return result
        finally:
            connection.rollback()
            connection.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(cancel) for _ in range(4)]
        assert [future.result(timeout=20) for future in futures] == [0, 0, 0, 0]
    assert _stock(db_connection) == before
    assert _total(db_connection, order_id) == Decimal('995000.00')


def test_failed_order_transaction_releases_reservation_for_later_order(db_connection, database_url):
    with db_connection.cursor() as cursor:
        cursor.execute('UPDATE ProductVariants SET Quantity = 1 WHERE VariantID = 1')
    db_connection.commit()
    connection = _connect(database_url)
    try:
        order_id = _new_order(connection)
        _add(connection, order_id, 1, 1)
        with pytest.raises(psycopg2.Error):
            _add(connection, order_id, 2, 10000)
        connection.rollback()
    finally:
        connection.close()
    assert _stock(db_connection) == 1
    successor = _new_order(db_connection)
    _add(db_connection, successor, 1, 1)
    assert _stock(db_connection) == 0
    assert _total(db_connection, successor) == Decimal('199000.00')


def test_delivered_only_revenue_views_functions_and_end_date_boundary(db_connection):
    # Seed already includes one Delivered, one Pending, and one Cancelled order.
    order_ids = {}
    for status in ['Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled']:
        order_id = _new_order(db_connection)
        order_ids[status] = order_id
        _add(db_connection, order_id, 2, 1)
        with db_connection.cursor() as cursor:
            cursor.execute(
                "UPDATE Orders SET OrderDate = TIMESTAMP '2026-04-30 23:59:59.999999' WHERE OrderID = %s", (order_id,)
            )
        if status == 'Cancelled':
            _status(db_connection, order_id, status)
        elif status != 'Pending':
            _status(db_connection, order_id, 'Processing')
            if status in {'Shipped', 'Delivered'}:
                _status(db_connection, order_id, 'Shipped')
            if status == 'Delivered':
                _status(db_connection, order_id, 'Delivered')
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT * FROM vw_MonthlyRevenue')
        month = cursor.fetchone()
        assert int(month.Year) == 2026
        assert int(month.Month) == 4
        assert month.OrderCount == 2
        assert month.TotalRevenue == Decimal('797000.00')
        cursor.execute('SELECT * FROM vw_CategoryRevenue ORDER BY CategoryID')
        category = cursor.fetchall()
        assert [(row.CategoryID, row.TotalQuantitySold, row.TotalRevenue) for row in category] == [
            (1, 2, Decimal('398000.00')),
            (2, 1, Decimal('399000.00')),
        ]
        cursor.execute('SELECT * FROM vw_BestSellingProducts ORDER BY ProductID')
        bestselling = cursor.fetchall()
        assert [(row.ProductID, row.TotalSold, row.TotalRevenue) for row in bestselling] == [
            (1, 2, Decimal('398000.00')),
            (2, 1, Decimal('399000.00')),
        ]
        cursor.execute("SELECT * FROM sp_GetRevenueByDateRange_Daily('2026-04-30', '2026-04-30')")
        daily = cursor.fetchall()
        assert [(row.OrderDate, row.OrderCount, row.DailyRevenue) for row in daily] == [
            (date(2026, 4, 30), 1, Decimal('399000.00'))
        ]
        cursor.execute("SELECT * FROM sp_GetRevenueByDateRange_Category('2026-04-30', '2026-04-30')")
        category = cursor.fetchall()
        assert [(row.CategoryID, row.TotalQuantitySold, row.CategoryRevenue) for row in category] == [
            (2, 1, Decimal('399000.00'))
        ]
        cursor.execute("SELECT * FROM sp_GetRevenueByDateRange_Daily('2026-05-01', '2026-05-02')")
        assert cursor.fetchall() == []


def test_application_order_service_reuses_atomic_functions_and_price_aliases(db_app, db_connection):
    from app.services.order_service import OrderService

    before = _stock(db_connection)
    with db_app.app_context():
        result = OrderService.create_order(
            1,
            OrderService.PAYMENT_METHOD,
            'Synthetic App Order Street',
            [{'variant_id': 1, 'quantity': 2, 'price': 0.01}],
        )
        assert result['success'] is True, result
        order_id = result['order_id']
        detail = OrderService.get_user_order_detail(order_id, 1)
        assert detail is not None
        item = detail['items'][0]
        assert item.Price == item.UnitPrice == Decimal('199000.00')
        assert OrderService.get_user_order_detail(order_id, 3) is None
        assert OrderService.cancel_order(order_id, 3)['success'] is False
        assert OrderService.cancel_order(order_id, 1)['success'] is True
        # Whether the service returns false or idempotent success, it cannot restock twice.
        OrderService.cancel_order(order_id, 1)
    assert _stock(db_connection) == before
    assert _total(db_connection, order_id) == Decimal('398000.00')


def test_application_order_failure_rolls_back_all_rows(db_app, db_connection):
    from app.services.order_service import OrderService

    before_one, before_two = _stock(db_connection, 1), _stock(db_connection, 2)
    order_count = _scalar(db_connection, 'SELECT COUNT(*) FROM Orders')
    with db_app.app_context():
        result = OrderService.create_order(
            1,
            OrderService.PAYMENT_METHOD,
            'Synthetic Rollback Street',
            [{'variant_id': 1, 'quantity': 1}, {'variant_id': 2, 'quantity': before_two + 1}],
        )
        assert result['success'] is False
        assert result.get('status_code') == 409, result
    assert _stock(db_connection, 1) == before_one
    assert _stock(db_connection, 2) == before_two
    assert _scalar(db_connection, 'SELECT COUNT(*) FROM Orders') == order_count


def test_separate_checkout_pages_and_concurrent_submits_share_one_order(db_app, db_client, db_connection, monkeypatch):
    from app.services.order_service import OrderService

    with db_connection.cursor() as cursor:
        cursor.execute('UPDATE ProductVariants SET Quantity = 1 WHERE VariantID = 1')
    db_connection.commit()
    creds = {'email': 'customer@example.test', 'password': 'TestUser123!'}
    assert db_client.post('/login', data=creds).status_code == 302
    assert db_client.post('/add_to_cart', json={'variant_id': 1, 'quantity': 1}).status_code == 200
    second_tab = db_app.test_client()
    second_tab.set_cookie('session', db_client.get_cookie('session').value)

    def fields(client):
        page = client.get('/checkout')
        assert page.status_code == 200
        soup = BeautifulSoup(page.data, 'html.parser')
        return {
            'checkout_review': soup.select_one('input[name=checkout_review]')['value'],
            'full_name': 'Concurrent Buyer',
            'phone': '0901234000',
            'email': 'concurrent@example.test',
            'shipping_address': 'One Synthetic Checkout Street',
            'order_notes': 'Checkout repeat integration',
            'payment_method': OrderService.PAYMENT_METHOD,
        }

    first_form, second_form = fields(db_client), fields(second_tab)
    lookup = OrderService.get_checkout_order
    both_looked_up = threading.Barrier(2)

    def force_concurrent_lookup(user_id, key):
        order_id = lookup(user_id, key)
        if order_id is None:
            both_looked_up.wait(timeout=5)
        return order_id

    monkeypatch.setattr(OrderService, 'get_checkout_order', force_concurrent_lookup)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(db_client.post, '/checkout', json=first_form)
        second = workers.submit(second_tab.post, '/checkout', json=second_form)
        results = [request.result(timeout=15) for request in (first, second)]
    assert [response.status_code for response in results] == [200, 200]
    assert results[0].json['order_id'] == results[1].json['order_id']
    order_id = results[0].json['order_id']
    assert db_client.post('/checkout', json=first_form).json['order_id'] == order_id
    assert _scalar(db_connection, 'SELECT COUNT(*) FROM Orders WHERE notes = %s', ('Checkout repeat integration',)) == 1
    assert _scalar(db_connection, 'SELECT SUM(Quantity) FROM OrderDetails WHERE OrderID = %s', (order_id,)) == 1
    assert _stock(db_connection) == 0


def test_parallel_adds_from_one_guest_cookie_keep_both_items(db_app, db_client, monkeypatch):
    from app.services.cart_service import CartService

    assert db_client.get('/cart').status_code == 200
    second = db_app.test_client()
    second.set_cookie('session', db_client.get_cookie('session').value)
    original_load = CartService.load
    first_reads = threading.Barrier(2)

    def load(cart_id):
        saved = original_load(cart_id)
        if saved is None:
            first_reads.wait(timeout=5)
        return saved

    monkeypatch.setattr(CartService, 'load', load)
    with ThreadPoolExecutor(max_workers=2) as workers:
        one = workers.submit(db_client.post, '/add_to_cart', json={'variant_id': 1})
        two = workers.submit(second.post, '/add_to_cart', json={'variant_id': 2})
        assert [request.result(timeout=15).status_code for request in (one, two)] == [200, 200]
    with db_client.session_transaction() as session:
        assert 'cart' not in session
        cart_id = session['cart_id']
    with db_app.app_context():
        assert CartService.load(cart_id)[1] == [{'variant_id': 1, 'quantity': 1}, {'variant_id': 2, 'quantity': 1}]
    assert (
        db_client.post('/login', data={'email': 'customer@example.test', 'password': 'TestUser123!'}).status_code == 302
    )
    with db_client.session_transaction() as session:
        assert session['cart_id'] == cart_id


@pytest.mark.parametrize(
    'path,fields',
    [
        ('/admin/products/1/variants/1/stock', {'delta': '1'}),
        ('/admin/products/add_variant', {'product_id': '1', 'color_id': '1', 'size_id': '1', 'quantity': '1'}),
    ],
)
def test_replayed_admin_stock_form_records_one_change(db_app, db_client, db_connection, path, fields):
    assert db_client.post('/login', data={'email': 'admin@example.test', 'password': 'TestUser123!'}).status_code == 302
    second = db_app.test_client()
    second.set_cookie('session', db_client.get_cookie('session').value)
    key = uuid4().hex
    data = {**fields, 'reason': 'Audit restock', 'operation_key': key}
    before = _stock(db_connection)
    with ThreadPoolExecutor(max_workers=2) as workers:
        one = workers.submit(db_client.post, path, data=data)
        two = workers.submit(second.post, path, data=data)
        assert [request.result(timeout=15).status_code for request in (one, two)] == [302, 302]
    assert _stock(db_connection) == before + 1
    assert _scalar(db_connection, 'SELECT count(*) FROM InventoryAdjustments WHERE operation_key = %s', (key,)) == 1
    assert db_client.post(path, data={**data, 'operation_key': uuid4().hex}).status_code == 302
    assert _stock(db_connection) == before + 2


def test_checkout_transaction_rechecks_reviewed_price_and_keeps_retry_available(db_app, db_connection):
    from app.services.order_service import OrderService

    before = _stock(db_connection)
    key = uuid4().hex
    with db_connection.cursor() as cursor:
        cursor.execute('UPDATE Products SET Price = 299000 WHERE ProductID = 1')
    db_connection.commit()
    args = (
        1,
        OrderService.PAYMENT_METHOD,
        'Reviewed Price Test Street',
        [{'variant_id': 1, 'quantity': 1}],
    )
    with db_app.app_context():
        stale = OrderService.create_order(*args, checkout_key=key, reviewed_prices={1: '199000.00'})
        assert not stale['success'] and stale['status_code'] == 409
        assert OrderService.get_checkout_order(1, key) is None
        assert _stock(db_connection) == before

        refreshed = OrderService.create_order(*args, checkout_key=key, reviewed_prices={1: '299000.00'})
        assert refreshed['success'] is True
        assert OrderService.get_checkout_order(3, key) is None
        other_customer = OrderService.create_order(3, *args[1:], checkout_key=key, reviewed_prices={1: '299000.00'})
        assert not other_customer['success'] and other_customer['status_code'] == 409

    assert _total(db_connection, refreshed['order_id']) == Decimal('299000.00')
    assert _stock(db_connection) == before - 1


def test_expired_product_upload_cleanup_keeps_saved_images(db_app, db_connection):
    import os
    import time
    from uuid import uuid4

    from app.services.product_service import ProductService
    from app.uploads import expired_product_uploads, remove_unused_product_uploads, upload_root

    with db_app.app_context():
        directory = upload_root() / 'products'
        directory.mkdir(parents=True)
        saved = directory / f'pixabay-1-{uuid4().hex}.jpg'
        abandoned = directory / f'pixabay-2-{uuid4().hex}.jpg'
        recent = directory / f'pixabay-3-{uuid4().hex}.jpg'
        for path in (saved, abandoned, recent):
            path.write_bytes(b'synthetic image')
        timestamp = time.time() - 25 * 60 * 60
        for path in (saved, abandoned):
            os.utime(path, (timestamp, timestamp))
        assert ProductService.update_product(1, 'Saved image', '', 100_000, 1, 120_000, f'images/{saved.name}')[
            'success'
        ]
        with db_connection.cursor() as cursor:
            remove_unused_product_uploads(cursor, expired_product_uploads())
        db_connection.commit()
        assert saved.exists() and recent.exists()
        assert not abandoned.exists()
        assert not ProductService.update_product(1, 'Expired', '', 100_000, 1, 120_000, f'images/{abandoned.name}')[
            'success'
        ]
