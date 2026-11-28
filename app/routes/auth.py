from html import escape

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from app.decorators import handle_db_errors, login_required
from app.extensions import limiter
from app.services.auth_service import AuthService
from app.services.order_service import OrderService
from app.uploads import save_image, upload_root
from app.utils import send_email
from app.validation import ValidationError, email_address, local_redirect, password_value, required_text


auth_bp = Blueprint('auth', __name__)


def establish_session(user_id, name, role, auth_version=1, dark_mode=False):
    cart = session.get('cart', [])
    checkout_state = {}
    if session.get('user_id') in (None, user_id):
        checkout_state = {
            key: session[key] for key in ('cart_revision', 'checkout_owner', 'temp_cart') if key in session
        }
    session.clear()
    session.update(
        user_id=user_id,
        user_name=name,
        role=role,
        is_admin=role == 'admin',
        auth_version=auth_version,
        dark_mode=bool(dark_mode),
        cart=cart,
    )
    session.update(checkout_state)
    session.permanent = True


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
@handle_db_errors
def login():
    next_page = local_redirect(request.form.get('next') or request.args.get('next'))
    if request.method == 'GET':
        return render_template('login.html', next_page=next_page)
    try:
        email = email_address(request.form.get('email'))
        password = request.form.get('password')
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            raise ValidationError('Mật khẩu không hợp lệ')
        user = AuthService.login_user(email, password)
    except ValidationError:
        user = None
    if not user:
        flash('Email hoặc mật khẩu không đúng', 'error')
        return render_template('login.html', next_page=next_page), 400
    establish_session(user.CustomerID, user.FullName, user.Role, user.AuthVersion, user.DarkModeEnabled)
    if next_page:
        return redirect(next_page)
    flash('Đăng nhập thành công!', 'success')
    return redirect(url_for('admin.admin_dashboard' if user.Role == 'admin' else 'main.home'))


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('5 per hour')
@handle_db_errors
def register():
    next_page = local_redirect(request.form.get('next') or request.args.get('next'))
    if request.method == 'GET':
        return render_template('register.html', next_page=next_page)
    try:
        password = password_value(request.form.get('password'))
        if password != request.form.get('confirm_password'):
            raise ValidationError('Mật khẩu xác nhận không khớp')
        result = AuthService.register_user(
            request.form.get('full_name'),
            request.form.get('email'),
            password,
            request.form.get('phone'),
            request.form.get('address'),
        )
    except ValidationError as exc:
        flash(str(exc), 'error')
        return render_template('register.html', next_page=next_page), 400
    if not result['success']:
        flash(result['message'], 'error')
        return render_template('register.html', next_page=next_page), 400
    establish_session(result['customer_id'], result['full_name'], 'customer', result['auth_version'])
    flash('Đăng ký thành công!', 'success')
    return redirect(next_page or url_for('main.home'))


@auth_bp.route('/logout', methods=['POST'])
def logout():
    handlers = current_app.extensions.get('chat_socket_handlers')
    if handlers is not None and session.get('user_id'):
        handlers.revoke_user(session['user_id'])
    session.clear()
    flash('Đã đăng xuất thành công', 'success')
    return redirect(url_for('main.home'))


@auth_bp.route('/my_account')
@login_required
@handle_db_errors
def my_account():
    customer = AuthService.get_customer_profile(session['user_id'])
    if customer is None:
        session.clear()
        return redirect(url_for('auth.login'))
    return render_template(
        'my_account.html', customer=customer, orders=OrderService.get_customer_orders(session['user_id'])
    )


@auth_bp.route('/api/profile/avatar', methods=['POST'])
@login_required
@limiter.limit('5 per minute')
@handle_db_errors
def upload_avatar():
    try:
        path, image_url = save_image(request.files.get('avatar'))
    except ValidationError as exc:
        return jsonify(success=False, message=str(exc)), 400
    result = AuthService.update_avatar(session['user_id'], image_url)
    if not result['success']:
        path.unlink(missing_ok=True)
        return jsonify(result), 503
    return jsonify(success=True, avatar_url=image_url)


@auth_bp.route('/uploads/avatars/<filename>')
def avatar_file(filename):
    if not filename.endswith('.jpg') or len(filename) != 36:
        abort(404)
    return send_from_directory(upload_root() / 'avatars', filename, mimetype='image/jpeg')


@auth_bp.route('/update_profile', methods=['POST'])
@login_required
@handle_db_errors
def update_profile():
    try:
        name = required_text(request.form.get('full_name'), 'Họ tên', 255)
        result = AuthService.update_profile(
            session['user_id'], name, request.form.get('phone'), request.form.get('gender'), request.form.get('dob')
        )
    except ValidationError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('auth.my_account', _anchor='profile'))
    if result['success']:
        session['user_name'] = name
        flash('Cập nhật thông tin thành công!', 'success')
    else:
        flash(result['message'], 'error')
    return redirect(url_for('auth.my_account', _anchor='profile'))


@auth_bp.route('/update_address', methods=['POST'])
@login_required
@handle_db_errors
def update_address():
    try:
        result = AuthService.update_address(session['user_id'], request.form.get('address'))
    except ValidationError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('auth.my_account', _anchor='address'))
    flash(
        'Cập nhật địa chỉ thành công!' if result['success'] else result['message'],
        'success' if result['success'] else 'error',
    )
    return redirect(url_for('auth.my_account', _anchor='address'))


@auth_bp.route('/change_password', methods=['POST'])
@login_required
@limiter.limit('5 per hour')
@handle_db_errors
def change_password():
    try:
        password = password_value(request.form.get('new_password'))
        if password != request.form.get('confirm_password'):
            raise ValidationError('Mật khẩu xác nhận không khớp')
        current_password = request.form.get('current_password')
        if not isinstance(current_password, str) or not 1 <= len(current_password) <= 128:
            raise ValidationError('Mật khẩu hiện tại không hợp lệ')
        result = AuthService.change_password(session['user_id'], current_password, password)
    except ValidationError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('auth.my_account', _anchor='password'))
    if result['success']:
        session['auth_version'] = result['auth_version']
        flash('Đổi mật khẩu thành công!', 'success')
    else:
        flash(result['message'], 'error')
    return redirect(url_for('auth.my_account', _anchor='password'))


@auth_bp.route('/toggle_dark_mode', methods=['POST'])
@login_required
@handle_db_errors
def toggle_dark_mode():
    raw = request.form.get('dark_mode')
    if raw not in {'0', '1'}:
        return jsonify(success=False, message='Chế độ không hợp lệ'), 400
    enabled = raw == '1'
    result = AuthService.toggle_dark_mode(session['user_id'], enabled)
    if result['success']:
        session['dark_mode'] = enabled
    return jsonify(result), 200 if result['success'] else 503


@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
@limiter.limit('3 per hour')
@handle_db_errors
def forgot_password():
    if request.method == 'GET':
        return render_template('forgot_password.html')
    try:
        email = email_address(request.form.get('email'))
    except ValidationError as exc:
        flash(str(exc), 'error')
        return render_template('forgot_password.html'), 400
    result = AuthService.issue_account_recovery_token(email)
    if result:
        path = url_for('auth.reset_password', token=result['token'])
        base = current_app.config.get('PUBLIC_BASE_URL') or request.host_url.rstrip('/')
        link = f'{base.rstrip("/")}{path}'
        send_email(
            email,
            'Đặt lại mật khẩu',
            f'<p>Chào {escape(result["full_name"])}, nhấn vào <a href="{escape(link, quote=True)}">đây</a> để đặt lại mật khẩu.</p>',
        )
    return render_template('forgot_password.html', email_sent=email)


@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
@limiter.limit('5 per hour')
@handle_db_errors
def reset_password(token):
    if request.method == 'GET':
        return render_template('reset_password.html', token=token)
    try:
        password = password_value(request.form.get('password'))
        if password != request.form.get('confirm_password'):
            raise ValidationError('Mật khẩu xác nhận không khớp')
        result = AuthService.reset_password(token, password)
    except ValidationError as exc:
        flash(str(exc), 'error')
        return render_template('reset_password.html', token=token), 400
    if result['success']:
        session.clear()
        return render_template('reset_password.html', reset_success=True)
    flash(result['message'], 'error')
    return render_template('reset_password.html', token=token), 400
