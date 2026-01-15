from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from app.database import get_db_connection
from werkzeug.utils import secure_filename
from app.utils import resolve_image
import requests
import os
import psycopg2

admin_bp = Blueprint('admin', __name__)

@admin_bp.before_request
def check_admin():
    # Allow login redirection or static files, but for API/pages we check
    pass 
    # Logic in app.py was app.before_request to check if user_id=19 => is_admin=True
    # We should keep that logic or move it here. 
    # Since it's global, let's put it in app.py middleware or here as a helper.
    # But individual routes check is_admin too. 

def is_admin():
    return 'user_id' in session and session.get('is_admin') == True

@admin_bp.route('/admin')
def admin_dashboard():
    if not is_admin():
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('main.home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM vw_MonthlyRevenue ORDER BY Year DESC, Month DESC')
    monthly_revenue = cursor.fetchall()
    cursor.execute('SELECT * FROM vw_CategoryRevenue ORDER BY TotalRevenue DESC')
    category_revenue = cursor.fetchall()
    cursor.execute('SELECT * FROM vw_BestSellingProducts')
    best_selling = cursor.fetchall()
    conn.close()
    
    return render_template('admin/dashboard.html', monthly_revenue=monthly_revenue, category_revenue=category_revenue, best_selling=best_selling, now=datetime.now())

@admin_bp.route('/admin/products')
def admin_products():
    if not is_admin(): return redirect(url_for('main.home'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.*, c.CategoryName,
        (SELECT COUNT(*) FROM ProductVariants WHERE ProductID = p.ProductID) AS VariantCount,
        (SELECT SUM(Quantity) FROM ProductVariants WHERE ProductID = p.ProductID) AS TotalStock
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        ORDER BY p.ProductID DESC
    ''')
    products = cursor.fetchall()
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    conn.close()
    return render_template('products.html', products=products, categories=categories)

@admin_bp.route('/admin/products/add', methods=['GET', 'POST'])
def admin_add_product():
    if not is_admin(): return redirect(url_for('main.home'))
    
    if request.method == 'POST':
        product_name = request.form.get('product_name')
        description = request.form.get('description')
        price = request.form.get('price', type=float)
        category_id = request.form.get('category_id', type=int)
        
        if not product_name or not price or not category_id:
            flash('Vui lòng điền đầy đủ thông tin', 'error')
            return redirect(url_for('admin.admin_add_product'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT sp_AddProduct(%s, %s, %s, %s) AS ProductID', (product_name, description, price, category_id))
            result = cursor.fetchone()
            product_id = result.ProductID
            conn.commit()
            flash('Thêm sản phẩm thành công!', 'success')
            return redirect(url_for('admin.admin_edit_product', product_id=product_id))
        except psycopg2.Error as e:
            conn.rollback()
            flash(f'Lỗi: {str(e)}', 'error')
            return redirect(url_for('admin.admin_add_product'))
        finally:
            conn.close()
            
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    conn.close()
    return render_template('admin/add_product.html', categories=categories)

@admin_bp.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
def admin_edit_product(product_id):
    if not is_admin(): return redirect(url_for('main.home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        product_name = request.form.get('product_name')
        description = request.form.get('description')
        price = request.form.get('price', type=float)
        category_id = request.form.get('category_id', type=int)
        
        if not product_name or not price or not category_id:
            flash('Thiếu thông tin', 'error')
            return redirect(url_for('admin.admin_edit_product', product_id=product_id))
        
        try:
            image_url = request.form.get('image_url', '').strip()
            cursor.execute('''
                UPDATE Products SET ProductName=%s, Description=%s, Price=%s, CategoryID=%s, ImageURL=%s
                WHERE ProductID=%s
            ''', (product_name, description, price, category_id, image_url, product_id))
            conn.commit()
            flash('Cập nhật thành công!', 'success')
        except psycopg2.Error as e:
            conn.rollback()
            flash(f'Lỗi: {str(e)}', 'error')
    
    cursor.execute('''
        SELECT p.*, c.CategoryName FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID WHERE p.ProductID = %s
    ''', (product_id,))
    product = cursor.fetchone()
    
    if not product:
        conn.close()
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(url_for('admin.admin_products'))
    
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    
    cursor.execute('''
        SELECT pv.*, c.ColorName, s.SizeName FROM ProductVariants pv
        JOIN Colors c ON pv.ColorID = c.ColorID
        JOIN Sizes s ON pv.SizeID = s.SizeID WHERE pv.ProductID = %s
    ''', (product_id,))
    variants = cursor.fetchall()
    
    cursor.execute('SELECT * FROM Colors')
    colors = cursor.fetchall()
    cursor.execute('SELECT * FROM Sizes')
    sizes = cursor.fetchall()
    conn.close()
    
    return render_template('admin/edit_product.html', product=product, categories=categories, variants=variants, colors=colors, sizes=sizes)

@admin_bp.route('/admin/products/add_variant', methods=['POST'])
def admin_add_variant():
    if not is_admin(): return redirect(url_for('main.home'))
    
    product_id = request.form.get('product_id', type=int)
    color_id = request.form.get('color_id', type=int)
    size_id = request.form.get('size_id', type=int)
    quantity = request.form.get('quantity', type=int)
    
    if not product_id or not color_id or not size_id or not quantity:
        flash('Thiếu thông tin biến thể', 'error')
        return redirect(url_for('admin.admin_edit_product', product_id=product_id))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT sp_AddProductVariant(%s, %s, %s, %s) AS VariantID', (product_id, color_id, size_id, quantity))
        conn.commit()
        flash('Thêm biến thể thành công!', 'success')
    except psycopg2.Error as e:
        conn.rollback()
        flash(f'Lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin.admin_edit_product', product_id=product_id))

@admin_bp.route('/admin/orders')
def admin_orders():
    if not is_admin(): return redirect(url_for('main.home'))
    status = request.args.get('status', '')
    conn = get_db_connection()
    cursor = conn.cursor()
    query = 'SELECT o.*, c.FullName AS CustomerName, c.Email AS CustomerEmail FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID'
    if status: query += f" WHERE o.Status = '{status}'"
    query += " ORDER BY o.OrderDate DESC"
    cursor.execute(query)
    orders = cursor.fetchall()
    conn.close()
    return render_template('admin/orders.html', orders=orders, current_status=status)

@admin_bp.route('/admin/orders/<int:order_id>')
def admin_order_detail(order_id):
    if not is_admin(): return redirect(url_for('main.home'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM sp_GetOrderDetails_Main(%s)', (order_id,))
    order = cursor.fetchone()
    cursor.execute('SELECT * FROM sp_GetOrderDetails_Items(%s)', (order_id,))
    order_details = cursor.fetchall()
    conn.close()
    if not order:
        flash('Đơn hàng không tồn tại', 'error')
        return redirect(url_for('admin.admin_orders'))
    return render_template('admin/order_detail.html', order=order, order_details=order_details)

@admin_bp.route('/admin/orders/update_status', methods=['POST'])
def admin_update_order_status():
    if not is_admin(): return redirect(url_for('main.home'))
    order_id = request.form.get('order_id', type=int)
    new_status = request.form.get('status')
    if not order_id or not new_status: return redirect(url_for('admin.admin_orders'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, new_status))
        conn.commit()
        flash('Cập nhật trạng thái thành công!', 'success')
    except psycopg2.Error as e:
        conn.rollback()
        flash(f'Lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin.admin_order_detail', order_id=order_id))

@admin_bp.route('/admin/reports')
def admin_reports():
    if not is_admin(): return redirect(url_for('main.home'))
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    if not start_date: start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    if not end_date: end_date = datetime.now().strftime('%Y-%m-%d')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM sp_GetRevenueByDateRange_Daily(%s, %s)', (start_date, end_date))
    daily_revenue = cursor.fetchall()
    cursor.execute('SELECT * FROM sp_GetRevenueByDateRange_Category(%s, %s)', (start_date, end_date))
    category_revenue = cursor.fetchall()
    cursor.execute('SELECT * FROM vw_BestSellingProducts')
    best_selling = cursor.fetchall()
    conn.close()
    
    dates = []
    revenues = []
    for row in daily_revenue:
        dates.append(row.OrderDate.strftime('%d/%m/%Y') if row.OrderDate else '')
        revenues.append(float(row.DailyRevenue) if row.DailyRevenue else 0.0)
    
    cat_names = []
    cat_revs = []
    for row in category_revenue:
        cat_names.append(row.CategoryName)
        cat_revs.append(float(row.CategoryRevenue) if row.CategoryRevenue else 0.0)
        
    return render_template('admin/reports.html', daily_revenue=daily_revenue, category_revenue=category_revenue, best_selling=best_selling, start_date=start_date, end_date=end_date, dates=json.dumps(dates), revenues=json.dumps(revenues), category_names=json.dumps(cat_names), category_revenues=json.dumps(cat_revs))

@admin_bp.route('/admin/api/search_pixabay', methods=['GET'])
def admin_search_pixabay():
    if not is_admin(): return jsonify({'success': False, 'message': 'Unauthorized'})
    query = request.args.get('q', '')
    if not query: return jsonify({'success': False})
    
    try:
        params = {
            'key': current_app.config['PIXABAY_API_KEY'], 
            'q': query,
            'image_type': 'photo',
            'per_page': 20,
            'safesearch': 'true'
        }
        resp = requests.get(current_app.config['PIXABAY_ENDPOINT'], params=params, timeout=10)
        resp.raise_for_status()
        return jsonify({'success': True, 'hits': resp.json().get('hits', [])})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/admin/api/save_pixabay_image', methods=['POST'])
def admin_save_pixabay_image():
    if not is_admin(): return jsonify({'success': False, 'message': 'Unauthorized'})
    data = request.json
    image_url = data.get('image_url')
    product_id = data.get('product_id')
    if not image_url or not product_id: return jsonify({'success': False})
    
    try:
        IMAGE_FOLDER = os.path.join(current_app.root_path, 'static', 'images')
        os.makedirs(IMAGE_FOLDER, exist_ok=True)
        filename = f"{product_id}.jpg"
        filepath = os.path.join(IMAGE_FOLDER, filename)
        
        r = requests.get(image_url, timeout=10)
        r.raise_for_status()
        with open(filepath, 'wb') as f: f.write(r.content)
        
        return jsonify({'success': True, 'path': f"images/{filename}"})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/admin/reply_comment', methods=['POST'])
def admin_reply_comment():
    if not is_admin(): return jsonify({'success': False, 'message': 'No permission'})
    comment_id = request.form.get('comment_id', type=int)
    reply = request.form.get('reply')
    if not comment_id or not reply: return jsonify({'success': False, 'message': 'Invalid data'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE ProductComments SET AdminReply = %s, ReplyDate = CURRENT_TIMESTAMP WHERE CommentID = %s', (reply, comment_id))
        conn.commit()
        return jsonify({'success': True, 'message': 'Success'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@admin_bp.route('/admin/contact_messages')
def admin_contact_messages():
    if not is_admin(): 
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('main.home'))
    
    status_filter = request.args.get('status', '')
    conn = get_db_connection()
    cursor = conn.cursor()
    query = 'SELECT * FROM ContactMessages'
    if status_filter: query += f" WHERE Status = '{status_filter}'"
    query += " ORDER BY SubmitDate DESC"
    cursor.execute(query)
    messages = cursor.fetchall()
    conn.close()
    return render_template('admin/contact_messages.html', messages=messages, current_status=status_filter)

@admin_bp.route('/admin/update_message_status', methods=['POST'])
def admin_update_message_status_json():
    if not is_admin(): return jsonify({'success': False}), 403
    message_id = request.form.get('message_id', type=int)
    new_status = request.form.get('status')
    if not message_id or not new_status: return jsonify({'success': False}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE ContactMessages SET Status = %s WHERE MessageID = %s', (new_status, message_id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

@admin_bp.route('/admin/comments')
def admin_comments():
    if not is_admin(): return redirect(url_for('main.home'))
    filter_type = request.args.get('filter', '')
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''
        SELECT pc.CommentID, pc.Content, pc.CommentDate, pc.AdminReply, pc.ReplyDate, pc.IsVisible,
               c.FullName AS CustomerName, p.ProductName, p.ProductID
        FROM ProductComments pc
        JOIN Customers c ON pc.CustomerID = c.CustomerID
        JOIN Products p ON pc.ProductID = p.ProductID
    '''
    if filter_type == 'no_reply': query += " WHERE pc.AdminReply IS NULL"
    elif filter_type == 'replied': query += " WHERE pc.AdminReply IS NOT NULL"
    query += " ORDER BY pc.CommentDate DESC"
    cursor.execute(query)
    comments = cursor.fetchall()
    conn.close()
    return render_template('admin/comments.html', comments=comments, filter=filter_type)

@admin_bp.route('/admin/toggle_comment_visibility', methods=['POST'])
def admin_toggle_comment_visibility():
    if not is_admin(): return jsonify({'success': False}), 403
    comment_id = request.form.get('comment_id', type=int)
    visible = request.form.get('visible', type=int)
    if not comment_id: return jsonify({'success': False})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE ProductComments SET IsVisible = %s WHERE CommentID = %s', (bool(visible), comment_id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@admin_bp.route('/admin/products/manage', methods=['GET', 'POST'])
def admin_manage_products():
    if not is_admin(): return redirect(url_for('main.home'))
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        product_name = request.form.get('product_name')
        description = request.form.get('description')
        price = request.form.get('price', type=float)
        category_id = request.form.get('category_id', type=int)
        
        if not product_name or not price or not category_id:
            flash('Vui lòng điền thông tin', 'error')
            conn.close()
            return redirect(url_for('admin.admin_manage_products'))
        
        try:
            cursor.execute('SELECT sp_AddProduct(%s, %s, %s, %s) AS ProductID', (product_name, description, price, category_id))
            conn.commit()
            flash('Thêm thành công', 'success')
        except Exception as e:
            conn.rollback()
            flash(str(e), 'error')
        conn.close()
        return redirect(url_for('admin.admin_manage_products'))
    
    cursor.execute('''
        SELECT p.*, c.CategoryName,
        (SELECT COUNT(*) FROM ProductVariants WHERE ProductID = p.ProductID) AS VariantCount,
        (SELECT SUM(Quantity) FROM ProductVariants WHERE ProductID = p.ProductID) AS TotalStock
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        ORDER BY p.ProductID DESC
    ''')
    products = cursor.fetchall()
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    conn.close()
    return render_template('admin/manage_products.html', products=products, categories=categories)

@admin_bp.route('/admin/products/delete/<int:product_id>', methods=['POST'])
def admin_delete_product(product_id):
    if not is_admin(): return redirect(url_for('main.home'))
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM ProductVariants WHERE ProductID = %s', (product_id,))
        cursor.execute('DELETE FROM Products WHERE ProductID = %s', (product_id,))
        conn.commit()
        flash('Xóa thành công', 'success')
    except Exception as e:
        conn.rollback()
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('admin.admin_manage_products'))

@admin_bp.route('/admin/colors/add', methods=['POST'])
def admin_add_color():
    if not is_admin(): return redirect(url_for('main.home'))
    color_name = request.form.get('color_name')
    if not color_name: return redirect(request.referrer)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO Colors (ColorName) VALUES (%s)', (color_name,))
        conn.commit()
        flash('Thêm màu thành công', 'success')
    except Exception as e: val = e
    finally: conn.close()
    return redirect(request.referrer)

@admin_bp.route('/admin/sizes/add', methods=['POST'])
def admin_add_size():
    if not is_admin(): return redirect(url_for('main.home'))
    size_name = request.form.get('size_name')
    if not size_name: return redirect(request.referrer)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO Sizes (SizeName) VALUES (%s)', (size_name,))
        conn.commit()
        flash('Thêm kích thước thành công', 'success')
    except Exception as e: val = e
    finally: conn.close()
    return redirect(request.referrer)
