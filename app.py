from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import pyodbc
import os
from datetime import datetime
import decimal
import json
import re
from datetime import datetime, timedelta
import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = 'fashion_store_secret_key'

# Cấu hình kết nối SQL Server
server = r'DESKTOP-0NO7KHL\MSSQLSERVER69'
database = 'FashionStoreDB'
username = 'sa'  # Thay đổi theo cấu hình của bạn
password = 'lolnani2'  # Thay đổi theo cấu hình của bạn
driver = '{ODBC Driver 17 for SQL Server}'  # Thay đổi theo driver đã cài đặt

# Chuỗi kết nối cho SQLAlchemy
connection_string = f'mssql+pyodbc://{username}:{password}@{server}/{database}?driver={driver}'
app.config['SQLALCHEMY_DATABASE_URI'] = connection_string
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Cấu hình email (thay đổi theo thông tin của bạn)
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_HOST_USER = 'your_email@gmail.com'  # Thay đổi email của bạn
EMAIL_HOST_PASSWORD = 'your_app_password'  # Thay đổi mật khẩu ứng dụng của bạn
EMAIL_USE_TLS = True

db = SQLAlchemy(app)

# Hàm kết nối trực tiếp đến SQL Server (cho stored procedures)
def get_db_connection():
    conn = pyodbc.connect(f'DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}')
    return conn

# Hàm chuyển đổi decimal sang float cho JSON
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        return super(DecimalEncoder, self).default(o)

# Hàm gửi email
def send_email(to_email, subject, html_content):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_HOST_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(html_content, 'html'))
        
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return False

# Trang chủ
@app.route('/')
def home():
    # Lấy danh sách danh mục
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    
    # Lấy sản phẩm nổi bật (ví dụ: 8 sản phẩm mới nhất)
    cursor.execute('''
        SELECT TOP 8 p.ProductID, p.ProductName, p.Price, c.CategoryName,
        (SELECT TOP 1 ColorName FROM Colors cl JOIN ProductVariants pv ON cl.ColorID = pv.ColorID 
         WHERE pv.ProductID = p.ProductID) AS FirstColor
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        ORDER BY p.CreatedAt DESC
    ''')
    featured_products = cursor.fetchall()
    
    # Lấy sản phẩm bán chạy
    cursor.execute('SELECT TOP 4 * FROM vw_BestSellingProducts')
    best_selling = cursor.fetchall()
    
    conn.close()
    
    return render_template('index.html', 
                          categories=categories, 
                          featured_products=featured_products,
                          best_selling=best_selling)

# Trang danh sách sản phẩm
@app.route('/products')
def products():
    category_id = request.args.get('category', type=int)
    search_term = request.args.get('search', '')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    color_id = request.args.get('color', type=int)
    size_id = request.args.get('size', type=int)
    in_stock_only = request.args.get('in_stock', type=int, default=0)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lấy danh sách danh mục cho menu
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    
    # Lấy danh sách màu sắc cho bộ lọc
    cursor.execute('SELECT * FROM Colors')
    colors = cursor.fetchall()
    
    # Lấy danh sách kích thước cho bộ lọc
    cursor.execute('SELECT * FROM Sizes')
    sizes = cursor.fetchall()
    
    # Gọi stored procedure tìm kiếm sản phẩm
    cursor.execute('''
        EXEC sp_SearchProducts @SearchTerm=?, @CategoryID=?, @MinPrice=?, @MaxPrice=?, @ColorID=?, @SizeID=?, @InStockOnly=?
    ''', search_term, category_id, min_price, max_price, color_id, size_id, in_stock_only)
    
    products = cursor.fetchall()
    
    conn.close()
    
    return render_template('products.html', 
                          products=products, 
                          categories=categories,
                          colors=colors,
                          sizes=sizes,
                          current_category=category_id,
                          search_term=search_term)

# Trang chi tiết sản phẩm
@app.route('/product/<int:product_id>')
def product_detail(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lấy thông tin sản phẩm
    cursor.execute('''
        SELECT p.*, c.CategoryName 
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        WHERE p.ProductID = ?
    ''', product_id)
    product = cursor.fetchone()
    
    if not product:
        conn.close()
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(url_for('products'))
    
    # Lấy các biến thể của sản phẩm (màu sắc, kích thước, số lượng)
    cursor.execute('''
        SELECT pv.VariantID, c.ColorID, c.ColorName, s.SizeID, s.SizeName, pv.Quantity
        FROM ProductVariants pv
        JOIN Colors c ON pv.ColorID = c.ColorID
        JOIN Sizes s ON pv.SizeID = s.SizeID
        WHERE pv.ProductID = ?
    ''', product_id)
    variants = cursor.fetchall()
    
    # Tổ chức các biến thể theo màu sắc và kích thước
    colors = {}
    sizes = {}
    variants_map = {}
    
    for variant in variants:
        color_id = variant.ColorID
        size_id = variant.SizeID
        
        if color_id not in colors:
            colors[color_id] = {'id': color_id, 'name': variant.ColorName}
        
        if size_id not in sizes:
            sizes[size_id] = {'id': size_id, 'name': variant.SizeName}
        
        key = f"{color_id}_{size_id}"
        variants_map[key] = {
            'variant_id': variant.VariantID,
            'quantity': variant.Quantity
        }
    
    cursor.execute("""
    SELECT Rating, COUNT(*) as Count
    FROM Reviews
    WHERE ProductID = ?
    GROUP BY Rating
    """, (product_id,))
    raw_breakdown = cursor.fetchall()

    rating_breakdown = {i: 0 for i in range(1, 6)}
    for row in raw_breakdown:
        rating_breakdown[row[0]] = row[1]  # row[0] = Rating, row[1] = Count


    conn.close()

    return render_template('product_detail.html', 
                          product=product,
                          original_price=product.Price * decimal.Decimal('1.2'),
                          colors=list(colors.values()),
                          sizes=list(sizes.values()),
                          variants=variants_map,
                          rating_breakdown=rating_breakdown)

# Thêm vào giỏ hàng
@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    variant_id = request.form.get('variant_id', type=int)
    quantity = request.form.get('quantity', type=int, default=1)
    
    if not variant_id:
        flash('Vui lòng chọn màu sắc và kích thước', 'error')
        return redirect(request.referrer)
    
    # Kiểm tra số lượng tồn kho
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT pv.Quantity, p.ProductName, p.Price, c.ColorName, s.SizeName, p.ProductID
        FROM ProductVariants pv
        JOIN Products p ON pv.ProductID = p.ProductID
        JOIN Colors c ON pv.ColorID = c.ColorID
        JOIN Sizes s ON pv.SizeID = s.SizeID
        WHERE pv.VariantID = ?
    ''', variant_id)
    
    variant = cursor.fetchone()
    conn.close()
    
    if not variant:
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(request.referrer)
    
    if variant.Quantity < quantity:
        flash(f'Chỉ còn {variant.Quantity} sản phẩm trong kho', 'error')
        return redirect(request.referrer)
    
    # Khởi tạo giỏ hàng nếu chưa có
    if 'cart' not in session:
        session['cart'] = []
    
    # Kiểm tra xem sản phẩm đã có trong giỏ hàng chưa
    cart = session['cart']
    found = False
    
    for item in cart:
        if item['variant_id'] == variant_id:
            item['quantity'] += quantity
            found = True
            break
    
    # Nếu chưa có, thêm mới vào giỏ hàng
    if not found:
        cart.append({
            'variant_id': variant_id,
            'product_id': variant.ProductID,
            'product_name': variant.ProductName,
            'price': float(variant.Price),
            'color': variant.ColorName,
            'size': variant.SizeName,
            'quantity': quantity
        })
    
    session['cart'] = cart
    flash('Đã thêm sản phẩm vào giỏ hàng', 'success')
    return redirect(request.referrer)

# Trang giỏ hàng
@app.route('/cart')
def view_cart():
    cart = session.get('cart', [])
    total = sum(item['price'] * item['quantity'] for item in cart)
    
    return render_template('cart.html', cart=cart, total=total)

# Thêm route mới cho chức năng "Mua ngay" sau route view_cart
@app.route('/buy_now', methods=['POST'])
def buy_now():
    variant_id = request.form.get('variant_id', type=int)
    quantity = request.form.get('quantity', type=int, default=1)
    
    if not variant_id:
        flash('Vui lòng chọn màu sắc và kích thước', 'error')
        return redirect(request.referrer)
    
    # Kiểm tra số lượng tồn kho
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT pv.Quantity, p.ProductName, p.Price, c.ColorName, s.SizeName, p.ProductID
        FROM ProductVariants pv
        JOIN Products p ON pv.ProductID = p.ProductID
        JOIN Colors c ON pv.ColorID = c.ColorID
        JOIN Sizes s ON pv.SizeID = s.SizeID
        WHERE pv.VariantID = ?
    ''', variant_id)
    
    variant = cursor.fetchone()
    conn.close()
    
    if not variant:
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(request.referrer)
    
    if variant.Quantity < quantity:
        flash(f'Chỉ còn {variant.Quantity} sản phẩm trong kho', 'error')
        return redirect(request.referrer)
    
    # Tạo giỏ hàng tạm thời cho phiên mua ngay
    temp_cart = [{
        'variant_id': variant_id,
        'product_id': variant.ProductID,
        'product_name': variant.ProductName,
        'price': float(variant.Price),
        'color': variant.ColorName,
        'size': variant.SizeName,
        'quantity': quantity
    }]
    
    # Lưu giỏ hàng tạm thời vào session
    session['temp_cart'] = temp_cart
    
    # Chuyển hướng đến trang thanh toán
    return redirect(url_for('checkout', buy_now=1))

# Cập nhật giỏ hàng
@app.route('/update_cart', methods=['POST'])
def update_cart():
    variant_id = request.form.get('variant_id', type=int)
    quantity = request.form.get('quantity', type=int)
    
    if not variant_id or quantity < 1:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    # Kiểm tra số lượng tồn kho
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT Quantity FROM ProductVariants WHERE VariantID = ?', variant_id)
    available = cursor.fetchone()
    conn.close()
    
    if not available or available.Quantity < quantity:
        return jsonify({'success': False, 'message': f'Chỉ còn {available.Quantity} sản phẩm trong kho'})
    
    # Cập nhật giỏ hàng
    cart = session.get('cart', [])
    for item in cart:
        if item['variant_id'] == variant_id:
            item['quantity'] = quantity
            break
    
    session['cart'] = cart
    total = sum(item['price'] * item['quantity'] for item in cart)
    
    return jsonify({
        'success': True, 
        'message': 'Đã cập nhật giỏ hàng',
        'total': total
    })

# Xóa sản phẩm khỏi giỏ hàng
@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    variant_id = request.form.get('variant_id', type=int)
    
    if not variant_id:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    # Xóa sản phẩm khỏi giỏ hàng
    cart = session.get('cart', [])
    cart = [item for item in cart if item['variant_id'] != variant_id]
    session['cart'] = cart
    
    total = sum(item['price'] * item['quantity'] for item in cart)
    
    return jsonify({
        'success': True, 
        'message': 'Đã xóa sản phẩm khỏi giỏ hàng',
        'total': total
    })

# Trang thanh toán
@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    # Kiểm tra xem có phải là mua ngay không
    buy_now = request.args.get('buy_now', type=int, default=0)
    
    if buy_now and 'temp_cart' in session:
        cart = session.get('temp_cart', [])
    else:
        cart = session.get('cart', [])
    
    if not cart:
        flash('Giỏ hàng của bạn đang trống', 'error')
        return redirect(url_for('view_cart'))
    
    if request.method == 'POST':
        # Kiểm tra đăng nhập
        if 'user_id' not in session:
            # Nếu chưa đăng nhập, chuyển hướng đến trang đăng nhập
            flash('Vui lòng đăng nhập để tiếp tục thanh toán', 'error')
            return redirect(url_for('login', next=url_for('checkout')))
        
        # Lấy thông tin từ form
        shipping_address = request.form.get('shipping_address')
        payment_method = request.form.get('payment_method')
        
        if not shipping_address or not payment_method:
            flash('Vui lòng điền đầy đủ thông tin giao hàng', 'error')
            return redirect(url_for('checkout'))
        
        # Tạo đơn hàng mới
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Tính tổng tiền
        total_amount = sum(item['price'] * item['quantity'] for item in cart)
        
        # Gọi stored procedure tạo đơn hàng
        cursor.execute('''
            DECLARE @OrderID INT
            EXEC sp_CreateOrder @CustomerID=?, @PaymentMethod=?, @ShippingAddress=?, @OrderID=@OrderID OUTPUT
            SELECT @OrderID AS OrderID
        ''', session['user_id'], payment_method, shipping_address)
        
        result = cursor.fetchone()
        order_id = result.OrderID
        
        # Thêm chi tiết đơn hàng
        for item in cart:
            cursor.execute('''
                EXEC sp_AddOrderDetail @OrderID=?, @VariantID=?, @Quantity=?
            ''', order_id, item['variant_id'], item['quantity'])
        
        conn.commit()
        conn.close()
        
        # Xóa giỏ hàng sau khi đặt hàng thành công
        if buy_now and 'temp_cart' in session:
            session.pop('temp_cart', None)
        else:
            session.pop('cart', None)
        
        flash('Đặt hàng thành công! Cảm ơn bạn đã mua sắm.', 'success')
        return redirect(url_for('order_confirmation', order_id=order_id))
    
    # Tính tổng tiền
    total = sum(item['price'] * item['quantity'] for item in cart)
    
    # Nếu đã đăng nhập, lấy thông tin địa chỉ của khách hàng
    address = ''
    if 'user_id' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT Address FROM Customers WHERE CustomerID = ?', session['user_id'])
        customer = cursor.fetchone()
        conn.close()
        
        if customer and customer.Address:
            address = customer.Address
    
    return render_template('checkout.html', cart=cart, total=total, address=address)

# Trang xác nhận đơn hàng
@app.route('/order_confirmation/<int:order_id>')
def order_confirmation(order_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lấy thông tin đơn hàng
    cursor.execute('''
        EXEC sp_GetOrderDetails @OrderID=?
    ''', order_id)
    
    order = cursor.fetchone()
    
    # Lấy chi tiết đơn hàng
    order_details = []
    if cursor.nextset():
        order_details = cursor.fetchall()
    
    conn.close()
    
    if not order or order.CustomerID != session['user_id']:
        flash('Đơn hàng không tồn tại hoặc bạn không có quyền xem', 'error')
        return redirect(url_for('home'))
    
    return render_template('order_confirmation.html', order=order, order_details=order_details)

# Trang đăng nhập
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Vui lòng nhập email và mật khẩu', 'error')
            return redirect(url_for('login'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT CustomerID, FullName, Password, DarkModeEnabled FROM Customers WHERE Email = ?', email)
        user = cursor.fetchone()
        conn.close()
        
        if not user or not check_password_hash(user.Password, password):
            flash('Email hoặc mật khẩu không đúng', 'error')
            return redirect(url_for('login'))
        
        # Lưu thông tin đăng nhập vào session
        session['user_id'] = user.CustomerID
        session['user_name'] = user.FullName
        session['dark_mode'] = user.DarkModeEnabled
        
        # Chuyển hướng đến trang tiếp theo (nếu có)
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        
        flash('Đăng nhập thành công!', 'success')
        return redirect(url_for('home'))
    
    return render_template('login.html')

# Trang đăng ký
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')
        phone = request.form.get('phone')
        address = request.form.get('address')
        
        if not full_name or not email or not password:
            flash('Vui lòng điền đầy đủ thông tin bắt buộc', 'error')
            return redirect(url_for('register'))
        
        # Mã hóa mật khẩu
        hashed_password = generate_password_hash(password)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Gọi stored procedure thêm khách hàng mới
            cursor.execute('''
                DECLARE @CustomerID INT
                EXEC @CustomerID = sp_AddCustomer @FullName=?, @Email=?, @Password=?, @PhoneNumber=?, @Address=?
                SELECT @CustomerID AS CustomerID
            ''', full_name, email, hashed_password, phone, address)
            
            result = cursor.fetchone()
            customer_id = result.CustomerID
            
            conn.commit()
            
            # Đăng nhập tự động sau khi đăng ký
            session['user_id'] = customer_id
            session['user_name'] = full_name
            session['dark_mode'] = False
            
            flash('Đăng ký thành công!', 'success')
            return redirect(url_for('home'))
            
        except pyodbc.Error as e:
            conn.rollback()
            error_message = str(e)
            if 'Email đã tồn tại' in error_message:
                flash('Email đã được sử dụng, vui lòng chọn email khác', 'error')
            elif 'Số điện thoại đã tồn tại' in error_message:
                flash('Số điện thoại đã được sử dụng, vui lòng chọn số khác', 'error')
            else:
                flash('Đã xảy ra lỗi, vui lòng thử lại', 'error')
            
            return redirect(url_for('register'))
        finally:
            conn.close()
    
    return render_template('register.html')

# Đăng xuất
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    session.pop('dark_mode', None)
    session.pop('is_admin', None)
    flash('Đã đăng xuất thành công', 'success')
    return redirect(url_for('home'))

# Trang tài khoản của tôi
@app.route('/my_account')
def my_account():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lấy thông tin khách hàng
    cursor.execute('SELECT * FROM Customers WHERE CustomerID = ?', session['user_id'])
    customer = cursor.fetchone()
    
    # Lấy danh sách đơn hàng
    cursor.execute('''
        EXEC sp_GetCustomerOrders @CustomerID=?
    ''', session['user_id'])
    
    orders = cursor.fetchall()
    
    conn.close()
    
    return render_template('my_account.html', customer=customer, orders=orders)

# Cập nhật thông tin cá nhân
@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    full_name = request.form.get('full_name')
    phone = request.form.get('phone')
    
    if not full_name:
        flash('Vui lòng nhập họ và tên', 'error')
        return redirect(url_for('my_account'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE Customers
            SET FullName = ?, PhoneNumber = ?
            WHERE CustomerID = ?
        ''', full_name, phone, session['user_id'])
        
        conn.commit()
        
        # Cập nhật tên hiển thị trong session
        session['user_name'] = full_name
        
        flash('Cập nhật thông tin thành công!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('my_account', _anchor='profile', profile_updated=True))

# Cập nhật địa chỉ
@app.route('/update_address', methods=['POST'])
def update_address():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    address = request.form.get('address')
    
    if not address:
        flash('Vui lòng nhập địa chỉ', 'error')
        return redirect(url_for('my_account'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE Customers
            SET Address = ?
            WHERE CustomerID = ?
        ''', address, session['user_id'])
        
        conn.commit()
        flash('Cập nhật địa chỉ thành công!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('my_account', _anchor='address', address_updated=True))

# Đổi mật khẩu
@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if not current_password or not new_password or not confirm_password:
        flash('Vui lòng điền đầy đủ thông tin', 'error')
        return redirect(url_for('my_account', _anchor='password'))
    
    if new_password != confirm_password:
        flash('Mật khẩu xác nhận không khớp với mật khẩu mới', 'error')
        return redirect(url_for('my_account', _anchor='password', password_error='Mật khẩu xác nhận không khớp với mật khẩu mới'))
    
    # Kiểm tra độ mạnh mật khẩu
    if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$', new_password):
        flash('Mật khẩu phải có ít nhất 8 ký tự, bao gồm chữ hoa, chữ thường và số', 'error')
        return redirect(url_for('my_account', _anchor='password', password_error='Mật khẩu phải có ít nhất 8 ký tự, bao gồm chữ hoa, chữ thường và số'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Kiểm tra mật khẩu hiện tại
    cursor.execute('SELECT Password FROM Customers WHERE CustomerID = ?', session['user_id'])
    user = cursor.fetchone()
    
    if not check_password_hash(user.Password, current_password):
        conn.close()
        flash('Mật khẩu hiện tại không đúng', 'error')
        return redirect(url_for('my_account', _anchor='password', password_error='Mật khẩu hiện tại không đúng'))
    
    # Cập nhật mật khẩu mới
    try:
        hashed_password = generate_password_hash(new_password)
        cursor.execute('''
            UPDATE Customers
            SET Password = ?
            WHERE CustomerID = ?
        ''', hashed_password, session['user_id'])
        
        conn.commit()
        flash('Đổi mật khẩu thành công!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('my_account', _anchor='password', password_updated=True))

# Chuyển đổi chế độ tối
@app.route('/toggle_dark_mode', methods=['POST'])
def toggle_dark_mode():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Bạn cần đăng nhập để lưu tùy chọn'})
    
    dark_mode = request.form.get('dark_mode', type=int, default=0)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE Customers
            SET DarkModeEnabled = ?
            WHERE CustomerID = ?
        ''', dark_mode, session['user_id'])
        
        conn.commit()
        
        # Cập nhật session
        session['dark_mode'] = bool(dark_mode)
        
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

# Quên mật khẩu
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        
        if not email:
            flash('Vui lòng nhập email', 'error')
            return redirect(url_for('forgot_password'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Kiểm tra email có tồn tại không
        cursor.execute('SELECT CustomerID, FullName FROM Customers WHERE Email = ?', email)
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            # Không thông báo email không tồn tại để tránh lộ thông tin
            return render_template('forgot_password.html', email_sent=email)
        
        # Tạo token đặt lại mật khẩu
        token = str(uuid.uuid4())
        expiry_date = datetime.now() + timedelta(hours=24)  # Token hết hạn sau 24 giờ
        
        # Lưu token vào cơ sở dữ liệu
        try:
            cursor.execute('''
                INSERT INTO PasswordResetTokens (CustomerID, Token, ExpiryDate)
                VALUES (?, ?, ?)
            ''', user.CustomerID, token, expiry_date)
            
            conn.commit()
            
            # Gửi email đặt lại mật khẩu
            reset_link = url_for('reset_password', token=token, _external=True)
            html_content = f'''
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background-color: #ff6b6b; color: white; padding: 10px 20px; text-align: center; }}
                        .content {{ padding: 20px; border: 1px solid #ddd; }}
                        .button {{ display: inline-block; background-color: #ff6b6b; color: white; padding: 10px 20px; 
                                  text-decoration: none; border-radius: 4px; margin-top: 20px; }}
                        .footer {{ margin-top: 20px; font-size: 12px; color: #777; text-align: center; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>Đặt lại mật khẩu</h2>
                        </div>
                        <div class="content">
                            <p>Xin chào {user.FullName},</p>
                            <p>Chúng tôi nhận được yêu cầu đặt lại mật khẩu cho tài khoản của bạn tại Fashion Store.</p>
                            <p>Vui lòng nhấp vào liên kết dưới đây để đặt lại mật khẩu của bạn:</p>
                            <p><a href="{reset_link}" class="button">Đặt lại mật khẩu</a></p>
                            <p>Hoặc sao chép và dán liên kết này vào trình duyệt của bạn: {reset_link}</p>
                            <p>Liên kết này sẽ hết hạn sau 24 giờ.</p>
                            <p>Nếu bạn không yêu cầu đặt lại mật khẩu, vui lòng bỏ qua email này.</p>
                        </div>
                        <div class="footer">
                            <p>&copy; 2025 Fashion Store. All rights reserved.</p>
                        </div>
                    </div>
                </body>
                </html>
            '''
            
            # Gửi email
            send_email(email, 'Đặt lại mật khẩu - Fashion Store', html_content)
            
        except Exception as e:
            conn.rollback()
            print(f"Error: {str(e)}")
        finally:
            conn.close()
        
        # Hiển thị thông báo đã gửi email
        return render_template('forgot_password.html', email_sent=email)
    
    return render_template('forgot_password.html')

# Đặt lại mật khẩu
@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # Kiểm tra token có hợp lệ không
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT t.*, c.Email 
        FROM PasswordResetTokens t
        JOIN Customers c ON t.CustomerID = c.CustomerID
        WHERE t.Token = ? AND t.ExpiryDate > GETDATE() AND t.IsUsed = 0
    ''', token)
    
    token_data = cursor.fetchone()
    
    if not token_data:
        conn.close()
        return render_template('reset_password.html', token_invalid=True)
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not password or not confirm_password:
            flash('Vui lòng điền đầy đủ thông tin', 'error')
            return redirect(url_for('reset_password', token=token))
        
        if password != confirm_password:
            flash('Mật khẩu xác nhận không khớp với mật khẩu mới', 'error')
            return redirect(url_for('reset_password', token=token))
        
        # Kiểm tra độ mạnh mật khẩu
        if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$', password):
            flash('Mật khẩu phải có ít nhất 8 ký tự, bao gồm chữ hoa, chữ thường và số', 'error')
            return redirect(url_for('reset_password', token=token))
        
        try:
            # Cập nhật mật khẩu mới
            hashed_password = generate_password_hash(password)
            cursor.execute('''
                UPDATE Customers
                SET Password = ?
                WHERE CustomerID = ?
            ''', hashed_password, token_data.CustomerID)
            
            # Đánh dấu token đã sử dụng
            cursor.execute('''
                UPDATE PasswordResetTokens
                SET IsUsed = 1
                WHERE TokenID = ?
            ''', token_data.TokenID)
            
            conn.commit()
            
            return render_template('reset_password.html', reset_success=True)
            
        except Exception as e:
            conn.rollback()
            flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
            return redirect(url_for('reset_password', token=token))
        finally:
            conn.close()
    
    conn.close()
    return render_template('reset_password.html', token=token)

# Trang chi tiết đơn hàng
@app.route('/order/<int:order_id>')
def order_detail(order_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lấy thông tin đơn hàng
    cursor.execute('''
        EXEC sp_GetOrderDetails @OrderID=?
    ''', order_id)
    
    order = cursor.fetchone()
    
    # Lấy chi tiết đơn hàng
    order_details = []
    if cursor.nextset():
        order_details = cursor.fetchall()
    
    conn.close()
    
    if not order or order.CustomerID != session['user_id']:
        flash('Đơn hàng không tồn tại hoặc bạn không có quyền xem', 'error')
        return redirect(url_for('my_account'))
    
    return render_template('order_detail.html', order=order, order_details=order_details)

# API lấy biến thể sản phẩm
@app.route('/api/get_variant', methods=['POST'])
def get_variant():
    product_id = request.form.get('product_id', type=int)
    color_id = request.form.get('color_id', type=int)
    size_id = request.form.get('size_id', type=int)
    
    if not product_id or not color_id or not size_id:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT VariantID, Quantity 
        FROM ProductVariants 
        WHERE ProductID = ? AND ColorID = ? AND SizeID = ?
    ''', product_id, color_id, size_id)
    
    variant = cursor.fetchone()
    conn.close()
    
    if not variant:
        return jsonify({'success': False, 'message': 'Không tìm thấy biến thể sản phẩm'})
    
    return jsonify({
        'success': True,
        'variant_id': variant.VariantID,
        'quantity': variant.Quantity
    })

# Trang quản trị - Dashboard
@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session.get('is_admin') != True:
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lấy thống kê doanh thu theo tháng
    cursor.execute('SELECT * FROM vw_MonthlyRevenue ORDER BY Year DESC, Month DESC')
    monthly_revenue = cursor.fetchall()
    
    # Lấy thống kê doanh thu theo danh mục
    cursor.execute('SELECT * FROM vw_CategoryRevenue ORDER BY TotalRevenue DESC')
    category_revenue = cursor.fetchall()
    
    # Lấy sản phẩm bán chạy
    cursor.execute('SELECT * FROM vw_BestSellingProducts')
    best_selling = cursor.fetchall()
    
    conn.close()
    
    return render_template('admin/dashboard.html', 
                          monthly_revenue=monthly_revenue,
                          category_revenue=category_revenue,
                          best_selling=best_selling,
                          now=datetime.now())

# Trang quản lý sản phẩm
@app.route('/admin/products')
def admin_products():
    if 'user_id' not in session or session.get('is_admin') != True:
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lấy danh sách sản phẩm
    cursor.execute('''
        SELECT p.*, c.CategoryName,
        (SELECT COUNT(*) FROM ProductVariants WHERE ProductID = p.ProductID) AS VariantCount,
        (SELECT SUM(Quantity) FROM ProductVariants WHERE ProductID = p.ProductID) AS TotalStock
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        ORDER BY p.ProductID DESC
    ''')
    
    products = cursor.fetchall()
    
    # Lấy danh sách danh mục
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    
    conn.close()
    
    return render_template('products.html', products=products, categories=categories)

# Thêm sản phẩm mới
@app.route('/admin/products/add', methods=['GET', 'POST'])
def admin_add_product():
    if 'user_id' not in session or session.get('is_admin') != True:
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        product_name = request.form.get('product_name')
        description = request.form.get('description')
        price = request.form.get('price', type=float)
        category_id = request.form.get('category_id', type=int)
        
        if not product_name or not price or not category_id:
            flash('Vui lòng điền đầy đủ thông tin sản phẩm', 'error')
            return redirect(url_for('admin_add_product'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Gọi stored procedure thêm sản phẩm mới
            cursor.execute('''
                DECLARE @ProductID INT
                EXEC sp_AddProduct @ProductName=?, @Description=?, @Price=?, @CategoryID=?, @ProductID=@ProductID OUTPUT
                SELECT @ProductID AS ProductID
            ''', product_name, description, price, category_id)
            
            result = cursor.fetchone()
            product_id = result.ProductID
            
            conn.commit()
            
            flash('Thêm sản phẩm thành công!', 'success')
            return redirect(url_for('admin_edit_product', product_id=product_id))
            
        except pyodbc.Error as e:
            conn.rollback()
            flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
            return redirect(url_for('admin_add_product'))
        finally:
            conn.close()
    
    # Lấy danh sách danh mục
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    conn.close()
    
    return render_template('admin/add_product.html', categories=categories)

# Chỉnh sửa sản phẩm
@app.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
def admin_edit_product(product_id):
    if 'user_id' not in session or session.get('is_admin') != True:
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        product_name = request.form.get('product_name')
        description = request.form.get('description')
        price = request.form.get('price', type=float)
        category_id = request.form.get('category_id', type=int)
        
        if not product_name or not price or not category_id:
            flash('Vui lòng điền đầy đủ thông tin sản phẩm', 'error')
            return redirect(url_for('admin_edit_product', product_id=product_id))
        
        try:
            # Cập nhật thông tin sản phẩm
            cursor.execute('''
                UPDATE Products
                SET ProductName = ?, Description = ?, Price = ?, CategoryID = ?
                WHERE ProductID = ?
            ''', product_name, description, price, category_id, product_id)
            
            conn.commit()
            flash('Cập nhật sản phẩm thành công!', 'success')
            
        except pyodbc.Error as e:
            conn.rollback()
            flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
    
    # Lấy thông tin sản phẩm
    cursor.execute('''
        SELECT p.*, c.CategoryName
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        WHERE p.ProductID = ?
    ''', product_id)
    
    product = cursor.fetchone()
    
    if not product:
        conn.close()
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(url_for('admin_products'))
    
    # Lấy danh sách danh mục
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    
    # Lấy danh sách biến thể sản phẩm
    cursor.execute('''
        SELECT pv.*, c.ColorName, s.SizeName
        FROM ProductVariants pv
        JOIN Colors c ON pv.ColorID = c.ColorID
        JOIN Sizes s ON pv.SizeID = s.SizeID
        WHERE pv.ProductID = ?
    ''', product_id)
    
    variants = cursor.fetchall()
    
    # Lấy danh sách màu sắc và kích thước
    cursor.execute('SELECT * FROM Colors')
    colors = cursor.fetchall()
    
    cursor.execute('SELECT * FROM Sizes')
    sizes = cursor.fetchall()
    
    conn.close()
    
    return render_template('admin/edit_product.html', 
                          product=product,
                          categories=categories,
                          variants=variants,
                          colors=colors,
                          sizes=sizes)

# Thêm biến thể sản phẩm
@app.route('/admin/products/add_variant', methods=['POST'])
def admin_add_variant():
    if 'user_id' not in session or session.get('is_admin') != True:
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('home'))
    
    product_id = request.form.get('product_id', type=int)
    color_id = request.form.get('color_id', type=int)
    size_id = request.form.get('size_id', type=int)
    quantity = request.form.get('quantity', type=int)
    
    if not product_id or not color_id or not size_id or not quantity:
        flash('Vui lòng điền đầy đủ thông tin biến thể', 'error')
        return redirect(url_for('admin_edit_product', product_id=product_id))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Gọi stored procedure thêm biến thể sản phẩm
        cursor.execute('''
            DECLARE @VariantID INT
            EXEC sp_AddProductVariant @ProductID=?, @ColorID=?, @SizeID=?, @Quantity=?, @VariantID=@VariantID OUTPUT
            SELECT @VariantID AS VariantID
        ''', product_id, color_id, size_id, quantity)
        
        conn.commit()
        flash('Thêm biến thể sản phẩm thành công!', 'success')
        
    except pyodbc.Error as e:
        conn.rollback()
        flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('admin_edit_product', product_id=product_id))

# Trang quản lý đơn hàng
@app.route('/admin/orders')
def admin_orders():
    if 'user_id' not in session or session.get('is_admin') != True:
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('home'))
    
    status = request.args.get('status', '')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lấy danh sách đơn hàng
    query = '''
        SELECT o.*, c.FullName AS CustomerName, c.Email AS CustomerEmail
        FROM Orders o
        JOIN Customers c ON o.CustomerID = c.CustomerID
    '''
    
    if status:
        query += f" WHERE o.Status = '{status}'"
    
    query += " ORDER BY o.OrderDate DESC"
    
    cursor.execute(query)
    orders = cursor.fetchall()
    
    conn.close()
    
    return render_template('admin/orders.html', orders=orders, current_status=status)

# Chi tiết đơn hàng (Admin)
@app.route('/admin/orders/<int:order_id>')
def admin_order_detail(order_id):
    if 'user_id' not in session or session.get('is_admin') != True:
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lấy thông tin đơn hàng
    cursor.execute('''
        EXEC sp_GetOrderDetails @OrderID=?
    ''', order_id)
    
    order = cursor.fetchone()
    
    # Lấy chi tiết đơn hàng
    order_details = []
    if cursor.nextset():
        order_details = cursor.fetchall()
    
    conn.close()
    
    if not order:
        flash('Đơn hàng không tồn tại', 'error')
        return redirect(url_for('admin_orders'))
    
    return render_template('admin/order_detail.html', order=order, order_details=order_details)

# Cập nhật trạng thái đơn hàng
@app.route('/admin/orders/update_status', methods=['POST'])
def admin_update_order_status():
    if 'user_id' not in session or session.get('is_admin') != True:
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('home'))
    
    order_id = request.form.get('order_id', type=int)
    new_status = request.form.get('status')
    
    if not order_id or not new_status:
        flash('Dữ liệu không hợp lệ', 'error')
        return redirect(url_for('admin_orders'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Gọi stored procedure cập nhật trạng thái đơn hàng
        cursor.execute('''
            EXEC sp_UpdateOrderStatus @OrderID=?, @NewStatus=?
        ''', order_id, new_status)
        
        conn.commit()
        flash('Cập nhật trạng thái đơn hàng thành công!', 'success')
        
    except pyodbc.Error as e:
        conn.rollback()
        flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('admin_order_detail', order_id=order_id))

# Trang báo cáo thống kê
@app.route('/admin/reports')
def admin_reports():
    if 'user_id' not in session or session.get('is_admin') != True:
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('home'))
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    if not start_date:
        start_date = (datetime.now().replace(day=1)).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Gọi stored procedure thống kê doanh thu theo khoảng thời gian
    cursor.execute('''
        EXEC sp_GetRevenueByDateRange @StartDate=?, @EndDate=?
    ''', start_date, end_date)
    
    # Lấy doanh thu theo ngày
    daily_revenue = cursor.fetchall()
    
    # Lấy doanh thu theo danh mục
    category_revenue = []
    if cursor.nextset():
        category_revenue = cursor.fetchall()
    
    # Lấy sản phẩm bán chạy
    best_selling = []
    if cursor.nextset():
        best_selling = cursor.fetchall()
    
    conn.close()
    
    # Chuẩn bị dữ liệu cho biểu đồ
    dates = []
    revenues = []
    for row in daily_revenue:
        if hasattr(row, 'OrderDate') and row.OrderDate:
            dates.append(row.OrderDate.strftime('%d/%m/%Y'))
        else:
            dates.append('')
        if hasattr(row, 'DailyRevenue') and row.DailyRevenue is not None:
            revenues.append(float(row.DailyRevenue))
        else:
            revenues.append(0.0)

    category_names = []
    category_revenues = []
    for row in category_revenue:
        if hasattr(row, 'CategoryName') and row.CategoryName:
            category_names.append(row.CategoryName)
        else:
            category_names.append('')
        if hasattr(row, 'CategoryRevenue') and row.CategoryRevenue is not None:
            category_revenues.append(float(row.CategoryRevenue))
        else:
            category_revenues.append(0.0)
    
    return render_template('admin/reports.html', 
                          daily_revenue=daily_revenue,
                          category_revenue=category_revenue,
                          best_selling=best_selling,
                          start_date=start_date,
                          end_date=end_date,
                          dates=json.dumps(dates),
                          revenues=json.dumps(revenues),
                          category_names=json.dumps(category_names),
                          category_revenues=json.dumps(category_revenues))

# Kiểm tra quyền admin
@app.before_request
def check_admin():
    if 'user_id' in session and session.get('is_admin') is None:
        # Kiểm tra xem người dùng có phải là admin không
        # Ví dụ: admin có CustomerID = 19
        if session['user_id'] == 19:
            session['is_admin'] = True

# Wishlist functionality
@app.route('/add_to_wishlist', methods=['POST'])
def add_to_wishlist():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để sử dụng tính năng này'})
    
    # Support both JSON and form data
    if request.is_json:
        data = request.get_json()
        product_id = data.get('product_id', None)
    else:
        product_id = request.form.get('product_id', type=int)
    
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        product_id = None

    if not product_id:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if product exists in wishlist
        cursor.execute('''
            SELECT * FROM Wishlist 
            WHERE CustomerID = ? AND ProductID = ?
        ''', session['user_id'], product_id)
        
        existing = cursor.fetchone()
        
        if existing:
            return jsonify({'success': True, 'message': 'Sản phẩm đã có trong danh sách yêu thích'})
        
        # Add to wishlist
        cursor.execute('''
            INSERT INTO Wishlist (CustomerID, ProductID, AddedDate)
            VALUES (?, ?, GETDATE())
        ''', session['user_id'], product_id)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Đã thêm vào danh sách yêu thích'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Đã xảy ra lỗi: {str(e)}'})
    finally:
        conn.close()

@app.route('/wishlist')
def view_wishlist():
    if 'user_id' not in session:
        return redirect(url_for('login', next=url_for('view_wishlist')))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get wishlist items
    cursor.execute('''
        SELECT w.WishlistID, p.ProductID, p.ProductName, p.Price, c.CategoryName,
        (SELECT TOP 1 ColorName FROM Colors cl JOIN ProductVariants pv ON cl.ColorID = pv.ColorID 
         WHERE pv.ProductID = p.ProductID) AS FirstColor,
        w.AddedDate
        FROM Wishlist w
        JOIN Products p ON w.ProductID = p.ProductID
        JOIN Categories c ON p.CategoryID = c.CategoryID
        WHERE w.CustomerID = ?
        ORDER BY w.AddedDate DESC
    ''', session['user_id'])
    
    wishlist_items = cursor.fetchall()
    
    # Get categories for navbar
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    
    conn.close()
    
    return render_template('wishlist.html', wishlist_items=wishlist_items, categories=categories)

@app.route('/remove_from_wishlist', methods=['POST'])
def remove_from_wishlist():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để sử dụng tính năng này'})
    
    wishlist_id = request.form.get('wishlist_id', type=int)
    
    if not wishlist_id:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Verify ownership
        cursor.execute('''
            SELECT * FROM Wishlist 
            WHERE WishlistID = ? AND CustomerID = ?
        ''', (wishlist_id, session['user_id']))
        
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'Bạn không có quyền thực hiện thao tác này'})
        
        # Remove from wishlist
        cursor.execute('DELETE FROM Wishlist WHERE WishlistID = ?', (wishlist_id,))
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Đã xóa khỏi danh sách yêu thích'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Đã xảy ra lỗi: {str(e)}'})
    finally:
        conn.close()

# Product reviews
@app.route('/add_review', methods=['POST'])
def add_review():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để đánh giá sản phẩm'})
    
    product_id = request.form.get('product_id', type=int)
    rating = request.form.get('rating', type=int)
    comment = request.form.get('comment')
    
    if not product_id or not rating or rating < 1 or rating > 5:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if user has already reviewed this product
        cursor.execute('''
            SELECT * FROM Reviews 
            WHERE CustomerID = ? AND ProductID = ?
        ''', session['user_id'], product_id)
        
        existing = cursor.fetchone()
        
        if existing:
            # Update existing review
            cursor.execute('''
                UPDATE Reviews
                SET Rating = ?, Comment = ?, ReviewDate = GETDATE()
                WHERE CustomerID = ? AND ProductID = ?
            ''', rating, comment, session['user_id'], product_id)
            message = 'Đã cập nhật đánh giá của bạn'
        else:
            # Add new review
            cursor.execute('''
                INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
                VALUES (?, ?, ?, ?, GETDATE())
            ''', session['user_id'], product_id, rating, comment)
            message = 'Cảm ơn bạn đã đánh giá sản phẩm'
        
        conn.commit()
        
        # Get customer name for the response
        cursor.execute('SELECT FullName FROM Customers WHERE CustomerID = ?', session['user_id'])
        customer = cursor.fetchone()
        
        return jsonify({
            'success': True, 
            'message': message,
            'review': {
                'customer_name': customer.FullName,
                'rating': rating,
                'comment': comment,
                'date': datetime.now().strftime('%d/%m/%Y')
            }
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Đã xảy ra lỗi: {str(e)}'})
    finally:
        conn.close()

# Thêm các route mới cho bình luận sản phẩm sau route add_review

# Thêm bình luận sản phẩm
@app.route('/add_comment', methods=['POST'])
def add_comment():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để bình luận sản phẩm'})
    
    product_id = request.form.get('product_id', type=int)
    content = request.form.get('content')
    
    if not product_id or not content:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Add new comment
        cursor.execute('''
            INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, IsVisible)
            VALUES (?, ?, ?, GETDATE(), 1)
        ''', session['user_id'], product_id, content)
        
        conn.commit()
        
        # Get customer name for the response
        cursor.execute('SELECT FullName FROM Customers WHERE CustomerID = ?', session['user_id'])
        customer = cursor.fetchone()
        
        return jsonify({
            'success': True, 
            'message': 'Cảm ơn bạn đã bình luận sản phẩm',
            'comment': {
                'customer_name': customer.FullName,
                'content': content,
                'comment_date': datetime.now().strftime('%d/%m/%Y %H:%M')
            }
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Đã xảy ra lỗi: {str(e)}'})
    finally:
        conn.close()

# API lấy bình luận sản phẩm
@app.route('/api/get_product_comments', methods=['GET'])
def get_product_comments():
    product_id = request.args.get('product_id', type=int)
    
    if not product_id:
        return jsonify({'success': False, 'message': 'Product ID is required'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get product comments
        cursor.execute('''
            SELECT pc.CommentID, pc.Content, pc.CommentDate, pc.AdminReply, pc.ReplyDate, 
                   c.FullName AS CustomerName
            FROM ProductComments pc
            JOIN Customers c ON pc.CustomerID = c.CustomerID
            WHERE pc.ProductID = ? AND pc.IsVisible = 1
            ORDER BY pc.CommentDate DESC
        ''', product_id)
        
        comments_data = cursor.fetchall()
        
        # Format comments
        comments = []
        for comment in comments_data:
            comments.append({
                'comment_id': comment.CommentID,
                'content': comment.Content,
                'comment_date': comment.CommentDate.strftime('%d/%m/%Y %H:%M'),
                'customer_name': comment.CustomerName,
                'reply': comment.AdminReply,
                'reply_date': comment.ReplyDate.strftime('%d/%m/%Y %H:%M') if comment.ReplyDate else None
            })
        
        return jsonify({
            'success': True,
            'comments': comments
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

# Admin route để trả lời bình luận
@app.route('/admin/reply_comment', methods=['POST'])
def admin_reply_comment():
    if 'user_id' not in session or session.get('is_admin') != True:
        return jsonify({'success': False, 'message': 'Bạn không có quyền thực hiện thao tác này'})
    
    comment_id = request.form.get('comment_id', type=int)
    reply = request.form.get('reply')
    
    if not comment_id or not reply:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE ProductComments
            SET AdminReply = ?, ReplyDate = GETDATE()
            WHERE CommentID = ?
        ''', reply, comment_id)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Đã trả lời bình luận thành công'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Đã xảy ra lỗi: {str(e)}'})
    finally:
        conn.close()

# Contact form
@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')
        
        if not name or not email or not message:
            flash('Vui lòng điền đầy đủ thông tin', 'error')
            return redirect(url_for('contact'))
        
        # Validate email format
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('Email không hợp lệ', 'error')
            return redirect(url_for('contact'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Store contact message
            cursor.execute('''
                INSERT INTO ContactMessages (Name, Email, Subject, Message, SubmitDate, Status)
                VALUES (?, ?, ?, ?, GETDATE(), 'New')
            ''', name, email, subject, message)
            
            conn.commit()
            flash('Cảm ơn bạn đã liên hệ với chúng tôi. Chúng tôi sẽ phản hồi sớm nhất có thể.', 'success')
            return redirect(url_for('contact'))
            
        except Exception as e:
            conn.rollback()
            flash(f'Đã xảy ra lỗi: {str(e)}', 'error')
            return redirect(url_for('contact'))
        finally:
            conn.close()
    
    # Get categories for navbar
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    conn.close()
    
    return render_template('contact.html', categories=categories)

# Newsletter subscription
@app.route('/subscribe_newsletter', methods=['POST'])
def subscribe_newsletter():
    email = request.form.get('email')
    
    if not email:
        return jsonify({'success': False, 'message': 'Vui lòng nhập email'})
    
    # Validate email format
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({'success': False, 'message': 'Email không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if email already exists
        cursor.execute('SELECT * FROM NewsletterSubscribers WHERE Email = ?', email)
        
        if cursor.fetchone():
            return jsonify({'success': True, 'message': 'Email này đã đăng ký nhận bản tin'})
        
        # Add new subscriber
        cursor.execute('''
            INSERT INTO NewsletterSubscribers (Email, SubscribeDate, IsActive)
            VALUES (?, GETDATE(), 1)
        ''', email)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Đăng ký nhận bản tin thành công!'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Đã xảy ra lỗi: {str(e)}'})
    finally:
        conn.close()

# Recently viewed products
@app.route('/api/track_product_view', methods=['POST'])
def track_product_view():
    product_id = request.form.get('product_id', type=int)
    
    if not product_id:
        return jsonify({'success': False})
    
    # Store in session
    if 'recently_viewed' not in session:
        session['recently_viewed'] = []
    
    # Remove if already in list
    if product_id in session['recently_viewed']:
        session['recently_viewed'].remove(product_id)
    
    # Add to beginning of list
    session['recently_viewed'].insert(0, product_id)
    
    # Keep only the last 5 items
    session['recently_viewed'] = session['recently_viewed'][:5]
    
    # Save session
    session.modified = True
    
    return jsonify({'success': True})

@app.route('/api/get_recently_viewed')
def get_recently_viewed():
    if 'recently_viewed' not in session or not session['recently_viewed']:
        return jsonify({'success': True, 'products': []})
    
    product_ids = session['recently_viewed']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Convert list to comma-separated string for SQL IN clause
    product_ids_str = ','.join(map(str, product_ids))
    
    # Get products
    cursor.execute(f'''
        SELECT p.ProductID, p.ProductName, p.Price, c.CategoryName
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        WHERE p.ProductID IN ({product_ids_str})
    ''')
    
    products = cursor.fetchall()
    conn.close()
    
    # Convert to list of dicts and maintain original order
    result = []
    for product_id in product_ids:
        for product in products:
            if product.ProductID == product_id:
                result.append({
                    'product_id': product.ProductID,
                    'product_name': product.ProductName,
                    'price': float(product.Price),
                    'category_name': product.CategoryName
                })
                break
    
    return jsonify({'success': True, 'products': result})

# API lấy đánh giá sản phẩm
@app.route('/api/get_product_reviews', methods=['GET'])
def get_product_reviews():
    product_id = request.args.get('product_id', type=int)
    
    if not product_id:
        return jsonify({'success': False, 'message': 'Product ID is required'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get product reviews
        cursor.execute('''
            SELECT r.ReviewID, r.Rating, r.Comment, r.ReviewDate, c.FullName AS CustomerName
            FROM Reviews r
            JOIN Customers c ON r.CustomerID = c.CustomerID
            WHERE r.ProductID = ?
            ORDER BY r.ReviewDate DESC
        ''', product_id)
        
        reviews_data = cursor.fetchall()
        
        # Calculate average rating
        cursor.execute('''
            SELECT AVG(CAST(Rating AS FLOAT)) AS AverageRating, COUNT(*) AS TotalReviews
            FROM Reviews
            WHERE ProductID = ?
        ''', product_id)
        
        avg_data = cursor.fetchone()
        average_rating = avg_data.AverageRating if avg_data and avg_data.AverageRating else 0
        total_reviews = avg_data.TotalReviews if avg_data else 0
        
        # Get rating breakdown
        cursor.execute('''
            SELECT Rating, COUNT(*) as Count
            FROM Reviews
            WHERE ProductID = ?
            GROUP BY Rating
            ORDER BY Rating DESC
        ''', product_id)
        
        rating_breakdown_data = cursor.fetchall()
        rating_breakdown = {i: 0 for i in range(1, 6)}
        for row in rating_breakdown_data:
            rating_breakdown[row.Rating] = row.Count
        
        # Format reviews
        reviews = []
        for review in reviews_data:
            reviews.append({
                'review_id': review.ReviewID,
                'rating': review.Rating,
                'comment': review.Comment,
                'review_date': review.ReviewDate.strftime('%d/%m/%Y'),
                'customer_name': review.CustomerName
            })
        
        return jsonify({
            'success': True,
            'reviews': reviews,
            'average_rating': float(average_rating),
            'total_reviews': int(total_reviews),
            'rating_breakdown': rating_breakdown
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

# Admin contact messages management
@app.route('/admin/contact_messages')
def admin_contact_messages():
    if 'user_id' not in session or session.get('is_admin') != True:
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('home'))
    
    status_filter = request.args.get('status', '')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get contact messages
    query = '''
        SELECT * FROM ContactMessages
    '''
    
    if status_filter:
        query += f" WHERE Status = '{status_filter}'"
    
    query += " ORDER BY SubmitDate DESC"
    
    cursor.execute(query)
    messages = cursor.fetchall()
    
    conn.close()
    
    return render_template('admin/contact_messages.html', messages=messages, current_status=status_filter)

@app.route('/admin/update_message_status', methods=['POST'])
def admin_update_message_status_json():
    # Kiểm tra quyền
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Bạn không có quyền thực hiện thao tác này'}), 403

    # Lấy dữ liệu từ form
    message_id = request.form.get('message_id', type=int)
    new_status = request.form.get('status')

    if not message_id or not new_status:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Cập nhật trạng thái với điều kiện WHERE
        cursor.execute("""
            UPDATE ContactMessages
            SET Status = ?
            WHERE MessageID = ?
        """, (new_status, message_id))

        conn.commit()   # Lưu thay đổi
        return jsonify({'success': True, 'message': 'Cập nhật thành công'}), 200

    except Exception as e:
        conn.rollback()  # Hoàn tác nếu có lỗi
        return jsonify({'success': False, 'message': f'Lỗi: {e}'}), 500

    finally:
        cursor.close()
        conn.close()
        
# Đổi tên hàm thành order_detail_view để không trùng
@app.route('/order/<int:order_id>')
def order_detail_view(order_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    # Lấy đơn hàng và chi tiết – giữ nguyên logic của bạn
    cursor.execute("""
        EXEC sp_GetOrderDetails @OrderID=?
    """, order_id)
    order = cursor.fetchone()
    order_details = []
    if cursor.nextset():
        order_details = cursor.fetchall()
    conn.close()

    # Chỉ chủ đơn mới xem được
    if not order or order.CustomerID != session['user_id']:
        flash('Đơn hàng không tồn tại hoặc bạn không có quyền xem', 'error')
        return redirect(url_for('my_account'))

    return render_template('order_detail.html',
                           order=order,
                           order_details=order_details)

# Admin comments management
@app.route('/admin/comments')
def admin_comments():
    if 'user_id' not in session or session.get('is_admin') != True:
        flash('Bạn không có quyền truy cập trang này', 'error')
        return redirect(url_for('home'))
    
    filter_type = request.args.get('filter', '')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get comments based on filter
    query = '''
        SELECT pc.CommentID, pc.Content, pc.CommentDate, pc.AdminReply, pc.ReplyDate, pc.IsVisible,
               c.FullName AS CustomerName, p.ProductName, p.ProductID
        FROM ProductComments pc
        JOIN Customers c ON pc.CustomerID = c.CustomerID
        JOIN Products p ON pc.ProductID = p.ProductID
    '''
    
    if filter_type == 'no_reply':
        query += " WHERE pc.AdminReply IS NULL"
    elif filter_type == 'replied':
        query += " WHERE pc.AdminReply IS NOT NULL"
    
    query += " ORDER BY pc.CommentDate DESC"
    
    cursor.execute(query)
    comments = cursor.fetchall()
    
    conn.close()
    
    return render_template('admin/comments.html', comments=comments, filter=filter_type)

@app.route('/admin/toggle_comment_visibility', methods=['POST'])
def admin_toggle_comment_visibility():
    if 'user_id' not in session or session.get('is_admin') != True:
        return jsonify({'success': False, 'message': 'Bạn không có quyền thực hiện thao tác này'})
    
    comment_id = request.form.get('comment_id', type=int)
    visible = request.form.get('visible', type=int)
    
    if not comment_id:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE ProductComments
            SET IsVisible = ?
            WHERE CommentID = ?
        ''', visible, comment_id)
        
        conn.commit()
        message = 'Đã hiển thị bình luận' if visible else 'Đã ẩn bình luận'
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Đã xảy ra lỗi: {str(e)}'})
    finally:
        conn.close()

# Cập nhật route admin_update_message_status để trả về JSON
@app.route('/admin/update_message_status', methods=['POST'])
def admin_update_message_status():
    if 'user_id' not in session or session.get('is_admin') != True:
        return jsonify({'success': False, 'message': 'Bạn không có quyền truy cập trang này'})
    
    message_id = request.form.get('message_id', type=int)
    new_status = request.form.get('status')
    
    if not message_id or not new_status:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE ContactMessages
            SET Status = ?
            WHERE MessageID = ?
        ''', new_status, message_id)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Cập nhật trạng thái thành công'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Đã xảy ra lỗi: {str(e)}'})
    finally:
        conn.close()

# Hủy đơn hàng
@app.route('/cancel_order/<int:order_id>', methods=['POST'])
def cancel_order(order_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để hủy đơn hàng'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Kiểm tra đơn hàng có tồn tại và thuộc về người dùng
        cursor.execute('''
            SELECT Status, CustomerID FROM Orders 
            WHERE OrderID = ?
        ''', order_id)
        order = cursor.fetchone()
        
        if not order:
            return jsonify({'success': False, 'message': 'Đơn hàng không tồn tại'})
        
        if order.CustomerID != session['user_id']:
            return jsonify({'success': False, 'message': 'Bạn không có quyền hủy đơn hàng này'})
        
        if order.Status != 'Pending':
            return jsonify({'success': False, 'message': 'Chỉ có thể hủy đơn hàng ở trạng thái Đang xử lý'})
        
        # Cập nhật trạng thái đơn hàng thành 'Cancelled'
        cursor.execute('''
            EXEC sp_UpdateOrderStatus @OrderID=?, @NewStatus=?
        ''', order_id, 'Cancelled')
        
        # Gửi email thông báo hủy đơn hàng
        cursor.execute('SELECT Email, FullName FROM Customers WHERE CustomerID = ?', session['user_id'])
        customer = cursor.fetchone()
        
        if customer:
            html_content = f'''
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background-color: #ff6b6b; color: white; padding: 10px 20px; text-align: center; }}
                        .content {{ padding: 20px; border: 1px solid #ddd; }}
                        .footer {{ margin-top: 20px; font-size: 12px; color: #777; text-align: center; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>Thông báo hủy đơn hàng</h2>
                        </div>
                        <div class="content">
                            <p>Xin chào {customer.FullName},</p>
                            <p>Đơn hàng #{order_id} của bạn đã được hủy theo yêu cầu.</p>
                            <p>Nếu bạn có bất kỳ câu hỏi nào, vui lòng liên hệ với chúng tôi.</p>
                        </div>
                        <div class="footer">
                            <p>© 2025 Fashion Store. All rights reserved.</p>
                        </div>
                    </div>
                </body>
                </html>
            '''
            send_email(customer.Email, 'Hủy đơn hàng - Fashion Store', html_content)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Đã hủy đơn hàng thành công'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Đã xảy ra lỗi: {str(e)}'})
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(debug=True, port=5328)