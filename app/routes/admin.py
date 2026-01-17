from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from flask_mail import Message
from app.database import get_db_connection
from werkzeug.utils import secure_filename
from app.utils import resolve_image
from datetime import datetime, timedelta
import json
import requests
import os
import psycopg2
import socket
import resend

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
    
    today = datetime.now()
    current_month_revenue = 0
    current_month_orders = 0
    
    for r in monthly_revenue:
        try:
            r_year = int(r.Year)
            r_month = int(r.Month)
            if r_year == today.year and r_month == today.month:
                current_month_revenue = r.TotalRevenue
                current_month_orders = r.OrderCount
                break
        except (ValueError, TypeError, AttributeError):
            continue
            
    total_sold = sum(p.TotalSold for p in best_selling)
    
    # Get new customers count for current month
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM Customers WHERE EXTRACT(YEAR FROM CreatedAt) = %s AND EXTRACT(MONTH FROM CreatedAt) = %s', (today.year, today.month))
    new_customers = cursor.fetchone()[0]
    conn.close()
    
    return render_template('admin/dashboard.html', 
                           monthly_revenue=monthly_revenue, 
                           category_revenue=category_revenue, 
                           best_selling=best_selling, 
                           now=today,
                           current_month_revenue=current_month_revenue,
                           current_month_orders=current_month_orders,
                           total_sold=total_sold,
                           new_customers=new_customers)


@admin_bp.route('/admin/products')
def admin_products():
    if not is_admin(): return redirect(url_for('main.home'))
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    sort_by = request.args.get('sort_by', 'newest')
    
    if page < 1: page = 1
    if per_page not in [12, 24, 48]: per_page = 12

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Sorting logic
    sort_query = "p.ProductID DESC"
    if sort_by == 'price_asc': sort_query = "p.Price ASC"
    elif sort_by == 'price_desc': sort_query = "p.Price DESC"
    elif sort_by == 'name_asc': sort_query = "p.ProductName ASC"
    
    # Count total records
    cursor.execute("SELECT COUNT(*) FROM Products")
    total_records = cursor.fetchone()[0]
    
    total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
    if page > total_pages: page = total_pages
    offset = (page - 1) * per_page
    
    cursor.execute(f'''
        SELECT p.*, c.CategoryName,
        (SELECT COUNT(*) FROM ProductVariants WHERE ProductID = p.ProductID) AS VariantCount,
        (SELECT SUM(Quantity) FROM ProductVariants WHERE ProductID = p.ProductID) AS TotalStock
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        ORDER BY {sort_query}
        LIMIT %s OFFSET %s
    ''', (per_page, offset))
    products = cursor.fetchall()
    
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    conn.close()
    
    paging_data = {
        'total_records': total_records,
        'total_pages': total_pages,
        'current_page': page,
        'per_page': per_page,
        'start_index': offset + 1 if total_records > 0 else 0,
        'end_index': min(offset + per_page, total_records)
    }
    
    return render_template('products.html', products=products, categories=categories, paging=paging_data, sort=sort_by)

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
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    if page < 1: page = 1
    if per_page not in [10, 20, 50, 100]: per_page = 20

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Base query parts
    base_query = 'FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID'
    where_clause = f" WHERE o.Status = '{status}'" if status else ""
    
    # Count total records
    cursor.execute(f"SELECT COUNT(*) {base_query} {where_clause}")
    total_records = cursor.fetchone()[0]
    
    total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
    
    # Boundary logic: cap page at total_pages
    if page > total_pages: page = total_pages
    
    offset = (page - 1) * per_page
    
    query = f"SELECT o.*, c.FullName AS CustomerName, c.Email AS CustomerEmail {base_query} {where_clause} ORDER BY o.OrderDate DESC LIMIT %s OFFSET %s"
    
    cursor.execute(query, (per_page, offset))
    orders = cursor.fetchall()
    conn.close()
    
    paging_data = {
        'total_records': total_records,
        'total_pages': total_pages,
        'current_page': page,
        'per_page': per_page,
        'start_index': offset + 1 if total_records > 0 else 0,
        'end_index': min(offset + per_page, total_records)
    }
    
    return render_template('admin/orders.html', orders=orders, current_status=status, paging=paging_data)

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
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date: 
        # Default to all time (earliest order)
        try:
            cursor.execute("SELECT MIN(OrderDate) FROM Orders")
            min_date_row = cursor.fetchone()
            if min_date_row and min_date_row[0]:
                start_date = min_date_row[0].strftime('%Y-%m-%d')
            else:
                start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        except:
             start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

    if not end_date: end_date = datetime.now().strftime('%Y-%m-%d')
    
    cursor.execute('SELECT * FROM sp_GetRevenueByDateRange_Daily(%s, %s)', (start_date, end_date))
    daily_revenue = cursor.fetchall()
    cursor.execute('SELECT * FROM sp_GetRevenueByDateRange_Category(%s, %s)', (start_date, end_date))
    category_revenue = cursor.fetchall()
    cursor.execute('SELECT * FROM vw_BestSellingProducts')
    best_selling = cursor.fetchall()
    today = datetime.now()
    dates = []
    revenues = []
    total_rev = 0
    total_ord = 0
    
    for row in daily_revenue:
        dates.append(row.OrderDate.strftime('%d/%m/%Y') if row.OrderDate else '')
        rev = float(row.DailyRevenue) if row.DailyRevenue else 0.0
        total_rev += rev
        total_ord += (row.OrderCount or 0)
        revenues.append(rev)
    
    cat_names = []
    cat_revs = []
    for row in category_revenue:
        cat_names.append(row.CategoryName)
        cat_revs.append(float(row.CategoryRevenue) if row.CategoryRevenue else 0.0)
    
    # Get new customers count for the date range
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM Customers WHERE CAST(CreatedAt AS DATE) BETWEEN %s AND %s', (start_date, end_date))
    new_customers_range = cursor.fetchone()[0]
    conn.close()
        
    return render_template('admin/reports.html', 
                           daily_revenue=daily_revenue, 
                           category_revenue=category_revenue, 
                           best_selling=best_selling, 
                           now=today,
                           start_date=start_date, 
                           end_date=end_date, 
                           dates=json.dumps(dates), 
                           revenues=json.dumps(revenues), 
                           category_names=json.dumps(cat_names), 
                           category_revenues=json.dumps(cat_revs),
                           total_revenue=total_rev,
                            total_orders=total_ord,
                           new_customers=new_customers_range)

@admin_bp.route('/admin/api/send_report_email', methods=['POST'])
def admin_send_report_email():
    if not is_admin(): return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    data = request.get_json()
    recipient = data.get('email')
    user_message = data.get('message', '')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    
    if not recipient:
        return jsonify({'success': False, 'message': 'Email recipient is required'}), 400
    
    # Check if a mail provider is configured
    resend_key = current_app.config.get('RESEND_API_KEY')
    mail_user = current_app.config.get('MAIL_USERNAME')
    mail_pass = current_app.config.get('MAIL_PASSWORD')
    
    if not resend_key and (not mail_user or not mail_pass):
        return jsonify({
            'success': False, 
            'message': 'Hệ thống chưa cấu hình Email (RESEND_API_KEY hoặc SMTP credentials).'
        }), 500
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Fetch data similar to admin_reports
        cursor.execute('SELECT * FROM sp_GetRevenueByDateRange_Daily(%s, %s)', (start_date, end_date))
        daily_revenue = cursor.fetchall()
        
        # Create CSV content
        import io
        import csv
        import base64
        
        output = io.StringIO()
        # Add UTF-8 BOM for Excel
        output.write('\ufeff')
        writer = csv.writer(output)
        writer.writerow(['Ngày', 'Số đơn hàng', 'Doanh thu (VNĐ)'])
        
        for row in daily_revenue:
            date_str = row.OrderDate.strftime('%d/%m/%Y') if row.OrderDate else 'N/A'
            writer.writerow([date_str, row.OrderCount, float(row.DailyRevenue) if row.DailyRevenue else 0])
            
        csv_data = output.getvalue()
        filename = f"bao_cao_doanh_thu_{start_date}_den_{end_date}.csv"

        subject = f"Báo cáo doanh thu FashionStore ({start_date} - {end_date})"
        body_content = f"Xin chào,\n\nDưới đây là báo cáo doanh thu từ ngày {start_date} đến ngày {end_date}.\n\nLời nhắn từ quản trị viên: {user_message}\n\nTrân trọng,\nFashionStore Admin Team"

        # Try Resend API first (Preferred for Render)
        if resend_key:
            print(f"Sending email via Resend API to {recipient}...")
            resend.api_key = resend_key
            sender = current_app.config.get('MAIL_DEFAULT_SENDER', 'onboarding@resend.dev')
            # ...
            
            # Resend requires base64 for attachments
            attachment_b64 = base64.b64encode(csv_data.encode('utf-8')).decode('utf-8')
            
            resend.Emails.send({
                "from": f"FashionStore Admin <{sender}>",
                "to": recipient,
                "subject": subject,
                "text": body_content,
                "attachments": [
                    {
                        "filename": filename,
                        "content": attachment_b64,
                    }
                ]
            })
        else:
            # Fallback to Flask-Mail (SMTP)
            print(f"RESEND_API_KEY not found. Falling back to SMTP for {recipient}...")
            msg = Message(
                subject=subject,
                recipients=[recipient],
                body=body_content
            )
            msg.attach(filename, "text/csv", csv_data)
            
            original_timeout = socket.getdefaulttimeout()
            try:
                socket.setdefaulttimeout(15)
                current_app.mail.send(msg)
            finally:
                socket.setdefaulttimeout(original_timeout)
        
        return jsonify({'success': True, 'message': f'Đã gửi báo cáo đến {recipient} thành công!'})
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return jsonify({'success': False, 'message': f'Lỗi khi gửi email: {str(e)}'}), 500
    finally:
        if conn:
            conn.close()

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
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    
    if page < 1: page = 1
    if per_page not in [10, 15, 20, 50, 100]: per_page = 15

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Base query parts
    base_query = '''
        FROM ProductComments pc
        JOIN Customers c ON pc.CustomerID = c.CustomerID
        JOIN Products p ON pc.ProductID = p.ProductID
    '''
    where_clause = ""
    if filter_type == 'no_reply': where_clause = " WHERE pc.AdminReply IS NULL"
    elif filter_type == 'replied': where_clause = " WHERE pc.AdminReply IS NOT NULL"
    
    # Count total records
    cursor.execute(f"SELECT COUNT(*) {base_query} {where_clause}")
    total_records = cursor.fetchone()[0]
    
    total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
    
    # Boundary logic: cap page at total_pages
    if page > total_pages: page = total_pages
    
    offset = (page - 1) * per_page
    
    query = f'''
        SELECT pc.CommentID, pc.Content, pc.CommentDate, pc.AdminReply, pc.ReplyDate, pc.IsVisible,
               c.FullName AS CustomerName, p.ProductName, p.ProductID
        {base_query} {where_clause}
        ORDER BY pc.CommentDate DESC LIMIT %s OFFSET %s
    '''
    
    cursor.execute(query, (per_page, offset))
    comments = cursor.fetchall()
    conn.close()
    
    paging_data = {
        'total_records': total_records,
        'total_pages': total_pages,
        'current_page': page,
        'per_page': per_page,
        'start_index': offset + 1 if total_records > 0 else 0,
        'end_index': min(offset + per_page, total_records)
    }
    
    return render_template('admin/comments.html', comments=comments, filter=filter_type, paging=paging_data)

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
    
    # GET logic with pagination and sorting
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    sort_by = request.args.get('sort_by', 'newest')
    
    if page < 1: page = 1
    if per_page not in [10, 20, 50, 100]: per_page = 20
    
    # Sorting logic
    sort_query = "p.ProductID DESC"
    if sort_by == 'price_asc': sort_query = "p.Price ASC"
    elif sort_by == 'price_desc': sort_query = "p.Price DESC"
    elif sort_by == 'name_asc': sort_query = "p.ProductName ASC"
    
    # Count total records
    cursor.execute("SELECT COUNT(*) FROM Products")
    total_records = cursor.fetchone()[0]
    
    total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
    if page > total_pages: page = total_pages
    offset = (page - 1) * per_page
    
    cursor.execute(f'''
        SELECT p.*, c.CategoryName,
        (SELECT COUNT(*) FROM ProductVariants WHERE ProductID = p.ProductID) AS VariantCount,
        (SELECT SUM(Quantity) FROM ProductVariants WHERE ProductID = p.ProductID) AS TotalStock
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        ORDER BY {sort_query}
        LIMIT %s OFFSET %s
    ''', (per_page, offset))
    
    products = cursor.fetchall()
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    conn.close()
    
    paging_data = {
        'total_records': total_records,
        'total_pages': total_pages,
        'current_page': page,
        'per_page': per_page,
        'start_index': offset + 1 if total_records > 0 else 0,
        'end_index': min(offset + per_page, total_records)
    }
    
    return render_template('admin/manage_products.html', products=products, categories=categories, paging=paging_data, sort_by=sort_by)

@admin_bp.route('/admin/attributes')
def admin_attributes():
    if not is_admin(): return redirect(url_for('main.home'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM Colors ORDER BY ColorName')
    colors = cursor.fetchall()
    cursor.execute('SELECT * FROM Sizes ORDER BY SizeName')
    sizes = cursor.fetchall()
    conn.close()
    return render_template('admin/attributes.html', colors=colors, sizes=sizes)

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

@admin_bp.route('/admin/variants/delete/<int:variant_id>', methods=['POST'])
def admin_delete_variant(variant_id):
    if not is_admin(): return redirect(url_for('main.home'))
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM ProductVariants WHERE VariantID = %s', (variant_id,))
        conn.commit()
        flash('Đã xóa biến thể thành công', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Lỗi: {str(e)}', 'error')
    finally: conn.close()
    return redirect(request.referrer)

@admin_bp.route('/admin/colors/delete/<int:color_id>', methods=['POST'])
def admin_delete_color(color_id):
    if not is_admin(): return redirect(url_for('main.home'))
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM Colors WHERE ColorID = %s', (color_id,))
        conn.commit()
        flash('Đã xóa màu thành công', 'success')
    except psycopg2.IntegrityError:
        conn.rollback()
        flash('Không thể xóa màu này vì đang được sử dụng trong sản phẩm.', 'error')
    except Exception as e:
        conn.rollback()
        flash(f'Lỗi: {str(e)}', 'error')
    finally: conn.close()
    return redirect(request.referrer)

@admin_bp.route('/admin/sizes/delete/<int:size_id>', methods=['POST'])
def admin_delete_size(size_id):
    if not is_admin(): return redirect(url_for('main.home'))
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM Sizes WHERE SizeID = %s', (size_id,))
        conn.commit()
        flash('Đã xóa kích thước thành công', 'success')
    except psycopg2.IntegrityError:
        conn.rollback()
        flash('Không thể xóa kích thước này vì đang được sử dụng trong sản phẩm.', 'error')
    except Exception as e:
        conn.rollback()
        flash(f'Lỗi: {str(e)}', 'error')
    finally: conn.close()
    return redirect(request.referrer)
