from decimal import Decimal

from app.validation import ValidationError, positive_int

from .base_service import BaseService


class CustomerService(BaseService):
    PROFILE_COLUMNS = 'CustomerID, FullName, Email, PhoneNumber, Address, CreatedAt, IsAdmin'
    SORTS = {
        'oldest': 'CreatedAt ASC, CustomerID ASC',
        'name_asc': 'FullName ASC, CustomerID ASC',
        'name_desc': 'FullName DESC, CustomerID DESC',
        'newest': 'CreatedAt DESC, CustomerID DESC',
    }

    @staticmethod
    def search_customers(search_term='', role='all', page=1, per_page=20, sort_by='newest'):
        page = positive_int(page, 'Trang', max_value=1000000)
        per_page = positive_int(per_page, 'Số dòng', max_value=100)
        if role not in {'all', 'admin', 'customer'} or sort_by not in CustomerService.SORTS:
            raise ValidationError('Bộ lọc khách hàng không hợp lệ')
        if not isinstance(search_term, str) or len(search_term) > 200 or '\x00' in search_term:
            raise ValidationError('Từ khóa tìm kiếm không hợp lệ')
        search_term = search_term.strip()
        conn = CustomerService.get_connection()
        try:
            with conn.cursor() as cursor:
                clauses, params = [], []
                if search_term:
                    clauses.append('(FullName ILIKE %s OR Email ILIKE %s OR PhoneNumber ILIKE %s)')
                    # Search text literally, rather than interpreting user %/_ as wildcards.
                    pattern = '%' + search_term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                    params.extend([pattern] * 3)
                if role == 'admin':
                    clauses.append('IsAdmin = TRUE')
                elif role == 'customer':
                    clauses.append('IsAdmin = FALSE')
                where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
                cursor.execute(f'SELECT COUNT(*) FROM Customers{where}', params)
                total = cursor.fetchone()[0]
                total_pages = max(1, (total + per_page - 1) // per_page)
                page = min(page, total_pages)
                offset = (page - 1) * per_page
                cursor.execute(
                    f"""
                    SELECT {CustomerService.PROFILE_COLUMNS} FROM Customers{where}
                    ORDER BY {CustomerService.SORTS[sort_by]} LIMIT %s OFFSET %s
                """,
                    params + [per_page, offset],
                )
                return {
                    'customers': cursor.fetchall(),
                    'total_records': total,
                    'total_pages': total_pages,
                    'current_page': page,
                    'per_page': per_page,
                    'start_index': offset + 1 if total else 0,
                    'end_index': min(offset + per_page, total),
                }
        finally:
            conn.close()

    @staticmethod
    def get_customer_details(customer_id):
        customer_id = positive_int(customer_id, 'Khách hàng', max_value=2147483647)
        conn = CustomerService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'SELECT {CustomerService.PROFILE_COLUMNS} FROM Customers WHERE CustomerID = %s', (customer_id,)
                )
                customer = cursor.fetchone()
                if not customer:
                    return None
                # TotalAmount is the canonical booked order total; never duplicate its alias.
                cursor.execute(
                    """
                    SELECT OrderID, OrderDate, TotalAmount, Status
                    FROM Orders WHERE CustomerID = %s ORDER BY OrderDate DESC, OrderID DESC
                """,
                    (customer_id,),
                )
                orders = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT pc.CommentID, pc.ProductID, pc.Content, pc.CommentDate, pc.AdminReply, pc.ReplyDate,
                           p.ProductName
                    FROM ProductComments pc JOIN Products p ON p.ProductID = pc.ProductID
                    WHERE pc.CustomerID = %s ORDER BY pc.CommentDate DESC, pc.CommentID DESC
                """,
                    (customer_id,),
                )
                comments = cursor.fetchall()
                delivered = [order for order in orders if order.Status == 'Delivered']
                stats = {
                    'totalorders': len(orders),
                    'deliveredorders': len(delivered),
                    'totalspent': sum((Decimal(str(order.TotalAmount or 0)) for order in delivered), Decimal('0')),
                }
                return {'customer': customer, 'orders': orders, 'comments': comments, 'stats': stats}
        finally:
            conn.close()

    @staticmethod
    def delete_customer(customer_id, actor_id=None):
        """Never delete administrators, oneself, or a customer's persisted history."""
        customer_id = positive_int(customer_id, 'Khách hàng', max_value=2147483647)
        if actor_id is not None:
            actor_id = positive_int(actor_id, 'Tài khoản hiện tại', max_value=2147483647)
            if customer_id == actor_id:
                return {'success': False, 'message': 'Không thể xóa tài khoản hiện tại', 'status_code': 409}
        conn = CustomerService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT CustomerID, IsAdmin FROM Customers WHERE CustomerID = %s FOR UPDATE', (customer_id,)
                )
                customer = cursor.fetchone()
                if not customer:
                    return {'success': False, 'message': 'Khách hàng không tồn tại', 'status_code': 404}
                if customer.IsAdmin:
                    return {'success': False, 'message': 'Không thể xóa tài khoản quản trị viên', 'status_code': 409}
                cursor.execute(
                    """
                    SELECT EXISTS(SELECT 1 FROM Orders WHERE CustomerID = %s)
                        OR EXISTS(SELECT 1 FROM Reviews WHERE CustomerID = %s)
                        OR EXISTS(SELECT 1 FROM ProductComments WHERE CustomerID = %s)
                        OR EXISTS(SELECT 1 FROM Messages WHERE user_id = %s)
                        OR EXISTS(SELECT 1 FROM Participants WHERE user_id = %s)
                        OR EXISTS(SELECT 1 FROM Conversations WHERE created_by = %s)
                        OR EXISTS(SELECT 1 FROM Reactions WHERE user_id = %s)
                        OR EXISTS(SELECT 1 FROM PinnedMessages WHERE pinned_by = %s)
                """,
                    (customer_id,) * 8,
                )
                if cursor.fetchone()[0]:
                    return {
                        'success': False,
                        'message': 'Không thể xóa khách hàng đã có lịch sử giao dịch hoặc tương tác',
                        'status_code': 409,
                    }
                cursor.execute('DELETE FROM Customers WHERE CustomerID = %s RETURNING CustomerID', (customer_id,))
                if not cursor.fetchone():
                    conn.rollback()
                    return {'success': False, 'message': 'Khách hàng không tồn tại', 'status_code': 404}
                conn.commit()
                return CustomerService.success(message='Xóa khách hàng thành công')
        except Exception as exc:
            conn.rollback()
            if getattr(exc, 'pgcode', None) == '23503':
                return {
                    'success': False,
                    'message': 'Không thể xóa khách hàng đang được tham chiếu',
                    'status_code': 409,
                }
            result = CustomerService.handle_error(exc)
            result['status_code'] = 500
            return result
        finally:
            conn.close()
