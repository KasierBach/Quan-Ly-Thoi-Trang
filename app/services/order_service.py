from app.services.base_service import BaseService

class OrderService(BaseService):
    @staticmethod
    def create_order(user_id: int, payment_method: str, shipping_address: str, cart_items: list):
        """Create a new order and its details in a transaction."""
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                # 1. Create main order record via stored procedure
                cursor.execute('SELECT sp_CreateOrder(%s, %s, %s) AS OrderID', 
                             (user_id, payment_method, shipping_address))
                order_id = cursor.fetchone().OrderID
                
                # 2. Add order items
                for item in cart_items:
                    cursor.execute('SELECT sp_AddOrderDetail(%s, %s, %s)', 
                                 (order_id, item['variant_id'], item['quantity']))
                
                conn.commit()
                return {'success': True, 'order_id': order_id}
        except Exception as e:
            conn.rollback()
            return OrderService.handle_error(e, "Lỗi khi tạo đơn hàng. Vui lòng kiểm tra lại giỏ hàng.")
        finally:
            conn.close()

    @staticmethod
    def cancel_order(order_id, user_id):
        """Cancel an order only if it belongs to the user and is in 'Pending' status."""
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT Status, CustomerID FROM Orders WHERE OrderID = %s', (order_id,))
                order = cursor.fetchone()
                
                if not order: return {'success': False, 'message': 'Đơn hàng không tồn tại'}
                if order.CustomerID != user_id: return {'success': False, 'message': 'Không có quyền'}
                if order.Status != 'Pending': return {'success': False, 'message': 'Chỉ hủy được đơn ở trạng thái Chờ xử lý'}
                
                cursor.execute('SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, 'Cancelled'))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return OrderService.handle_error(e, "Lỗi khi hủy đơn hàng")
        finally:
            conn.close()

    @staticmethod
    def get_customer_orders(user_id):
        """Return a customer's orders for the account page."""
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT OrderID, OrderDate, TotalAmount, Status, PaymentMethod
                    FROM Orders
                    WHERE CustomerID = %s
                    ORDER BY OrderDate DESC
                ''', (user_id,))
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def get_user_order_detail(order_id, user_id):
        """Get order details with ownership verification."""
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM sp_GetOrderDetails_Main(%s)', (order_id,))
                order = cursor.fetchone()
                
                if not order or order.CustomerID != user_id: return None
                
                cursor.execute('''
                    SELECT od.Quantity, od.Price as UnitPrice, p.ProductName, 
                           c.ColorName, s.SizeName, p.ImageURL 
                    FROM OrderDetails od
                    JOIN ProductVariants pv ON od.VariantID = pv.VariantID
                    JOIN Products p ON pv.ProductID = p.ProductID
                    JOIN Colors c ON pv.ColorID = c.ColorID
                    JOIN Sizes s ON pv.SizeID = s.SizeID
                    WHERE od.OrderID = %s
                ''', (order_id,))
                items = cursor.fetchall()
                return {'order': order, 'items': items}
        finally:
            conn.close()

    @staticmethod
    def get_orders_admin(status, page, per_page):
        """Fetch orders for admin with filtering and pagination."""
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                where_clause = "WHERE o.Status = %s" if status else ""
                params = [status] if status else []
                
                cursor.execute(f"SELECT COUNT(*) FROM Orders o {where_clause}", params)
                total_records = cursor.fetchone()[0]
                total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
                page = min(max(1, page), total_pages)
                offset = (page - 1) * per_page
                
                query = f'''
                    SELECT o.*, c.FullName AS CustomerName, c.Email AS CustomerEmail 
                    FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID 
                    {where_clause} ORDER BY o.OrderDate DESC LIMIT %s OFFSET %s
                '''
                cursor.execute(query, params + [per_page, offset])
                orders = cursor.fetchall()
                
                return {
                    'orders': orders, 'total_records': total_records, 'total_pages': total_pages,
                    'current_page': page, 'per_page': per_page,
                    'start_index': offset + 1 if total_records > 0 else 0,
                    'end_index': min(offset + per_page, total_records)
                }
        finally:
            conn.close()

    @staticmethod
    def get_order_detail(order_id):
        """Get order details for admin (no ownership check)."""
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT o.*, c.FullName AS CustomerName, c.Email AS CustomerEmail, c.PhoneNumber AS CustomerPhone FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID WHERE o.OrderID = %s', (order_id,))
                order = cursor.fetchone()
                if not order: return None
                
                cursor.execute('''
                    SELECT od.Quantity, od.Price as UnitPrice, p.ProductName, 
                           c.ColorName, s.SizeName, p.ImageURL 
                    FROM OrderDetails od
                    JOIN ProductVariants pv ON od.VariantID = pv.VariantID
                    JOIN Products p ON pv.ProductID = p.ProductID
                    JOIN Colors c ON pv.ColorID = c.ColorID
                    JOIN Sizes s ON pv.SizeID = s.SizeID
                    WHERE od.OrderID = %s
                ''', (order_id,))
                return {'order': order, 'items': cursor.fetchall()}
        finally:
            conn.close()

    @staticmethod
    def update_order_status(order_id, new_status):
        """Update order status via stored procedure."""
        conn = OrderService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, new_status))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return OrderService.handle_error(e)
        finally:
            conn.close()
