from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.auth_service import AuthService
from app.decorators import login_required

from app.database import get_db_connection
from app.utils import send_email
import re
import uuid
import datetime
from datetime import datetime, timedelta

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Vui lòng nhập email và mật khẩu', 'error')
            return redirect(url_for('auth.login'))
        
        user = AuthService.login_user(email, password)
        
        if not user:
            flash('Email hoặc mật khẩu không đúng', 'error')
            return redirect(url_for('auth.login'))
        
        # Lưu thông tin đăng nhập vào session
        session['user_id'] = user.CustomerID
        session['user_name'] = user.FullName
        session['is_admin'] = user.IsAdmin # Keep for backward compatibility
        session['role'] = user.Role
        session['dark_mode'] = user.DarkModeEnabled
        
        # Chuyển hướng đến trang tiếp theo (nếu có)
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        
        if user.Role == 'admin':
             return redirect(url_for('admin.admin_dashboard'))

        flash('Đăng nhập thành công!', 'success')
        return redirect(url_for('main.home'))
    
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')
        phone = request.form.get('phone')
        address = request.form.get('address')
        
        if not full_name or not email or not password:
            flash('Vui lòng điền đầy đủ thông tin bắt buộc', 'error')
            return redirect(url_for('auth.register'))
        
        result = AuthService.register_user(full_name, email, password, phone, address)
        
        if result['success']:
            # Đăng nhập tự động sau khi đăng ký
            session['user_id'] = result['customer_id']
            session['user_name'] = result['full_name']
            session['role'] = 'customer' # Default role
            session['dark_mode'] = False
            
            flash('Đăng ký thành công!', 'success')
            return redirect(url_for('main.home'))
        else:
            flash(result['message'], 'error')
            return redirect(url_for('auth.register'))
    
    return render_template('register.html')

@auth_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    session.pop('dark_mode', None)
    session.pop('is_admin', None)
    flash('Đã đăng xuất thành công', 'success')
    return redirect(url_for('main.home'))

@auth_bp.route('/my_account')
def my_account():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lấy thông tin khách hàng
    cursor.execute('SELECT * FROM Customers WHERE CustomerID = %s', (session['user_id'],))
    customer = cursor.fetchone()
    
    # Lấy danh sách đơn hàng
    cursor.execute('''
        SELECT * FROM sp_GetCustomerOrders(%s)
    ''', (session['user_id'],))
    
    orders = cursor.fetchall()
    
    conn.close()
    
    return render_template('my_account.html', customer=customer, orders=orders)

@auth_bp.route('/api/profile/avatar', methods=['POST'])
def upload_avatar():
    """Handle avatar upload."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Chưa đăng nhập'}), 401
    
    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'Không có file'}), 400
    
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Chưa chọn file'}), 400
    
    # Validate file type
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if ext not in allowed_extensions:
        return jsonify({'success': False, 'error': 'Định dạng file không hợp lệ'}), 400
    
    # Generate unique filename
    import os
    from flask import current_app
    filename = f"avatar_{session['user_id']}_{uuid.uuid4().hex[:8]}.{ext}"
    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars')
    os.makedirs(upload_folder, exist_ok=True)
    
    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)
    
    # Update database
    avatar_url = f"/static/uploads/avatars/{filename}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE Customers SET AvatarUrl = %s WHERE CustomerID = %s', 
                      (avatar_url, session['user_id']))
        conn.commit()
        return jsonify({'success': True, 'avatar_url': avatar_url})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@auth_bp.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    full_name = request.form.get('full_name')
    phone = request.form.get('phone')
    gender = request.form.get('gender')
    dob = request.form.get('dob')
    
    if not full_name:
        flash('Vui lòng nhập họ và tên', 'error')
        return redirect(url_for('auth.my_account'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check phone duplication if changed
        if phone:
            cursor.execute('SELECT CustomerID FROM Customers WHERE PhoneNumber = %s AND CustomerID != %s', (phone, session['user_id']))
            if cursor.fetchone():
                flash('Số điện thoại đã được sử dụng', 'error')
                conn.close()
                return redirect(url_for('auth.my_account', _anchor='profile'))

        # Check if dob is valid date or empty
        if not dob: dob = None

        cursor.execute('''
            UPDATE Customers
            SET FullName = %s, PhoneNumber = %s, Gender = %s, DateOfBirth = %s
            WHERE CustomerID = %s
        ''', (full_name, phone, gender, dob, session['user_id']))
        
        conn.commit()
        
        # Cập nhật tên hiển thị trong session
        session['user_name'] = full_name
        
        flash('Cập nhật thông tin thành công!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('auth.my_account', _anchor='profile', profile_updated=True))

@auth_bp.route('/update_address', methods=['POST'])
def update_address():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    address = request.form.get('address')
    
    if not address:
        flash('Vui lòng nhập địa chỉ', 'error')
        return redirect(url_for('auth.my_account'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE Customers
            SET Address = %s
            WHERE CustomerID = %s
        ''', (address, session['user_id']))
        
        conn.commit()
        flash('Cập nhật địa chỉ thành công!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('auth.my_account', _anchor='address', address_updated=True))

@auth_bp.route('/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if not current_password or not new_password or not confirm_password:
        flash('Vui lòng điền đầy đủ thông tin', 'error')
        return redirect(url_for('auth.my_account', _anchor='password'))
    
    if new_password != confirm_password:
        flash('Mật khẩu xác nhận không khớp với mật khẩu mới', 'error')
        return redirect(url_for('auth.my_account', _anchor='password', password_error='Mật khẩu xác nhận không khớp'))
    
    if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$', new_password):
        flash('Mật khẩu phải có ít nhất 8 ký tự, bao gồm chữ hoa, chữ thường và số', 'error')
        return redirect(url_for('auth.my_account', _anchor='password', password_error='Mật khẩu yếu'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT Password FROM Customers WHERE CustomerID = %s', (session['user_id'],))
    user = cursor.fetchone()
    
    if not check_password_hash(user.Password, current_password):
        conn.close()
        flash('Mật khẩu hiện tại không đúng', 'error')
        return redirect(url_for('auth.my_account', _anchor='password', password_error='Mật khẩu hiện tại sai'))
    
    try:
        hashed_password = generate_password_hash(new_password)
        cursor.execute('''
            UPDATE Customers
            SET Password = %s
            WHERE CustomerID = %s
        ''', (hashed_password, session['user_id']))
        
        conn.commit()
        flash('Đổi mật khẩu thành công!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('auth.my_account', _anchor='password', password_updated=True))

@auth_bp.route('/toggle_dark_mode', methods=['POST'])
def toggle_dark_mode():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Bạn cần đăng nhập để lưu tùy chọn'})
    
    dark_mode = request.form.get('dark_mode', type=int, default=0)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE Customers
            SET DarkModeEnabled = %s
            WHERE CustomerID = %s
        ''', (bool(dark_mode), session['user_id']))
        conn.commit()
        session['dark_mode'] = bool(dark_mode)
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        if not email:
            flash('Vui lòng nhập email', 'error')
            return redirect(url_for('auth.forgot_password'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT CustomerID, FullName FROM Customers WHERE Email = %s', (email,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return render_template('forgot_password.html', email_sent=email)
        
        token = str(uuid.uuid4())
        expiry_date = datetime.now() + timedelta(hours=24)
        
        try:
            cursor.execute('''
                INSERT INTO PasswordResetTokens (CustomerID, Token, ExpiryDate)
                VALUES (%s, %s, %s)
            ''', (user.CustomerID, token, expiry_date))
            conn.commit()
            
            reset_link = url_for('auth.reset_password', token=token, _external=True)
            html_content = f'''
                <html><body>
                    <p>Xin chào {user.FullName},</p>
                    <p><a href="{reset_link}">Đặt lại mật khẩu</a></p>
                </body></html>
            '''
            send_email(email, 'Đặt lại mật khẩu - Fashion Store', html_content)
        except Exception as e:
            conn.rollback()
            print(f"Error: {str(e)}")
        finally:
            conn.close()
        
        return render_template('forgot_password.html', email_sent=email)
    
    return render_template('forgot_password.html')

@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT t.*, c.Email 
        FROM PasswordResetTokens t
        JOIN Customers c ON t.CustomerID = c.CustomerID
        WHERE t.Token = %s AND t.ExpiryDate > CURRENT_TIMESTAMP AND t.IsUsed = FALSE
    ''', (token,))
    token_data = cursor.fetchone()
    
    if not token_data:
        conn.close()
        return render_template('reset_password.html', token_invalid=True)
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not password or not confirm_password:
            flash('Vui lòng điền đầy đủ thông tin', 'error')
            return redirect(url_for('auth.reset_password', token=token))
        
        if password != confirm_password:
            flash('Mật khẩu không khớp', 'error')
            return redirect(url_for('auth.reset_password', token=token))
            
        if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$', password):
            flash('Mật khẩu yếu', 'error')
            return redirect(url_for('auth.reset_password', token=token))
            
        try:
            hashed_password = generate_password_hash(password)
            cursor.execute('UPDATE Customers SET Password = %s WHERE CustomerID = %s', (hashed_password, token_data.CustomerID))
            cursor.execute('UPDATE PasswordResetTokens SET IsUsed = TRUE WHERE TokenID = %s', (token_data.TokenID,))
            conn.commit()
            return render_template('reset_password.html', reset_success=True)
        except Exception as e:
            conn.rollback()
            flash(f'Lỗi: {str(e)}', 'error')
            return redirect(url_for('auth.reset_password', token=token))
        finally:
            conn.close()
            
    conn.close()
    return render_template('reset_password.html', token=token)
