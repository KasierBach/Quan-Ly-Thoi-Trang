from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from app.database import get_db_connection
from app.utils import send_email
import re

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def home():
    # Use ProductService to fetch data
    from app.services.product_service import ProductService
    
    featured_products = ProductService.get_featured_products(8)
    best_selling = ProductService.get_best_selling_products(8)
    
    return render_template('index.html', 
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
    conn = get_db_connection()
    cursor = conn.cursor()
    # categories fetching removed - handled by context processor
    conn.close()
    
    return render_template('contact.html')

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
