from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.order_service import OrderService
from app.services.product_service import ProductService
from app.services.auth_service import AuthService
from app.decorators import login_required, handle_db_errors
from app.utils import send_email

cart_bp = Blueprint('cart', __name__)

@cart_bp.route('/add_to_cart', methods=['POST'])
@handle_db_errors
def add_to_cart():
    vid, qty = request.form.get('variant_id', type=int), request.form.get('quantity', type=int, default=1)
    if not vid:
        flash('Vui lòng chọn màu sắc và kích thước', 'error')
        return redirect(request.referrer)
    
    variant = ProductService.get_variant_detail(vid)
    if not variant:
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(request.referrer)
    
    if variant.Quantity < qty:
        flash(f'Chỉ còn {variant.Quantity} sản phẩm trong kho', 'error')
        return redirect(request.referrer)
    
    cart = session.get('cart', [])
    found = False
    for item in cart:
        if item['variant_id'] == vid:
            item['quantity'] += qty
            found = True
            break
    
    if not found:
        cart.append({
            'variant_id': vid, 'product_id': variant.ProductID, 'product_name': variant.ProductName,
            'price': float(variant.Price), 'color': variant.ColorName, 'size': variant.SizeName,
            'quantity': qty, 'image_url': variant.ImageURL
        })
    
    session['cart'] = cart
    flash('Đã thêm sản phẩm vào giỏ hàng', 'success')
    return redirect(request.referrer)

@cart_bp.route('/cart')
def view_cart():
    cart = session.get('cart', [])
    return render_template('cart.html', cart=cart, total=sum(item['price'] * item['quantity'] for item in cart))

@cart_bp.route('/buy_now', methods=['POST'])
@handle_db_errors
def buy_now():
    vid, qty = request.form.get('variant_id', type=int), request.form.get('quantity', type=int, default=1)
    if not vid:
        flash('Vui lòng chọn màu sắc và kích thước', 'error')
        return redirect(request.referrer)
    
    variant = ProductService.get_variant_detail(vid)
    if not variant:
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(request.referrer)
    
    if variant.Quantity < qty:
        flash(f'Chỉ còn {variant.Quantity} sản phẩm trong kho', 'error')
        return redirect(request.referrer)
    
    session['temp_cart'] = [{
        'variant_id': vid, 'product_id': variant.ProductID, 'product_name': variant.ProductName,
        'price': float(variant.Price), 'color': variant.ColorName, 'size': variant.SizeName,
        'quantity': qty, 'image_url': variant.ImageURL
    }]
    return redirect(url_for('cart.checkout', buy_now=1))

@cart_bp.route('/update_cart', methods=['POST'])
@handle_db_errors
def update_cart():
    vid, qty = request.form.get('variant_id', type=int), request.form.get('quantity', type=int)
    if not vid or qty < 1: return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    avail = ProductService.get_variant_quantity(vid)
    if avail < qty: return jsonify({'success': False, 'message': f'Chỉ còn {avail} sản phẩm'})
    
    cart = session.get('cart', [])
    for item in cart:
        if item['variant_id'] == vid:
            item['quantity'] = qty
            break
    session['cart'] = cart
    return jsonify({'success': True, 'total': sum(item['price'] * item['quantity'] for item in cart)})

@cart_bp.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    vid = request.form.get('variant_id', type=int)
    cart = [i for i in session.get('cart', []) if i['variant_id'] != vid]
    session['cart'] = cart
    return jsonify({'success': True, 'total': sum(item['price'] * item['quantity'] for item in cart)})

@cart_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
@handle_db_errors
def checkout():
    is_buy_now = request.args.get('buy_now', type=int, default=0)
    cart = session.get('temp_cart', []) if is_buy_now else session.get('cart', [])
    if not cart:
        flash('Giỏ hàng trống', 'error')
        return redirect(url_for('cart.view_cart'))
    
    uid = session['user_id']
    if request.method == 'GET':
        addr = ''
        cust = AuthService.get_customer_profile(uid)
        if cust: addr = cust.Address
        return render_template('checkout.html', cart=cart, total=sum(item['price'] * item['quantity'] for item in cart), address=addr)

    addr, pm = request.form.get('shipping_address'), request.form.get('payment_method')
    if not addr or not pm:
        flash('Thiếu thông tin giao hàng', 'error')
        return redirect(url_for('cart.checkout'))
    
    res = OrderService.create_order(uid, pm, addr, cart)
    if not res['success']:
        flash(res['message'], 'error')
        return redirect(url_for('cart.checkout'))

    session.pop('temp_cart' if is_buy_now else 'cart', None)
    flash('Đặt hàng thành công!', 'success')
    return redirect(url_for('cart.order_confirmation', order_id=res['order_id']))

@cart_bp.route('/order_confirmation/<int:order_id>')
@login_required
@handle_db_errors
def order_confirmation(order_id):
    data = OrderService.get_user_order_detail(order_id, session['user_id'])
    if not data:
        flash('Đơn hàng không tồn tại', 'error')
        return redirect(url_for('main.home'))
    return render_template('order_confirmation.html', order=data['order'], order_details=data['items'])

@cart_bp.route('/order/<int:order_id>')
@login_required
@handle_db_errors
def order_detail(order_id):
    data = OrderService.get_user_order_detail(order_id, session['user_id'])
    if not data:
        flash('Đơn hàng không tồn tại', 'error')
        return redirect(url_for('auth.my_account'))
    return render_template('order_detail.html', order=data['order'], order_details=data['items'])

@cart_bp.route('/cancel_order/<int:order_id>', methods=['POST'])
@login_required
@handle_db_errors
def cancel_order(order_id):
    res = OrderService.cancel_order(order_id, session['user_id'])
    if not res['success']: return jsonify(res)
        
    cust = AuthService.get_customer_profile(session['user_id'])
    if cust:
        send_email(cust.Email, 'Hủy đơn hàng', f'<p>Chào {cust.FullName}, đơn hàng #{order_id} đã được hủy.</p>')
    
    return jsonify({'success': True, 'message': 'Đã hủy đơn hàng'})
