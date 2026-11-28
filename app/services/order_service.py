from typing import Any

import psycopg2

from app.services.base_service import BaseService
from app.services.product_service import ProductService
from app.validation import (
    PHONE_NUMBER_FORMAT_MESSAGE,
    ValidationError,
    email_address,
    money,
    phone_number,
    positive_int,
    required_text,
)


class OrderService(BaseService):
    PAYMENT_METHOD = 'Thanh toán khi nhận hàng'
    STATUS_TRANSITIONS = {
        'Pending': {'Processing', 'Cancelled'},
        'Processing': {'Shipped', 'Cancelled'},
        'Shipped': {'Delivered'},
        'Delivered': set(),
        'Cancelled': set(),
    }

    @staticmethod
    def create_order(
        user_id: int,
        payment_method: str,
        shipping_address: str,
        cart_items: list,
        *,
        recipient_name=None,
        recipient_phone=None,
        recipient_email=None,
        notes='',
        checkout_key=None,
        reviewed_prices=None,
    ) -> dict[str, Any]:
        """Validate before writing and leave authoritative prices/stock to SQL atomics."""
        validation_message, validation_field = 'Khách hàng không hợp lệ', None
        try:
            user_id = positive_int(user_id, 'Khách hàng', ProductService.MAX_INTEGER)
            validation_message, validation_field = 'Địa chỉ giao hàng không hợp lệ', 'shipping_address'
            shipping_address = required_text(shipping_address, 'Địa chỉ giao hàng', 500)
            validation_message, validation_field = 'Phương thức thanh toán chưa được hỗ trợ', 'cod'
            payment_method = required_text(payment_method, 'Phương thức thanh toán', 100)
            if payment_method != OrderService.PAYMENT_METHOD:
                raise ValidationError(validation_message)
            validation_message, validation_field = 'Giỏ hàng không hợp lệ', None
            items = ProductService.normalize_cart_items(cart_items)
            if not items:
                return {'success': False, 'message': 'Giỏ hàng trống', 'status_code': 400}
            if any(value is not None for value in (recipient_name, recipient_phone, recipient_email)):
                validation_message, validation_field = 'Họ và tên không hợp lệ', 'full_name'
                recipient_name = required_text(recipient_name, 'Họ và tên', 255)
                validation_message, validation_field = PHONE_NUMBER_FORMAT_MESSAGE, 'phone'
                recipient_phone = phone_number(recipient_phone)
                validation_message, validation_field = 'Email không hợp lệ', 'email'
                recipient_email = email_address(recipient_email)
            validation_message, validation_field = 'Ghi chú không hợp lệ', 'order_notes'
            notes = ProductService.optional_text(notes, 'Ghi chú', 2000)
        except ValidationError:
            return {'success': False, 'message': validation_message, 'status_code': 400, 'field': validation_field}
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                if checkout_key is None:
                    cursor.execute(
                        'SELECT sp_CreateOrder(%s, %s, %s) AS OrderID',
                        (user_id, payment_method, shipping_address),
                    )
                    order_id = cursor.fetchone().OrderID
                else:
                    cursor.execute(
                        """
                        INSERT INTO Orders (CustomerID, PaymentMethod, ShippingAddress, checkout_key)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (checkout_key) DO NOTHING
                        RETURNING OrderID
                        """,
                        (user_id, payment_method, shipping_address, checkout_key),
                    )
                    order = cursor.fetchone()
                    if order is None:
                        existing_id = OrderService._find_checkout_order(cursor, user_id, checkout_key)
                        if existing_id is None:
                            raise ValidationError('Phiên đặt hàng không hợp lệ')
                        return {'success': True, 'order_id': existing_id}
                    order_id = order.OrderID
                    variant_ids = [item['variant_id'] for item in items]
                    # Hold the product price stable until the order details are written.
                    cursor.execute(
                        """
                        SELECT pv.VariantID, p.Price
                        FROM ProductVariants pv JOIN Products p ON p.ProductID = pv.ProductID
                        WHERE pv.VariantID = ANY(%s)
                        ORDER BY p.ProductID FOR SHARE OF p
                        """,
                        (variant_ids,),
                    )
                    prices = {row.VariantID: row.Price for row in cursor.fetchall()}
                    expected = {
                        variant_id: money(price, 'Giá sản phẩm')
                        for variant_id, price in (reviewed_prices or {}).items()
                    }
                    if prices != expected or len(prices) != len(items):
                        raise ValidationError(
                            'Giá hoặc sản phẩm đã thay đổi. Vui lòng kiểm tra lại trước khi đặt hàng.'
                        )
                if recipient_name is not None or notes:
                    cursor.execute(
                        """
                        UPDATE Orders
                        SET recipient_name = %s, recipient_phone = %s, recipient_email = %s, notes = %s
                        WHERE OrderID = %s
                    """,
                        (recipient_name, recipient_phone, recipient_email, notes, order_id),
                    )
                # A stable lock order avoids deadlocks across carts containing the same variants.
                for item in items:
                    cursor.execute(
                        'SELECT sp_AddOrderDetail(%s, %s, %s)',
                        (order_id, item['variant_id'], item['quantity']),
                    )
                conn.commit()
                return {'success': True, 'order_id': order_id}
        except ValidationError:
            conn.rollback()
            return {
                'success': False,
                'message': 'Không thể xác nhận phiên đặt hàng. Vui lòng kiểm tra lại sản phẩm và giá.',
                'status_code': 409,
            }
        except psycopg2.Error as exc:
            conn.rollback()
            if exc.pgcode in ('23514', 'P0001') or (checkout_key is not None and exc.pgcode == '23503'):
                return {
                    'success': False,
                    'message': 'Sản phẩm không đủ tồn kho hoặc giỏ hàng không hợp lệ',
                    'status_code': 409,
                }
            result = OrderService.handle_error(exc, 'Không thể tạo đơn hàng. Vui lòng thử lại sau.')
            result['status_code'] = 503
            return result
        except Exception as exc:
            conn.rollback()
            result = OrderService.handle_error(exc, 'Không thể tạo đơn hàng. Vui lòng thử lại sau.')
            result['status_code'] = 503
            return result
        finally:
            conn.close()

    @staticmethod
    def _find_checkout_order(cursor, user_id, checkout_key):
        cursor.execute(
            'SELECT OrderID FROM Orders WHERE CustomerID = %s AND checkout_key = %s',
            (user_id, checkout_key),
        )
        order = cursor.fetchone()
        return order.OrderID if order else None

    @staticmethod
    def get_checkout_order(user_id, checkout_key):
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                return OrderService._find_checkout_order(cursor, user_id, checkout_key)
        finally:
            conn.close()

    @staticmethod
    def cancel_order(order_id, user_id) -> dict[str, Any]:
        """Lock an owner-scoped pending order so cancelling cannot race fulfilment."""
        try:
            order_id = positive_int(order_id, 'Đơn hàng', ProductService.MAX_INTEGER)
            user_id = positive_int(user_id, 'Khách hàng', ProductService.MAX_INTEGER)
        except ValidationError:
            return {'success': False, 'message': 'Đơn hàng hoặc khách hàng không hợp lệ', 'status_code': 400}
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT Status FROM Orders WHERE OrderID = %s AND CustomerID = %s FOR UPDATE
                """,
                    (order_id, user_id),
                )
                order = cursor.fetchone()
                if not order:
                    return {'success': False, 'message': 'Đơn hàng không tồn tại', 'status_code': 404}
                if order.Status != 'Pending':
                    return {
                        'success': False,
                        'message': 'Chỉ hủy được đơn ở trạng thái Chờ xử lý',
                        'status_code': 409,
                    }
                OrderService._record_actor(cursor, user_id)
                cursor.execute('SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, 'Cancelled'))
                conn.commit()
                return {'success': True, 'message': 'Đã hủy đơn hàng'}
        except Exception as exc:
            conn.rollback()
            result = OrderService.handle_error(exc, 'Không thể hủy đơn hàng. Vui lòng thử lại sau.')
            result['status_code'] = 503
            return result
        finally:
            conn.close()

    @staticmethod
    def get_customer_orders(user_id, page=1):
        user_id = positive_int(user_id, 'Khách hàng', ProductService.MAX_INTEGER)
        page = positive_int(page, 'Trang', ProductService.MAX_INTEGER)
        page_size = 12
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    WITH history AS (
                        SELECT COUNT(*) AS total_orders,
                               COALESCE(SUM(TotalAmount) FILTER (WHERE Status = 'Delivered'), 0) AS total_spent,
                               LEAST(%s, GREATEST(1, (COUNT(*) + %s - 1) / %s)) AS current_page
                        FROM Orders WHERE CustomerID = %s
                    )
                    SELECT history.*, orders.*
                    FROM history
                    LEFT JOIN LATERAL (
                        SELECT OrderID, OrderDate, TotalAmount, Status, PaymentMethod
                        FROM Orders WHERE CustomerID = %s
                        ORDER BY OrderDate DESC, OrderID DESC
                        LIMIT %s OFFSET ((history.current_page - 1) * %s)
                    ) orders ON TRUE
                    ORDER BY orders.OrderDate DESC, orders.OrderID DESC
                    """,
                    (page, page_size, page_size, user_id, user_id, page_size, page_size),
                )
                rows = cursor.fetchall()
                totals = rows[0]
                return {
                    'orders': [row for row in rows if row.OrderID is not None],
                    'total_orders': totals.total_orders,
                    'total_spent': totals.total_spent,
                    'current_page': totals.current_page,
                    'total_pages': max(1, (totals.total_orders + page_size - 1) // page_size),
                }
        finally:
            conn.close()

    @staticmethod
    def get_user_order_detail(order_id, user_id):
        """Scope the first query by owner before fetching order items."""
        order_id = positive_int(order_id, 'Đơn hàng', ProductService.MAX_INTEGER)
        user_id = positive_int(user_id, 'Khách hàng', ProductService.MAX_INTEGER)
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT o.*, c.FullName AS CustomerName, c.PhoneNumber AS CustomerPhone, c.Email AS CustomerEmail
                    FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID
                    WHERE o.OrderID = %s AND o.CustomerID = %s
                """,
                    (order_id, user_id),
                )
                order = cursor.fetchone()
                if not order:
                    return None
                cursor.execute(
                    """
                    SELECT od.Quantity, od.Price, od.Price AS UnitPrice,
                           od.Price * od.Quantity AS Subtotal, p.ProductName,
                           c.ColorName, s.SizeName, p.ImageURL
                    FROM OrderDetails od
                    JOIN ProductVariants pv ON od.VariantID = pv.VariantID
                    JOIN Products p ON pv.ProductID = p.ProductID
                    JOIN Colors c ON pv.ColorID = c.ColorID
                    JOIN Sizes s ON pv.SizeID = s.SizeID
                    WHERE od.OrderID = %s ORDER BY od.OrderDetailID
                """,
                    (order_id,),
                )
                items = cursor.fetchall()
                return {
                    'order': order,
                    'items': items,
                    'status_history': OrderService._status_history(cursor, order_id),
                }
        finally:
            conn.close()

    @staticmethod
    def get_orders_admin(status, page, per_page):
        """Fetch orders for admin with filtering and bounded pagination."""
        if status is not None and (
            not isinstance(status, str) or (status and status not in OrderService.STATUS_TRANSITIONS)
        ):
            raise ValidationError('Trạng thái đơn hàng không hợp lệ')
        try:
            page = positive_int(page, 'Trang', ProductService.MAX_INTEGER)
        except ValidationError:
            page = 1
        try:
            per_page = positive_int(per_page, 'Số đơn hàng mỗi trang')
        except ValidationError:
            per_page = 20
        if per_page not in (10, 20, 50, 100):
            per_page = 20
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                where_clause = 'WHERE o.Status = %s' if status else ''
                params = [status] if status else []
                cursor.execute(f'SELECT COUNT(*) FROM Orders o {where_clause}', params)
                total_records = cursor.fetchone()[0]
                total_pages = max(1, (total_records + per_page - 1) // per_page)
                page = min(page, total_pages)
                offset = (page - 1) * per_page
                cursor.execute(
                    f"""
                    SELECT o.*, c.FullName AS CustomerName, c.Email AS CustomerEmail
                    FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID
                    {where_clause} ORDER BY o.OrderDate DESC, o.OrderID DESC LIMIT %s OFFSET %s
                """,
                    params + [per_page, offset],
                )
                return {
                    'orders': cursor.fetchall(),
                    'total_records': total_records,
                    'total_pages': total_pages,
                    'current_page': page,
                    'per_page': per_page,
                    'start_index': offset + 1 if total_records else 0,
                    'end_index': min(offset + per_page, total_records),
                }
        finally:
            conn.close()

    @staticmethod
    def get_order_detail(order_id):
        """Get order details for routes protected by the admin role guard."""
        order_id = positive_int(order_id, 'Đơn hàng', ProductService.MAX_INTEGER)
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT o.*, c.FullName AS CustomerName, c.Email AS CustomerEmail, c.PhoneNumber AS CustomerPhone
                    FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID WHERE o.OrderID = %s
                """,
                    (order_id,),
                )
                order = cursor.fetchone()
                if not order:
                    return None
                cursor.execute(
                    """
                    SELECT od.Quantity, od.Price, od.Price AS UnitPrice,
                           od.Price * od.Quantity AS Subtotal, p.ProductName,
                           c.ColorName, s.SizeName, p.ImageURL
                    FROM OrderDetails od
                    JOIN ProductVariants pv ON od.VariantID = pv.VariantID
                    JOIN Products p ON pv.ProductID = p.ProductID
                    JOIN Colors c ON pv.ColorID = c.ColorID
                    JOIN Sizes s ON pv.SizeID = s.SizeID
                    WHERE od.OrderID = %s ORDER BY od.OrderDetailID
                """,
                    (order_id,),
                )
                items = cursor.fetchall()
                return {
                    'order': order,
                    'items': items,
                    'status_history': OrderService._status_history(cursor, order_id),
                }
        finally:
            conn.close()

    @staticmethod
    def _status_history(cursor, order_id):
        cursor.execute(
            """SELECT status, occurred_at, occurred_at AT TIME ZONE 'Asia/Ho_Chi_Minh' AS local_time,
                      actor_name, actor_role
               FROM OrderStatusEvents WHERE order_id = %s ORDER BY id DESC""",
            (order_id,),
        )
        return cursor.fetchall()

    @staticmethod
    def _record_actor(cursor, actor_id):
        cursor.execute("SELECT set_config('thua2.order_actor_id', %s, true)", (str(actor_id),))

    @staticmethod
    def update_order_status(order_id, new_status, actor_id=None) -> dict[str, Any]:
        """Permit only idempotent or forward state transitions under the order lock."""
        try:
            order_id = positive_int(order_id, 'Đơn hàng', ProductService.MAX_INTEGER)
            if actor_id is not None:
                actor_id = positive_int(actor_id, 'Người cập nhật', ProductService.MAX_INTEGER)
            if not isinstance(new_status, str) or new_status not in OrderService.STATUS_TRANSITIONS:
                raise ValidationError('Trạng thái đơn hàng không hợp lệ')
        except ValidationError as exc:
            return {'success': False, 'message': str(exc), 'status_code': 400}
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT Status FROM Orders WHERE OrderID = %s FOR UPDATE', (order_id,))
                order = cursor.fetchone()
                if not order:
                    return {'success': False, 'message': 'Đơn hàng không tồn tại', 'status_code': 404}
                if new_status == order.Status:
                    return {'success': True}
                if new_status not in OrderService.STATUS_TRANSITIONS.get(order.Status, set()):
                    return {'success': False, 'message': 'Không thể chuyển về trạng thái này', 'status_code': 409}
                if actor_id is not None:
                    OrderService._record_actor(cursor, actor_id)
                cursor.execute('SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, new_status))
                conn.commit()
                return {'success': True}
        except Exception as exc:
            conn.rollback()
            result = OrderService.handle_error(exc, 'Không thể cập nhật trạng thái đơn hàng. Vui lòng thử lại sau.')
            result['status_code'] = 503
            return result
        finally:
            conn.close()
