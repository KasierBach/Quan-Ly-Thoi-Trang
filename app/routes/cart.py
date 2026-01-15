from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.database import get_db_connection
from app.utils import send_email
from datetime import datetime

cart_bp = Blueprint('cart', __name__)

@cart_bp.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    variant_id = request.form.get('variant_id', type=int)
    quantity = request.form.get('quantity', type=int, default=1)
    
    if not variant_id:
        flash('Vui lòng chọn màu sắc và kích thước', 'error')
        return redirect(request.referrer)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT pv.Quantity, p.ProductName, p.Price, c.ColorName, s.SizeName, p.ProductID, p.ImageURL
        FROM ProductVariants pv
        JOIN Products p ON pv.ProductID = p.ProductID
        JOIN Colors c ON pv.ColorID = c.ColorID
        JOIN Sizes s ON pv.SizeID = s.SizeID
        WHERE pv.VariantID = %s
    ''', (variant_id,))
    variant = cursor.fetchone()
    conn.close()
    
    if not variant:
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(request.referrer)
    
    if variant.Quantity < quantity:
        flash(f'Chỉ còn {variant.Quantity} sản phẩm trong kho', 'error')
        return redirect(request.referrer)
    
    if 'cart' not in session:
        session['cart'] = []
    
    cart = session['cart']
    found = False
    
    for item in cart:
        if item['variant_id'] == variant_id:
            item['quantity'] += quantity
            found = True
            break
    
    if not found:
        cart.append({
            'variant_id': variant_id,
            'product_id': variant.ProductID,
            'product_name': variant.ProductName,
            'price': float(variant.Price),
            'color': variant.ColorName,
            'size': variant.SizeName,
            'quantity': quantity,
            'image_url': variant.ImageURL
        })
    
    session['cart'] = cart
    flash('Đã thêm sản phẩm vào giỏ hàng', 'success')
    return redirect(request.referrer)

@cart_bp.route('/cart')
def view_cart():
    cart = session.get('cart', [])
    total = sum(item['price'] * item['quantity'] for item in cart)
    return render_template('cart.html', cart=cart, total=total)

@cart_bp.route('/buy_now', methods=['POST'])
def buy_now():
    variant_id = request.form.get('variant_id', type=int)
    quantity = request.form.get('quantity', type=int, default=1)
    
    if not variant_id:
        flash('Vui lòng chọn màu sắc và kích thước', 'error')
        return redirect(request.referrer)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT pv.Quantity, p.ProductName, p.Price, c.ColorName, s.SizeName, p.ProductID, p.ImageURL
        FROM ProductVariants pv
        JOIN Products p ON pv.ProductID = p.ProductID
        JOIN Colors c ON pv.ColorID = c.ColorID
        JOIN Sizes s ON pv.SizeID = s.SizeID
        WHERE pv.VariantID = %s
    ''', (variant_id,))
    variant = cursor.fetchone()
    conn.close()
    
    if not variant:
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(request.referrer)
    
    if variant.Quantity < quantity:
        flash(f'Chỉ còn {variant.Quantity} sản phẩm trong kho', 'error')
        return redirect(request.referrer)
    
    temp_cart = [{
        'variant_id': variant_id,
        'product_id': variant.ProductID,
        'product_name': variant.ProductName,
        'price': float(variant.Price),
        'color': variant.ColorName,
        'size': variant.SizeName,
        'quantity': quantity,
        'image_url': variant.ImageURL
    }]
    session['temp_cart'] = temp_cart
    return redirect(url_for('cart.checkout', buy_now=1))

@cart_bp.route('/update_cart', methods=['POST'])
def update_cart():
    variant_id = request.form.get('variant_id', type=int)
    quantity = request.form.get('quantity', type=int)
    
    if not variant_id or quantity < 1:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT Quantity FROM ProductVariants WHERE VariantID = %s', (variant_id,))
    available = cursor.fetchone()
    conn.close()
    
    if not available or available.Quantity < quantity:
        return jsonify({'success': False, 'message': f'Chỉ còn {available.Quantity} sản phẩm trong kho'})
    
    cart = session.get('cart', [])
    for item in cart:
        if item['variant_id'] == variant_id:
            item['quantity'] = quantity
            break
    session['cart'] = cart
    total = sum(item['price'] * item['quantity'] for item in cart)
    
    return jsonify({'success': True, 'message': 'Đã cập nhật giỏ hàng', 'total': total})

@cart_bp.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    variant_id = request.form.get('variant_id', type=int)
    if not variant_id: return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    cart = session.get('cart', [])
    cart = [item for item in cart if item['variant_id'] != variant_id]
    session['cart'] = cart
    total = sum(item['price'] * item['quantity'] for item in cart)
    return jsonify({'success': True, 'message': 'Đã xóa sản phẩm', 'total': total})

@cart_bp.route('/checkout', methods=['GET', 'POST'])
def checkout():
    buy_now = request.args.get('buy_now', type=int, default=0)
    cart = session.get('temp_cart', []) if (buy_now and 'temp_cart' in session) else session.get('cart', [])
    
    if not cart:
        flash('Giỏ hàng của bạn đang trống', 'error')
        return redirect(url_for('cart.view_cart'))
    
    if request.method == 'POST':
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập để tiếp tục thanh toán', 'error')
            return redirect(url_for('auth.login', next=url_for('cart.checkout')))
        
        shipping_address = request.form.get('shipping_address')
        payment_method = request.form.get('payment_method')
        
        if not shipping_address or not payment_method:
            flash('Vui lòng điền đầy đủ thông tin giao hàng', 'error')
            return redirect(url_for('cart.checkout'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT sp_CreateOrder(%s, %s, %s) AS OrderID', (session['user_id'], payment_method, shipping_address))
            result = cursor.fetchone()
            order_id = result.OrderID
            
            for item in cart:
                cursor.execute('SELECT sp_AddOrderDetail(%s, %s, %s)', (order_id, item['variant_id'], item['quantity']))
            
            conn.commit()
            
            if buy_now and 'temp_cart' in session:
                session.pop('temp_cart', None)
            else:
                session.pop('cart', None)
            
            flash('Đặt hàng thành công! Cảm ơn bạn đã mua sắm.', 'success')
            return redirect(url_for('cart.order_confirmation', order_id=order_id))
        except Exception as e:
            conn.rollback()
            flash(f'Lỗi khi tạo đơn hàng: {str(e)}', 'error')
            return redirect(url_for('cart.checkout'))
        finally:
            conn.close()
    
    total = sum(item['price'] * item['quantity'] for item in cart)
    address = ''
    if 'user_id' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT Address FROM Customers WHERE CustomerID = %s', (session['user_id'],))
        customer = cursor.fetchone()
        conn.close()
        if customer and customer.Address: address = customer.Address
    
    return render_template('checkout.html', cart=cart, total=total, address=address)

@cart_bp.route('/order_confirmation/<int:order_id>')
def order_confirmation(order_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM sp_GetOrderDetails_Main(%s)', (order_id,))
    order = cursor.fetchone()
    
    cursor.execute('SELECT * FROM sp_GetOrderDetails_Items(%s)', (order_id,))
    order_details = cursor.fetchall()
    conn.close()
    
    if not order or order.CustomerID != session['user_id']:
        flash('Đơn hàng không tồn tại hoặc không có quyền', 'error')
        return redirect(url_for('main.home'))
    
    return render_template('order_confirmation.html', order=order, order_details=order_details)

@cart_bp.route('/order/<int:order_id>')
def order_detail(order_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM sp_GetOrderDetails_Main(%s)', (order_id,))
    order = cursor.fetchone()
    
    # Use direct query instead of stored procedure to ensure correct price retrieval
    cursor.execute('''
        SELECT 
            od.Quantity, 
            od.Price as UnitPrice, 
            p.ProductName, 
            c.ColorName, 
            s.SizeName, 
            p.ImageURL 
        FROM OrderDetails od
        JOIN ProductVariants pv ON od.VariantID = pv.VariantID
        JOIN Products p ON pv.ProductID = p.ProductID
        JOIN Colors c ON pv.ColorID = c.ColorID
        JOIN Sizes s ON pv.SizeID = s.SizeID
        WHERE od.OrderID = %s
    ''', (order_id,))
    order_details = cursor.fetchall()
    conn.close()
    
    if not order or order.CustomerID != session['user_id']:
        flash('Đơn hàng không tồn tại hoặc không có quyền xem', 'error')
        return redirect(url_for('auth.my_account'))
    
    return render_template('order_detail.html', order=order, order_details=order_details)

@cart_bp.route('/cancel_order/<int:order_id>', methods=['POST'])
def cancel_order(order_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT Status, CustomerID FROM Orders WHERE OrderID = %s', (order_id,))
        order = cursor.fetchone()
        if not order: return jsonify({'success': False, 'message': 'Đơn hàng không tồn tại'})
        if order.CustomerID != session['user_id']: return jsonify({'success': False, 'message': 'Không có quyền'})
        if order.Status != 'Pending': return jsonify({'success': False, 'message': 'Chỉ hủy được đơn Pending'})
        
        cursor.execute('SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, 'Cancelled'))
        
        cursor.execute('SELECT Email, FullName FROM Customers WHERE CustomerID = %s', (session['user_id'],))
        customer = cursor.fetchone()
        if customer:
            html = f'<p>Chào {customer.FullName}, đơn hàng #{order_id} đã hủy.</p>'
            send_email(customer.Email, 'Hủy đơn hàng', html)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Đã hủy đơn hàng'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
    finally:
        conn.close()
