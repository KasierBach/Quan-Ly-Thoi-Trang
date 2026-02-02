from flask import render_template, request, redirect, url_for, flash
from app.database import get_db_connection
from .blueprint import admin_bp, admin_required

@admin_bp.route('/admin/customers')
@admin_required
def admin_customers():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '')
    role = request.args.get('role', 'all')
    sort_by = request.args.get('sort_by', 'newest')
    
    if page < 1: page = 1
    if per_page not in [10, 20, 50, 100]: per_page = 20
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Base query
    query = "SELECT * FROM Customers"
    count_query = "SELECT COUNT(*) FROM Customers"
    conditions = []
    params = []
    
    if search:
        conditions.append("(FullName ILIKE %s OR Email ILIKE %s OR PhoneNumber ILIKE %s)")
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param])
    
    if role == 'admin':
        conditions.append("IsAdmin = TRUE")
    elif role == 'customer':
        conditions.append("IsAdmin = FALSE")

    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)
        query += where_clause
        count_query += where_clause
    
    cursor.execute(count_query, params)
    total_records = cursor.fetchone()[0]
    
    # Sorting logic
    sort_query = "CreatedAt DESC"
    if sort_by == 'oldest': sort_query = "CreatedAt ASC"
    elif sort_by == 'name_asc': sort_query = "FullName ASC"
    elif sort_by == 'name_desc': sort_query = "FullName DESC"

    total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
    if page > total_pages: page = total_pages
    offset = (page - 1) * per_page
    
    query += f" ORDER BY {sort_query} LIMIT %s OFFSET %s"
    final_params = params + [per_page, offset]
    
    cursor.execute(query, final_params)
    customers = cursor.fetchall()
    
    conn.close()
    
    paging_data = {
        'total_records': total_records,
        'total_pages': total_pages,
        'current_page': page,
        'per_page': per_page,
        'start_index': offset + 1 if total_records > 0 else 0,
        'end_index': min(offset + per_page, total_records)
    }
    
    return render_template('admin/customers.html', customers=customers, paging=paging_data)

@admin_bp.route('/admin/customers/delete/<int:customer_id>', methods=['POST'])
@admin_required
def admin_delete_customer(customer_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if customer has orders
        cursor.execute("SELECT COUNT(*) FROM Orders WHERE CustomerID = %s", (customer_id,))
        if cursor.fetchone()[0] > 0:
            flash('Không thể xóa khách hàng đã có đơn hàng', 'error')
        else:
            cursor.execute("DELETE FROM Customers WHERE CustomerID = %s", (customer_id,))
            conn.commit()
            flash('Xóa khách hàng thành công', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin.admin_customers'))

@admin_bp.route('/admin/customers/<int:customer_id>')
@admin_required
def admin_customer_detail(customer_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM Customers WHERE CustomerID = %s", (customer_id,))
    customer = cursor.fetchone()
    
    if not customer:
        conn.close()
        flash('Khách hàng không tồn tại', 'error')
        return redirect(url_for('admin.admin_customers'))
    
    # Get order history
    cursor.execute("""
        SELECT o.*, 
               (SELECT SUM(Quantity * UnitPrice) FROM OrderDetails WHERE OrderID = o.OrderID) AS TotalAmount
        FROM Orders o 
        WHERE CustomerID = %s 
        ORDER BY OrderDate DESC
    """, (customer_id,))
    orders = cursor.fetchall()
    
    conn.close()
    return render_template('admin/customer_detail.html', customer=customer, orders=orders)
