from functools import wraps
from urllib.parse import urlsplit
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadData, URLSafeTimedSerializer
from markupsafe import escape

from app.decorators import api_request, handle_db_errors, login_required
from app.services.auth_service import AuthService
from app.services.cart_service import current_cart, previous_session_key, replace_cart
from app.services.order_service import OrderService
from app.services.product_service import ProductService
from app.utils import send_email
from app.validation import ValidationError, local_redirect, money, positive_int

cart_bp = Blueprint('cart', __name__)
CHECKOUT_REVIEW_SECONDS = 30 * 60
CART_CHANGED_MESSAGE = 'Giỏ hàng đã thay đổi. Vui lòng kiểm tra lại sản phẩm trước khi đặt hàng.'
ITEM_SELECTION_MESSAGE = 'Biến thể hoặc số lượng không hợp lệ. Vui lòng kiểm tra lại lựa chọn.'


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


class CartConflict(Exception):
    pass


def _store_cart(snapshot, cart):
    items = ProductService.normalize_cart_items(cart)
    if items != snapshot.items and not replace_cart(snapshot, items):
        raise CartConflict


def _retry_cart_change(func):
    @wraps(func)
    def wrapped():
        for _ in range(5):
            try:
                return func()
            except CartConflict:
                continue
        return _cart_error(CART_CHANGED_MESSAGE, 409)

    return wrapped


def _checkout_serializer(purpose):
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=f'checkout:{purpose}:v1')


def _read_checkout_token(purpose, token):
    try:
        if isinstance(token, str) and token:
            return _checkout_serializer(purpose).loads(token, max_age=CHECKOUT_REVIEW_SECONDS)
    except BadData:
        pass
    return None


def _buy_now_url(items, checkout_key=None):
    owner = session.get('checkout_owner')
    if not owner:
        owner = previous_session_key('checkout-owner') if session else uuid4().hex
        session['checkout_owner'] = owner
    draft = _checkout_serializer('buy-now').dumps(
        {
            'key': checkout_key or uuid4().hex,
            'owner': owner,
            'items': items,
        }
    )
    return url_for('cart.checkout', buy_now=1, draft=draft)


def _review_items(cart):
    return [[item['variant_id'], item['quantity'], item['price']] for item in cart]


def _checkout_preview(cart, checkout_key, user_id, buy_now):
    return {
        'cart': _display_cart(cart),
        'total': ProductService.cart_total(cart),
        'checkout_review': _checkout_serializer('review').dumps(
            {'key': checkout_key, 'user_id': user_id, 'buy_now': buy_now, 'items': _review_items(cart)}
        ),
    }


def _complete_checkout(order_id, buy_now, checkout_key):
    if not buy_now:
        snapshot = current_cart()
        if checkout_key == snapshot.revision:
            replace_cart(snapshot, [])
    confirmation_url = url_for('cart.order_confirmation', order_id=order_id)
    if api_request():
        return jsonify(success=True, order_id=order_id, confirmation_url=confirmation_url)
    flash('Đặt hàng thành công!', 'success')
    return redirect(confirmation_url)


def _restart_checkout(message, checkout_url):
    if api_request():
        return jsonify(success=False, message=message), 409
    flash(message, 'error')
    return redirect(checkout_url, code=303)


@cart_bp.route('/add_to_cart', methods=['POST'])
@handle_db_errors
@_retry_cart_change
def add_to_cart():
    try:
        data = _payload()
        vid = positive_int(data.get('variant_id'), 'Biến thể', ProductService.MAX_INTEGER)
        qty = positive_int(data.get('quantity', '1'), 'Số lượng', ProductService.MAX_INTEGER)
        variant = ProductService.get_variant_detail(vid)
        if not variant:
            return _cart_error('Sản phẩm không tồn tại', 404)
        snapshot = current_cart()
        cart = ProductService.refresh_cart_items(snapshot.items, drop_missing=True)
        existing = next((item for item in cart if item['variant_id'] == vid), None)
        accumulated = positive_int(
            qty + (existing['quantity'] if existing else 0), 'Số lượng', ProductService.MAX_INTEGER
        )
        if accumulated > variant.Quantity:
            return _cart_error(f'Chỉ còn {variant.Quantity} sản phẩm trong kho', 409, variant.ProductID)
        item = ProductService.cart_item(vid, accumulated, variant)
        cart = [row for row in cart if row['variant_id'] != vid] + [item]
        _store_cart(snapshot, cart)
    except ValidationError:
        return _cart_error(ITEM_SELECTION_MESSAGE)
    if api_request():
        return jsonify(success=True, message='Đã thêm sản phẩm vào giỏ hàng', **_summary(cart))
    flash('Đã thêm sản phẩm vào giỏ hàng', 'success')
    return redirect(_return_url(variant.ProductID))


@cart_bp.route('/cart')
@handle_db_errors
@_retry_cart_change
def view_cart():
    snapshot = current_cart()
    cart = ProductService.refresh_cart_items(snapshot.items, drop_missing=True)
    _store_cart(snapshot, cart)
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
        checkout_url = _buy_now_url([{'variant_id': vid, 'quantity': qty}])
    except ValidationError:
        return _cart_error(ITEM_SELECTION_MESSAGE)
    if api_request():
        return jsonify(success=True, checkout_url=checkout_url)
    return redirect(checkout_url)


@cart_bp.route('/update_cart', methods=['POST'])
@handle_db_errors
@_retry_cart_change
def update_cart():
    data = _payload()
    vid = positive_int(data.get('variant_id'), 'Biến thể', ProductService.MAX_INTEGER)
    qty = positive_int(data.get('quantity'), 'Số lượng', ProductService.MAX_INTEGER)
    snapshot = current_cart()
    items = snapshot.items
    if not any(item['variant_id'] == vid for item in items):
        return jsonify(success=False, message='Sản phẩm không có trong giỏ hàng'), 404
    cart = ProductService.refresh_cart_items(items)
    item = next(row for row in cart if row['variant_id'] == vid)
    if qty > item['stock']:
        return jsonify(success=False, message=f'Chỉ còn {item["stock"]} sản phẩm trong kho'), 409
    item['quantity'] = qty
    _store_cart(snapshot, cart)
    return jsonify(
        success=True,
        quantity=qty,
        price=item['price'],
        subtotal=str(money(item['price'], 'Giá sản phẩm') * qty),
        **_summary(cart),
    )


@cart_bp.route('/remove_from_cart', methods=['POST'])
@handle_db_errors
@_retry_cart_change
def remove_from_cart():
    vid = positive_int(_payload().get('variant_id'), 'Biến thể', ProductService.MAX_INTEGER)
    snapshot = current_cart()
    items = snapshot.items
    if not any(item['variant_id'] == vid for item in items):
        return jsonify(success=False, message='Sản phẩm không có trong giỏ hàng'), 404
    cart = ProductService.refresh_cart_items([item for item in items if item['variant_id'] != vid], drop_missing=True)
    _store_cart(snapshot, cart)
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
    user_id = session['user_id']
    checkout_url = url_for('cart.checkout')
    if is_buy_now:
        token = request.args.get('draft')
        draft = _read_checkout_token('buy-now', token)
        if draft is None or draft['owner'] != session.get('checkout_owner'):
            if request.method == 'GET' and token is None:
                legacy = ProductService.normalize_cart_items(session.get('temp_cart', []))
                if len(legacy) == 1:
                    session.pop('temp_cart')
                    return redirect(_buy_now_url(legacy, previous_session_key('buy-now')))
            return _restart_checkout('Lượt mua ngay đã hết hạn. Vui lòng chọn lại sản phẩm.', url_for('cart.view_cart'))
        source = draft['items']
        checkout_key = draft['key']
        checkout_url = url_for('cart.checkout', buy_now=1, draft=token)
    else:
        snapshot = current_cart()
        source = snapshot.items
        checkout_key = snapshot.revision if source else None

    review = None
    if request.method == 'POST':
        review = _read_checkout_token('review', data.get('checkout_review'))
        if review is None or review['user_id'] != user_id or review['buy_now'] != is_buy_now:
            return _restart_checkout(
                'Phiên đặt hàng đã hết hạn. Vui lòng tải lại trang và kiểm tra đơn hàng.', checkout_url
            )
        if is_buy_now and review['key'] != checkout_key:
            return 'Lượt mua ngay không khớp với đơn đã xem', 409
        order_id = OrderService.get_checkout_order(user_id, review['key'])
        if order_id is not None:
            return _complete_checkout(order_id, is_buy_now, review['key'])

    try:
        cart = ProductService.refresh_cart_items(source)
    except ValidationError:
        return _restart_checkout(CART_CHANGED_MESSAGE, url_for('cart.view_cart'))
    if not cart:
        if api_request():
            return jsonify(success=False, message='Giỏ hàng trống'), 400
        flash('Giỏ hàng trống', 'error')
        return redirect(url_for('cart.view_cart'))
    context = {
        'is_buy_now': is_buy_now,
        'checkout_url': checkout_url,
        **_checkout_preview(cart, checkout_key, user_id, is_buy_now),
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
    status = 400
    if review is None or review['key'] != checkout_key or review['items'] != _review_items(cart):
        status = 409
        message = 'Giỏ hàng hoặc giá đã thay đổi. Vui lòng kiểm tra lại trước khi đặt hàng.'
    elif data.get('shipping_method', 'standard') != 'standard':
        message = 'Phương thức giao hàng chưa được hỗ trợ'
    elif data.get('discount_code'):
        message = 'Mã giảm giá chưa được hỗ trợ'
    else:
        result = OrderService.create_order(
            user_id,
            data.get('payment_method', ''),
            data.get('shipping_address', ''),
            cart,
            recipient_name=data.get('full_name', ''),
            recipient_phone=data.get('phone', ''),
            recipient_email=data.get('email', ''),
            notes=data.get('order_notes', ''),
            checkout_key=checkout_key,
            reviewed_prices={variant_id: price for variant_id, _, price in review['items']},
        )
        if result['success']:
            return _complete_checkout(result['order_id'], is_buy_now, checkout_key)
        message = result['message']
        context['error_field'] = result.get('field')
        status = result.get('status_code', 400)
        if status == 409 and not api_request():
            # Refresh the review after a transaction conflict, keeping the submitted delivery details.
            try:
                refreshed_cart = ProductService.refresh_cart_items(source)
            except ValidationError:
                return _restart_checkout(CART_CHANGED_MESSAGE, url_for('cart.view_cart'))
            context.update(_checkout_preview(refreshed_cart, checkout_key, user_id, is_buy_now))
    if api_request():
        return jsonify(success=False, message=message), status
    return render_template('checkout.html', checkout_error=message, **context), status


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
