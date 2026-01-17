from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from app.database import get_db_connection
from app.utils import send_email
import re

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def home():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    
    cursor.execute('''
        SELECT p.ProductID, p.ProductName, p.Price, p.OriginalPrice, c.CategoryName, p.ImageURL,
        (SELECT cl.ColorName FROM Colors cl JOIN ProductVariants pv ON cl.ColorID = pv.ColorID 
         WHERE pv.ProductID = p.ProductID LIMIT 1) AS FirstColor
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        ORDER BY p.CreatedAt DESC
        LIMIT 8
    ''')
    featured_products = cursor.fetchall()
    
    cursor.execute('''
        SELECT bs.ProductID, bs.ProductName, bs.Price, bs.OriginalPrice, bs.CategoryName, bs.TotalSold, p.ImageURL
        FROM vw_BestSellingProducts bs
        JOIN Products p ON bs.ProductID = p.ProductID
        ORDER BY bs.TotalSold DESC
    ''')
    best_selling = cursor.fetchall()
    conn.close()
    
    return render_template('index.html', 
                          categories=categories, 
                          featured_products=featured_products,
                          best_selling=best_selling)

@main_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')
        
        if not name or not email or not message:
            flash('Vui lòng điền đầy đủ thông tin', 'error')
            return redirect(url_for('main.contact'))
        
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('Email không hợp lệ', 'error')
            return redirect(url_for('main.contact'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO ContactMessages (Name, Email, Subject, Message, SubmitDate, Status)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, 'New')
            ''', (name, email, subject, message))
            conn.commit()
            flash('Cảm ơn bạn đã liên hệ!', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'Lỗi: {str(e)}', 'error')
        finally:
            conn.close()
        return redirect(url_for('main.contact'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    conn.close()
    
    return render_template('contact.html', categories=categories)

@main_bp.route('/subscribe_newsletter', methods=['POST'])
def subscribe_newsletter():
    email = request.form.get('email')
    if not email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({'success': False, 'message': 'Email không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM NewsletterSubscribers WHERE Email = %s', (email,))
        if cursor.fetchone():
            return jsonify({'success': True, 'message': 'Email đã đăng ký'})
        
        cursor.execute('''
            INSERT INTO NewsletterSubscribers (Email, SubscribeDate, IsActive)
            VALUES (%s, CURRENT_TIMESTAMP, 1)
        ''', (email,))
        conn.commit()
        return jsonify({'success': True, 'message': 'Đăng ký nhận bản tin thành công!'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()
