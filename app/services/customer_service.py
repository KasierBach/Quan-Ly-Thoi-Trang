from .base_service import BaseService

class CustomerService(BaseService):
    @staticmethod
    def search_customers(search_term='', role='all', page=1, per_page=20, sort_by='newest'):
        """Search and paginate customers with filters."""
        conn = CustomerService.get_connection()
        try:
            with conn.cursor() as cursor:
                # Base query
                where_clauses = []
                params = []
                
                if search_term:
                    where_clauses.append("(FullName ILIKE %s OR Email ILIKE %s OR PhoneNumber ILIKE %s)")
                    pattern = f"%{search_term}%"
                    params.extend([pattern, pattern, pattern])
                
                if role == 'admin':
                    where_clauses.append("IsAdmin = TRUE")
                elif role == 'customer':
                    where_clauses.append("IsAdmin = FALSE")

                where_stmt = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
                
                # Count total
                cursor.execute(f"SELECT COUNT(*) FROM Customers{where_stmt}", params)
                total_records = cursor.fetchone()[0]
                
                total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
                page = min(max(1, page), total_pages)
                offset = (page - 1) * per_page
                
                # Sorting
                sort_map = {
                    'oldest': 'CreatedAt ASC',
                    'name_asc': 'FullName ASC',
                    'name_desc': 'FullName DESC',
                    'newest': 'CreatedAt DESC'
                }
                sort_stmt = sort_map.get(sort_by, 'CreatedAt DESC')
                
                # Final query
                query = f"SELECT * FROM Customers{where_stmt} ORDER BY {sort_stmt} LIMIT %s OFFSET %s"
                cursor.execute(query, params + [per_page, offset])
                customers = cursor.fetchall()
                
                return {
                    'customers': customers,
                    'total_records': total_records,
                    'total_pages': total_pages,
                    'current_page': page,
                    'per_page': per_page,
                    'start_index': offset + 1 if total_records > 0 else 0,
                    'end_index': min(offset + per_page, total_records)
                }
        finally:
            conn.close()

    @staticmethod
    def get_customer_details(customer_id):
        """Get customer profile and order history."""
        conn = CustomerService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM Customers WHERE CustomerID = %s", (customer_id,))
                customer = cursor.fetchone()
                if not customer: return None
                
                cursor.execute("""
                    SELECT o.*, 
                           (SELECT SUM(Quantity * Price) FROM OrderDetails WHERE OrderID = o.OrderID) AS TotalAmount
                    FROM Orders o 
                    WHERE CustomerID = %s 
                    ORDER BY OrderDate DESC
                """, (customer_id,))
                orders = cursor.fetchall()
                
                # Fetch comments
                cursor.execute("""
                    SELECT pc.*, p.ProductName 
                    FROM ProductComments pc
                    JOIN Products p ON pc.ProductID = p.ProductID
                    WHERE pc.CustomerID = %s
                    ORDER BY pc.CommentDate DESC
                """, (customer_id,))
                comments = cursor.fetchall()
                
                # Compute stats safely
                total_spent = 0
                for o in orders:
                    try:
                        amt = getattr(o, 'totalamount', None) or getattr(o, 'TotalAmount', None) or 0
                        total_spent += float(amt)
                    except (TypeError, ValueError):
                        pass
                    
                stats = {
                    'totalorders': len(orders),
                    'totalspent': total_spent
                }
                
                return {'customer': customer, 'orders': orders, 'comments': comments, 'stats': stats}
        finally:
            conn.close()

    @staticmethod
    def delete_customer(customer_id):
        """Delete customer if they have no orders."""
        conn = CustomerService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM Orders WHERE CustomerID = %s", (customer_id,))
                if cursor.fetchone()[0] > 0:
                    return {'success': False, 'message': 'Không thể xóa khách hàng đã có đơn hàng'}
                
                cursor.execute("DELETE FROM Customers WHERE CustomerID = %s", (customer_id,))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return BaseService.handle_error(e)
        finally:
            conn.close()
