from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from markupsafe import escape

from app.decorators import api_request, handle_db_errors, login_required
from app.services.auth_service import AuthService
from app.services.order_service import OrderService
from app.services.product_service import ProductService
from app.utils import send_email
from app.validation import ValidationError, local_redirect, money, positive_int

cart_bp = Blueprint('cart', __name__)


def _payload():
    if request.is_json:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError('Dữ liệu không hợp lệ')
        return data
    return request.form


def _return_url(product_id=None):
    referrer = request.referrer or ''
    parsed = urlsplit(referrer)
    if parsed.netloc == request.host and parsed.scheme in ('http', 'https'):
        referrer = parsed.path + (f'?{parsed.query}' if parsed.query else '')
    safe_referrer = local_redirect(referrer)
    if safe_referrer:
        return safe_referrer
    if product_id:
        return url_for('product.product_detail', product_id=product_id)
    return url_for('cart.view_cart')


def _cart_error(message, status=400, product_id=None):
    if api_request():
        return jsonify(success=False, message=message), status
    flash(message, 'error')
    return redirect(_return_url(product_id))


def _summary(cart):
    return {
        'total': str(ProductService.cart_total(cart)),
        'cart_count': sum(item['quantity'] for item in cart),
        'item_count': len(cart),
        'items': [
            {
                'variant_id': item['variant_id'],
                'quantity': item['quantity'],
                'price': item['price'],
                'subtotal': str(money(item['price'], 'Giá sản phẩm') * item['quantity']),
                'stock': item['stock'],
            }
            for item in cart
        ],
    }


def _display_cart(cart):
    return [{**item, 'price': money(item['price'], 'Giá sản phẩm')} for item in cart]


@cart_bp.route('/add_to_cart', methods=['POST'])
@handle_db_errors
def add_to_cart():
    try:
        data = _payload()
        vid = positive_int(data.get('variant_id'), 'Biến thể', ProductService.MAX_INTEGER)
        qty = positive_int(data.get('quantity', '1'), 'Số lượng', ProductService.MAX_INTEGER)
        variant = ProductService.get_variant_detail(vid)
        if not variant:
            return _cart_error('Sản phẩm không tồn tại', 404)
        cart = ProductService.refresh_cart_items(session.get('cart', []), drop_missing=True)
        existing = next((item for item in cart if item['variant_id'] == vid), None)
        accumulated = positive_int(
            qty + (existing['quantity'] if existing else 0), 'Số lượng', ProductService.MAX_INTEGER
        )
        if accumulated > variant.Quantity:
            return _cart_error(f'Chỉ còn {variant.Quantity} sản phẩm trong kho', 409, variant.ProductID)
        item = ProductService.cart_item(vid, accumulated, variant)
        cart = [row for row in cart if row['variant_id'] != vid] + [item]
        session['cart'] = cart
    except ValidationError as exc:
        return _cart_error(str(exc))
    if api_request():
        return jsonify(success=True, message='Đã thêm sản phẩm vào giỏ hàng', **_summary(cart))
    flash('Đã thêm sản phẩm vào giỏ hàng', 'success')
    return redirect(_return_url(variant.ProductID))


@cart_bp.route('/cart')
@handle_db_errors
def view_cart():
    cart = ProductService.refresh_cart_items(session.get('cart', []), drop_missing=True)
    session['cart'] = cart
    return render_template('cart.html', cart=_display_cart(cart), total=ProductService.cart_total(cart))


@cart_bp.route('/buy_now', methods=['POST'])
@handle_db_errors
def buy_now():
    try:
        data = _payload()
        vid = positive_int(data.get('variant_id'), 'Biến thể', ProductService.MAX_INTEGER)
        qty = positive_int(data.get('quantity', '1'), 'Số lượng', ProductService.MAX_INTEGER)
        variant = ProductService.get_variant_detail(vid)
        if not variant:
            return _cart_error('Sản phẩm không tồn tại', 404)
        if qty > variant.Quantity:
            return _cart_error(f'Chỉ còn {variant.Quantity} sản phẩm trong kho', 409, variant.ProductID)
        session['temp_cart'] = [ProductService.cart_item(vid, qty, variant)]
    except ValidationError as exc:
        return _cart_error(str(exc))
    checkout_url = url_for('cart.checkout', buy_now=1)
    if api_request():
        return jsonify(success=True, checkout_url=checkout_url)
    return redirect(checkout_url)


@cart_bp.route('/update_cart', methods=['POST'])
@handle_db_errors
def update_cart():
    data = _payload()
    vid = positive_int(data.get('variant_id'), 'Biến thể', ProductService.MAX_INTEGER)
    qty = positive_int(data.get('quantity'), 'Số lượng', ProductService.MAX_INTEGER)
    items = ProductService.normalize_cart_items(session.get('cart', []))
    if not any(item['variant_id'] == vid for item in items):
        return jsonify(success=False, message='Sản phẩm không có trong giỏ hàng'), 404
    cart = ProductService.refresh_cart_items(items)
    item = next(row for row in cart if row['variant_id'] == vid)
    if qty > item['stock']:
        return jsonify(success=False, message=f'Chỉ còn {item["stock"]} sản phẩm trong kho'), 409
    item['quantity'] = qty
    session['cart'] = cart
    return jsonify(
        success=True,
        quantity=qty,
        price=item['price'],
        subtotal=str(money(item['price'], 'Giá sản phẩm') * qty),
        **_summary(cart),
    )


@cart_bp.route('/remove_from_cart', methods=['POST'])
@handle_db_errors
def remove_from_cart():
    vid = positive_int(_payload().get('variant_id'), 'Biến thể', ProductService.MAX_INTEGER)
    items = ProductService.normalize_cart_items(session.get('cart', []))
    if not any(item['variant_id'] == vid for item in items):
        return jsonify(success=False, message='Sản phẩm không có trong giỏ hàng'), 404
    cart = ProductService.refresh_cart_items([item for item in items if item['variant_id'] != vid], drop_missing=True)
    session['cart'] = cart
    return jsonify(success=True, **_summary(cart))


@cart_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
@handle_db_errors
def checkout():
    data = _payload() if request.method == 'POST' else {}
    query_mode = request.args.get('buy_now')
    form_mode = data.get('buy_now')
    if query_mode not in (None, '0', '1') or form_mode not in (None, '0', '1'):
        return 'Chế độ thanh toán không hợp lệ', 400
    if query_mode is not None and form_mode is not None and query_mode != form_mode:
        return 'Chế độ thanh toán không hợp lệ', 400
    is_buy_now = (query_mode if query_mode is not None else form_mode) == '1'
    cart_key = 'temp_cart' if is_buy_now else 'cart'
    try:
        cart = ProductService.refresh_cart_items(session.get(cart_key, []))
    except ValidationError as exc:
        return _cart_error(str(exc), 409)
    if not cart:
        if api_request():
            return jsonify(success=False, message='Giỏ hàng trống'), 400
        flash('Giỏ hàng trống', 'error')
        return redirect(url_for('cart.view_cart'))
    session[cart_key] = cart
    context = {
        'cart': _display_cart(cart),
        'total': ProductService.cart_total(cart),
        'is_buy_now': is_buy_now,
    }
    if request.method == 'GET':
        profile = AuthService.get_customer_profile(session['user_id'])
        context.update(
            address=profile.Address or '' if profile else '',
            full_name=profile.FullName or '' if profile else '',
            phone=profile.PhoneNumber or '' if profile else '',
            email=profile.Email or '' if profile else '',
            order_notes='',
        )
        return render_template('checkout.html', **context)
    context.update(
        address=data.get('shipping_address', ''),
        full_name=data.get('full_name', ''),
        phone=data.get('phone', ''),
        email=data.get('email', ''),
        order_notes=data.get('order_notes', ''),
    )
    try:
        if data.get('shipping_method', 'standard') != 'standard':
            raise ValidationError('Phương thức giao hàng chưa được hỗ trợ')
        if data.get('discount_code'):
            raise ValidationError('Mã giảm giá chưa được hỗ trợ')
        if any(item['quantity'] > item['stock'] for item in cart):
            raise ValidationError('Sản phẩm không đủ tồn kho. Vui lòng kiểm tra lại số lượng.')
    except ValidationError as exc:
        result = {'success': False, 'message': str(exc), 'status_code': 400}
    else:
        result = OrderService.create_order(
            session['user_id'],
            data.get('payment_method', ''),
            data.get('shipping_address', ''),
            cart,
            recipient_name=data.get('full_name', ''),
            recipient_phone=data.get('phone', ''),
            recipient_email=data.get('email', ''),
            notes=data.get('order_notes', ''),
        )
    if not result['success']:
        status = result.get('status_code', 400)
        if api_request():
            return jsonify(success=False, message=result['message']), status
        flash(result['message'], 'error')
        return render_template('checkout.html', **context), status
    session.pop(cart_key, None)
    confirmation_url = url_for('cart.order_confirmation', order_id=result['order_id'])
    if api_request():
        return jsonify(success=True, order_id=result['order_id'], confirmation_url=confirmation_url)
    flash('Đặt hàng thành công!', 'success')
    return redirect(confirmation_url)


@cart_bp.route('/order_confirmation/<int:order_id>')
@login_required
@handle_db_errors
def order_confirmation(order_id):
    data = OrderService.get_user_order_detail(order_id, session['user_id'])
    if not data:
        abort(404)
    return render_template('order_confirmation.html', order=data['order'], order_details=data['items'])


@cart_bp.route('/order/<int:order_id>')
@login_required
@handle_db_errors
def order_detail(order_id):
    data = OrderService.get_user_order_detail(order_id, session['user_id'])
    if not data:
        abort(404)
    return render_template('order_detail.html', order=data['order'], order_details=data['items'])


@cart_bp.route('/cancel_order/<int:order_id>', methods=['POST'])
@login_required
@handle_db_errors
def cancel_order(order_id):
    result = OrderService.cancel_order(order_id, session['user_id'])
    if not result['success']:
        return jsonify(success=False, message=result['message']), result.get('status_code', 400)
    # An optional notification must not make a committed cancellation appear to have failed.
    try:
        profile = AuthService.get_customer_profile(session['user_id'])
        if profile:
            send_email(
                profile.Email,
                'Hủy đơn hàng',
                f'<p>Chào {escape(profile.FullName)}, đơn hàng #{order_id} đã được hủy.</p>',
            )
    except Exception:
        current_app.logger.warning('Cancellation notification unavailable')
    return jsonify(success=True, message='Đã hủy đơn hàng')
