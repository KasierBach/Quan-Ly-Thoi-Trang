from app.services.base_service import BaseService

class OrderService(BaseService):
    @staticmethod
    def get_orders(status, page, per_page):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            # Base query parts
            base_query = 'FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID'
            where_clause = f" WHERE o.Status = '{status}'" if status else ""
            
            # Count total records
            cursor.execute(f"SELECT COUNT(*) {base_query} {where_clause}")
            total_records = cursor.fetchone()[0]
            
            total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
            if page > total_pages: page = total_pages
            offset = (page - 1) * per_page
            
            query = f"SELECT o.*, c.FullName AS CustomerName, c.Email AS CustomerEmail {base_query} {where_clause} ORDER BY o.OrderDate DESC LIMIT %s OFFSET %s"
            
            cursor.execute(query, (per_page, offset))
            orders = cursor.fetchall()
            
            return {
                'orders': orders,
                'total_records': total_records,
                'total_pages': total_pages,
                'current_page': page,
                'per_page': per_page,
                'start_index': offset + 1 if total_records > 0 else 0,
                'end_index': min(offset + per_page, total_records)
            }
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_order_detail(order_id):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM sp_GetOrderDetails_Main(%s)', (order_id,))
            order = cursor.fetchone()
            
            if not order: return None
            
            cursor.execute('SELECT * FROM sp_GetOrderDetails_Items(%s)', (order_id,))
            order_details = cursor.fetchall()
            
            return {'order': order, 'items': order_details}
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def update_order_status(order_id, new_status):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, new_status))
            conn.commit()
            return {'success': True}
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()
