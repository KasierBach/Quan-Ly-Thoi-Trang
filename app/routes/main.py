from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from app.services.main_service import MainService
from app.services.product_service import ProductService
from app.decorators import handle_db_errors
import re
from datetime import datetime

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@handle_db_errors
def home():
    featured = ProductService.get_featured_products(8)
    best_selling = ProductService.get_best_selling_products(8)
    return render_template('index.html', featured_products=featured, best_selling=best_selling)

@main_bp.route('/contact', methods=['GET', 'POST'])
@handle_db_errors
def contact():
    if request.method == 'GET':
        return render_template('contact.html')
        
    name, email = request.form.get('name'), request.form.get('email')
    subj, msg = request.form.get('subject'), request.form.get('message')
    
    if not all([name, email, msg]):
        flash('Vui lòng điền đầy đủ thông tin', 'error')
        return redirect(url_for('main.contact'))
    
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        flash('Email không hợp lệ', 'error')
        return redirect(url_for('main.contact'))
    
    res = MainService.add_contact_message(name, email, subj, msg)
    if res['success']:
        flash('Cảm ơn bạn đã liên hệ!', 'success')
    else:
        flash('Gửi tin không thành công', 'error')
    
    return redirect(url_for('main.contact'))

@main_bp.route('/subscribe_newsletter', methods=['POST'])
@handle_db_errors
def subscribe_newsletter():
    email = request.form.get('email')
    if not email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({'success': False, 'message': 'Email không hợp lệ'})
    
    return jsonify(MainService.subscribe_newsletter(email))

@main_bp.route('/health')
def health_check():
    """Health check endpoint for uptime monitoring."""
    is_healthy = MainService.check_health()
    status = 'healthy' if is_healthy else 'unhealthy'
    return jsonify({
        'status': status,
        'database': 'connected' if is_healthy else 'error',
        'timestamp': datetime.now().isoformat()
    }), (200 if is_healthy else 500)
