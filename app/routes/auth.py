from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from app.services.auth_service import AuthService
from app.services.order_service import OrderService
from app.decorators import login_required, handle_db_errors
from app import limiter
from app.utils import send_email
from werkzeug.utils import secure_filename
import re
import os
import uuid

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
@handle_db_errors
def login():
    if request.method == 'GET': return render_template('login.html')

    email, pwd = request.form.get('email'), request.form.get('password')
    if not email or not pwd:
        flash('Vui lòng nhập email và mật khẩu', 'error')
        return redirect(url_for('auth.login'))
    
    user = AuthService.login_user(email, pwd)
    if not user:
        flash('Email hoặc mật khẩu không đúng', 'error')
        return redirect(url_for('auth.login'))
    
    session.update({
        'user_id': user.CustomerID, 'user_name': user.FullName,
        'is_admin': user.IsAdmin, 'role': user.Role, 'dark_mode': user.DarkModeEnabled
    })
    
    next_page = request.args.get('next')
    if next_page: return redirect(next_page)
    if user.Role == 'admin': return redirect(url_for('admin.admin_dashboard'))

    flash('Đăng nhập thành công!', 'success')
    return redirect(url_for('main.home'))

@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
@handle_db_errors
def register():
    if request.method == 'GET': return render_template('register.html')

    name, email, pwd = request.form.get('full_name'), request.form.get('email'), request.form.get('password')
    phone, addr = request.form.get('phone'), request.form.get('address')
    
    if not all([name, email, pwd]):
        flash('Vui lòng điền đầy đủ thông tin bắt buộc', 'error')
        return redirect(url_for('auth.register'))
    
    res = AuthService.register_user(name, email, pwd, phone, addr)
    if not res['success']:
        flash(res['message'], 'error')
        return redirect(url_for('auth.register'))

    session.update({'user_id': res['customer_id'], 'user_name': res['full_name'], 'role': 'customer', 'dark_mode': False})
    
    flash('Đăng ký thành công!', 'success')
    return redirect(url_for('main.home'))

@auth_bp.route('/logout')
def logout():
    for key in ['user_id', 'user_name', 'dark_mode', 'is_admin', 'role']: session.pop(key, None)
    flash('Đã đăng xuất thành công', 'success')
    return redirect(url_for('main.home'))

@auth_bp.route('/my_account')
@login_required
@handle_db_errors
def my_account():
    uid = session['user_id']
    cust = AuthService.get_customer_profile(uid)
    orders = OrderService.get_customer_orders(uid)
    return render_template('my_account.html', customer=cust, orders=orders)

@auth_bp.route('/api/profile/avatar', methods=['POST'])
@login_required
@handle_db_errors
def upload_avatar():
    if 'avatar' not in request.files: return jsonify({'success': False, 'message': 'Không có file'}), 400
    
    file = request.files['avatar']
    if file.filename == '': return jsonify({'success': False, 'message': 'Chưa chọn file'}), 400
    
    allowed = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if ext not in allowed: return jsonify({'success': False, 'message': 'Định dạng không hợp lệ'}), 400
    
    safe_name = secure_filename(f"avatar_{session['user_id']}_{uuid.uuid4().hex[:8]}.{ext}")
    path = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars')
    os.makedirs(path, exist_ok=True)
    
    file.save(os.path.join(path, safe_name))
    url = f"/static/uploads/avatars/{safe_name}"
    
    AuthService.update_avatar(session['user_id'], url)
    return jsonify({'success': True, 'avatar_url': url})

@auth_bp.route('/update_profile', methods=['POST'])
@login_required
@handle_db_errors
def update_profile():
    name = request.form.get('full_name')
    if not name:
        flash('Vui lòng nhập họ và tên', 'error')
        return redirect(url_for('auth.my_account'))
        
    res = AuthService.update_profile(session['user_id'], name, request.form.get('phone'), request.form.get('gender'), request.form.get('dob'))
    if not res['success']:
        flash(res['message'], 'error')
        return redirect(url_for('auth.my_account', _anchor='profile'))

    session['user_name'] = name
    flash('Cập nhật thông tin thành công!', 'success')
    return redirect(url_for('auth.my_account', _anchor='profile', profile_updated=True))

@auth_bp.route('/update_address', methods=['POST'])
@login_required
@handle_db_errors
def update_address():
    addr = request.form.get('address')
    if not addr:
        flash('Vui lòng nhập địa chỉ', 'error')
        return redirect(url_for('auth.my_account'))
    
    res = AuthService.update_address(session['user_id'], addr)
    if res['success']: flash('Cập nhật địa chỉ thành công!', 'success')
    else: flash(res['message'], 'error')
        
    return redirect(url_for('auth.my_account', _anchor='address', address_updated=True))

@auth_bp.route('/change_password', methods=['POST'])
@login_required
@handle_db_errors
def change_password():
    cur, new, conf = request.form.get('current_password'), request.form.get('new_password'), request.form.get('confirm_password')
    if not all([cur, new, conf]):
        flash('Vui lòng điền đầy đủ thông tin', 'error')
        return redirect(url_for('auth.my_account', _anchor='password'))
    
    if new != conf:
        flash('Mật khẩu xác nhận không khớp', 'error')
        return redirect(url_for('auth.my_account', _anchor='password'))
    
    if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$', new):
        flash('Mật khẩu yếu (cần 8 ký tự, 1 hoa, 1 thường, 1 số)', 'error')
        return redirect(url_for('auth.my_account', _anchor='password'))
    
    res = AuthService.change_password(session['user_id'], cur, new)
    if not res['success']: flash(res['message'], 'error')
    else: flash('Đổi mật khẩu thành công!', 'success')
        
    return redirect(url_for('auth.my_account', _anchor='password'))

@auth_bp.route('/toggle_dark_mode', methods=['POST'])
@login_required
@handle_db_errors
def toggle_dark_mode():
    enabled = request.form.get('dark_mode', type=int, default=0)
    AuthService.toggle_dark_mode(session['user_id'], enabled)
    session['dark_mode'] = bool(enabled)
    return jsonify({'success': True})

@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
@limiter.limit("3 per hour")
@handle_db_errors
def forgot_password():
    if request.method == 'GET': return render_template('forgot_password.html')
        
    email = request.form.get('email')
    if not email:
        flash('Vui lòng nhập email', 'error')
        return redirect(url_for('auth.forgot_password'))
    
    res = AuthService.create_password_reset_token(email)
    if res:
        link = url_for('auth.reset_password', token=res['token'], _external=True)
        send_email(email, 'Đặt lại mật khẩu', f'<p>Chào {res["full_name"]}, nhấn vào <a href="{link}">đây</a> để đặt lại mật khẩu.</p>')
    
    return render_template('forgot_password.html', email_sent=email)

@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
@handle_db_errors
def reset_password(token):
    if request.method == 'GET': return render_template('reset_password.html', token=token)
        
    pwd, conf = request.form.get('password'), request.form.get('confirm_password')
    if not pwd or pwd != conf:
        flash('Mật khẩu không khớp', 'error')
        return redirect(url_for('auth.reset_password', token=token))
        
    if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$', pwd):
        flash('Mật khẩu quá yếu', 'error')
        return redirect(url_for('auth.reset_password', token=token))
        
    res = AuthService.reset_password(token, pwd)
    if res['success']: return render_template('reset_password.html', reset_success=True)
    
    flash(res['message'], 'error')
    return redirect(url_for('auth.reset_password', token=token))
