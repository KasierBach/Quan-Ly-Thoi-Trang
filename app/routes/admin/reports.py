from flask import render_template, request, jsonify, current_app
from datetime import datetime
import socket
from flask_mail import Message
from app.services.report_service import ReportService
from app.services.media_service import MediaService
from .blueprint import admin_bp, admin_required
from app.decorators import handle_db_errors

@admin_bp.route('/admin')
@admin_required
@handle_db_errors
def admin_dashboard():
    stats = ReportService.get_dashboard_stats()
    return render_template('admin/dashboard.html', **stats, now=datetime.now())

@admin_bp.route('/admin/reports')
@admin_required
@handle_db_errors
def admin_reports():
    args = request.args
    sd, ed, group = args.get('start_date'), args.get('end_date'), args.get('group_by', 'day')
    
    data = ReportService.get_revenue_report(sd, ed, group)
    daily, cat = data['daily_revenue'], data['category_revenue']
    
    dates, revenues = [], []
    total_rev, total_ord = 0, 0
    
    fmts = {'month': '%m/%Y', 'year': '%Y', 'week': 'W%W-%Y'}
    for row in daily:
        d_str = row.OrderDate.strftime(fmts.get(group, '%d/%m/%Y')) if hasattr(row.OrderDate, 'strftime') else str(row.OrderDate)
        dates.append(d_str)
        rev = float(row.DailyRevenue or 0)
        revenues.append(rev)
        total_rev += rev
        total_ord += (row.OrderCount or 0)
        
    return render_template('admin/reports.html', 
                          **data, dates=dates, revenues=revenues, 
                          category_names=[r.CategoryName for r in cat], 
                          category_revenues=[float(r.CategoryRevenue or 0) for r in cat],
                          total_revenue=total_rev, total_orders=total_ord, now=datetime.now())

@admin_bp.route('/admin/api/send_report_email', methods=['POST'])
@admin_required
@handle_db_errors
def admin_send_report_email():
    data = request.get_json()
    recipient, msg_text = data.get('email'), data.get('message', '')
    sd, ed, rtype = data.get('start_date'), data.get('end_date'), data.get('report_type', 'daily_revenue')
    
    if not recipient: return jsonify({'success': False, 'message': 'Email recipient is required'}), 400
    
    m_user, m_pass = current_app.config.get('MAIL_USERNAME'), current_app.config.get('MAIL_PASSWORD')
    if not m_user or not m_pass: return jsonify({'success': False, 'message': 'Hệ thống chưa cấu hình Email SMTP.'}), 500
        
    names = {'daily_revenue': 'Doanh thu theo ngày', 'best_selling': 'Sản phẩm bán chạy', 'category_revenue': 'Doanh thu theo danh mục', 'top_customers': 'Khách hàng VIP', 'low_stock': 'Tồn kho thấp', 'order_details': 'Chi tiết đơn hàng'}
    name = names.get(rtype, 'Báo cáo')

    try:
        csv_bytes = ReportService.generate_csv_report(rtype, sd, ed)
        filename, subject = f"bao_cao_{rtype}_{sd}_den_{ed}.csv", f"[FashionStore] {name} ({sd} - {ed})"
        body = f"Xin chào,\n\nĐính kèm là báo cáo: {name}\nThời gian: {sd} đến {ed}\n\nLời nhắn: {msg_text}\n\nTrân trọng,\nFashionStore Admin"

        msg = Message(subject=subject, recipients=[recipient], body=body)
        msg.attach(filename, "text/csv; charset=utf-8", csv_bytes)
        
        orig_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(15)
            current_app.mail.send(msg)
        finally:
            socket.setdefaulttimeout(orig_timeout)
        
        return jsonify({'success': True, 'message': f'Đã gửi báo cáo "{name}" thành công!'})
    except Exception as e:
        return ReportService.handle_error(e)

@admin_bp.route('/admin/api/search_pixabay', methods=['GET'])
@admin_required
@handle_db_errors
def admin_search_pixabay():
    query = request.args.get('q', '')
    return jsonify(MediaService.search_pixabay(query))

@admin_bp.route('/admin/api/save_pixabay_image', methods=['POST'])
@admin_required
@handle_db_errors
def admin_save_pixabay_image():
    data = request.json
    return jsonify(MediaService.save_pixabay_image(data.get('image_url'), data.get('product_id')))
