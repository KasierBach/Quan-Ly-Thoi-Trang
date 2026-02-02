from flask import render_template, request, jsonify, current_app
from datetime import datetime
import requests
import os
import socket
from flask_mail import Message
from app.services.report_service import ReportService
from .blueprint import admin_bp, admin_required

@admin_bp.route('/admin')
@admin_required
def admin_dashboard():
    stats = ReportService.get_dashboard_stats()
    return render_template('admin/dashboard.html', 
                           monthly_revenue=stats['monthly_revenue'], 
                           category_revenue=stats['category_revenue'], 
                           best_selling=stats['best_selling'], 
                           now=datetime.now(),
                           current_month_revenue=stats['current_month_revenue'],
                           current_month_orders=stats['current_month_orders'],
                           total_sold=stats['total_sold'],
                           new_customers=stats['new_customers'])

@admin_bp.route('/admin/reports')
@admin_required
def admin_reports():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    group_by = request.args.get('group_by', 'day')
    
    report_data = ReportService.get_revenue_report(start_date, end_date, group_by)
    
    daily_revenue = report_data['daily_revenue']
    category_revenue = report_data['category_revenue']
    best_selling = report_data['best_selling']
    start_date = report_data['start_date']
    end_date = report_data['end_date']
    new_customers_range = report_data['new_customers_range']
    
    today = datetime.now()
    dates = []
    revenues = []
    total_rev = 0
    total_ord = 0
    
    for row in daily_revenue:
        if group_by == 'month':
            d_str = row.OrderDate.strftime('%m/%Y')
        elif group_by == 'year':
            d_str = row.OrderDate.strftime('%Y')
        elif group_by == 'week':
            try:
                d_str = row.OrderDate.strftime('W%W-%Y')
            except:
                d_str = str(row.OrderDate)
        else:
            d_str = row.OrderDate.strftime('%d/%m/%Y')
            
        dates.append(d_str)
        rev = float(row.DailyRevenue) if row.DailyRevenue else 0.0
        total_rev += rev
        total_ord += (row.OrderCount or 0)
        revenues.append(rev)
    
    cat_names = []
    cat_revs = []
    for row in category_revenue:
        cat_names.append(row.CategoryName)
        cat_revs.append(float(row.CategoryRevenue) if row.CategoryRevenue else 0.0)
        
    return render_template('admin/reports.html', 
                           daily_revenue=daily_revenue, 
                           category_revenue=category_revenue, 
                           best_selling=best_selling, 
                           now=today,
                           start_date=start_date, 
                           end_date=end_date, 
                           dates=dates, 
                           revenues=revenues, 
                           category_names=cat_names, 
                           category_revenues=cat_revs,
                           total_revenue=total_rev,
                           total_orders=total_ord,
                           new_customers=new_customers_range,
                           group_by=group_by)

@admin_bp.route('/admin/api/send_report_email', methods=['POST'])
@admin_required
def admin_send_report_email():
    data = request.get_json()
    recipient = data.get('email')
    user_message = data.get('message', '')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    report_type = data.get('report_type', 'daily_revenue')
    
    if not recipient:
        return jsonify({'success': False, 'message': 'Email recipient is required'}), 400
    
    mail_user = current_app.config.get('MAIL_USERNAME')
    mail_pass = current_app.config.get('MAIL_PASSWORD')
    
    if not mail_user or not mail_pass:
        return jsonify({'success': False, 'message': 'Hệ thống chưa cấu hình Email SMTP.'}), 500
        
    report_names = {
        'daily_revenue': 'Doanh thu theo ngày',
        'best_selling': 'Sản phẩm bán chạy',
        'category_revenue': 'Doanh thu theo danh mục',
        'top_customers': 'Khách hàng VIP',
        'low_stock': 'Tồn kho thấp',
        'order_details': 'Chi tiết đơn hàng'
    }
    report_name = report_names.get(report_type, 'Báo cáo')

    try:
        csv_bytes = ReportService.generate_csv_report(report_type, start_date, end_date)
        filename = f"bao_cao_{report_type}_{start_date}_den_{end_date}.csv"
        subject = f"[FashionStore] {report_name} ({start_date} - {end_date})"
        body_content = f"Xin chào,\n\nĐính kèm là báo cáo: {report_name}\nThời gian: {start_date} đến {end_date}\n\nLời nhắn: {user_message}\n\nTrân trọng,\nFashionStore Admin"

        msg = Message(subject=subject, recipients=[recipient], body=body_content)
        msg.attach(filename, "text/csv; charset=utf-8", csv_bytes)
        
        original_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(15)
            current_app.mail.send(msg)
        finally:
            socket.setdefaulttimeout(original_timeout)
        
        return jsonify({'success': True, 'message': f'Đã gửi báo cáo "{report_name}" đến {recipient} thành công!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi khi gửi email: {str(e)}'}), 500

@admin_bp.route('/admin/api/search_pixabay', methods=['GET'])
@admin_required
def admin_search_pixabay():
    query = request.args.get('q', '')
    if not query: return jsonify({'success': False})
    
    try:
        params = {
            'key': current_app.config['PIXABAY_API_KEY'], 
            'q': query,
            'image_type': 'photo',
            'per_page': 20,
            'safesearch': 'true'
        }
        resp = requests.get(current_app.config['PIXABAY_ENDPOINT'], params=params, timeout=10)
        resp.raise_for_status()
        return jsonify({'success': True, 'hits': resp.json().get('hits', [])})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/admin/api/save_pixabay_image', methods=['POST'])
@admin_required
def admin_save_pixabay_image():
    data = request.json
    image_url = data.get('image_url')
    product_id = data.get('product_id')
    if not image_url or not product_id: return jsonify({'success': False})
    
    try:
        IMAGE_FOLDER = os.path.join(current_app.root_path, 'static', 'images')
        os.makedirs(IMAGE_FOLDER, exist_ok=True)
        filename = f"{product_id}.jpg"
        filepath = os.path.join(IMAGE_FOLDER, filename)
        
        r = requests.get(image_url, timeout=10)
        r.raise_for_status()
        with open(filepath, 'wb') as f: f.write(r.content)
        
        return jsonify({'success': True, 'path': f"images/{filename}"})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
