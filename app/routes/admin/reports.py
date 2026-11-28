from datetime import datetime
from decimal import Decimal

from flask import Response, abort, current_app, jsonify, render_template, request
from markupsafe import escape

from app.decorators import handle_db_errors
from app.services.media_service import MediaService
from app.services.report_service import ReportService
from app.utils import send_email
from app.validation import ValidationError, email_address, required_text

from .blueprint import admin_bp, admin_required, service_response


@admin_bp.route('/admin')
@admin_required
@handle_db_errors
def admin_dashboard():
    stats = ReportService.get_dashboard_stats()
    monthly_chart = [
        {'Month': row.Month, 'Year': row.Year, 'TotalRevenue': float(row.TotalRevenue or 0)}
        for row in reversed(stats['monthly_revenue'][:12])
    ]
    category_chart = [
        {'CategoryName': row.CategoryName, 'TotalRevenue': float(row.CategoryRevenue or 0)}
        for row in stats['category_revenue']
    ]
    return render_template(
        'admin/dashboard.html', **stats, now=datetime.now(), monthly_chart=monthly_chart, category_chart=category_chart
    )


@admin_bp.route('/admin/reports')
@admin_required
@handle_db_errors
def admin_reports():
    args = request.args
    try:
        data = ReportService.get_revenue_report(
            args.get('start_date'), args.get('end_date'), args.get('group_by', 'day')
        )
    except ValidationError as exc:
        abort(400, description=str(exc))
    daily, categories = data['daily_revenue'], data['category_revenue']
    group = data['group_by']
    formats = {'month': '%m/%Y', 'year': '%Y'}
    labels = []
    for row in daily:
        if group == 'week':
            year, week, _ = row.OrderDate.isocalendar()
            labels.append(f'W{week:02d}-{year}')
        else:
            labels.append(row.OrderDate.strftime(formats.get(group, '%d/%m/%Y')))
    total_revenue = sum((Decimal(str(row.DailyRevenue or 0)) for row in daily), Decimal('0'))
    total_category = sum((Decimal(str(row.CategoryRevenue or 0)) for row in categories), Decimal('0'))
    return render_template(
        'admin/reports.html',
        **data,
        dates=labels,
        revenues=[float(row.DailyRevenue or 0) for row in daily],
        category_names=[row.CategoryName for row in categories],
        category_revenues=[float(row.CategoryRevenue or 0) for row in categories],
        total_revenue=total_revenue,
        total_category_revenue=total_category,
        total_orders=sum(int(row.OrderCount or 0) for row in daily),
        now=datetime.now(),
        report_names=ReportService.REPORT_NAMES,
        period_labels=labels,
        email_enabled=not current_app.testing
        and not current_app.config.get('MAIL_SUPPRESS_SEND')
        and bool(current_app.config.get('MAIL_SERVER') and current_app.config.get('MAIL_DEFAULT_SENDER')),
    )


@admin_bp.route('/admin/reports/export')
@admin_required
@handle_db_errors
def admin_export_report():
    args = request.args
    report_type = args.get('report_type', 'daily_revenue')
    try:
        ReportService.validate_report_type(report_type)
        contents = ReportService.generate_csv_report(
            report_type, args.get('start_date'), args.get('end_date'), args.get('group_by', 'day')
        )
    except ValidationError:
        return jsonify(success=False, message='Loại báo cáo, khoảng ngày hoặc cách nhóm không hợp lệ'), 400
    return Response(
        contents,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename="bao_cao_{report_type}.csv"',
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
        },
    )


@admin_bp.route('/admin/api/send_report_email', methods=['POST'])
@admin_required
@handle_db_errors
def admin_send_report_email():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'message': 'Dữ liệu JSON không hợp lệ'}), 400
    try:
        recipient = email_address(data.get('email'))
        text = data.get('message', '')
        if text:
            text = required_text(text, 'Lời nhắn', 5000)
        elif not isinstance(text, str):
            raise ValidationError('Lời nhắn không hợp lệ')
        report_type = ReportService.validate_report_type(data.get('report_type', 'daily_revenue'))
        group_by = ReportService.validate_group(data.get('group_by', 'day'))
        start, end = ReportService.validate_dates(data.get('start_date'), data.get('end_date'))
    except ValidationError:
        return jsonify(success=False, message='Kiểm tra email, lời nhắn và bộ lọc báo cáo trước khi gửi'), 400
    if (
        current_app.testing
        or current_app.config.get('MAIL_SUPPRESS_SEND')
        or not current_app.config.get('MAIL_SERVER')
        or not current_app.config.get('MAIL_DEFAULT_SENDER')
    ):
        return jsonify({'success': False, 'message': 'Gửi email chưa được cấu hình hoặc đang tắt'}), 503
    csv_bytes = ReportService.generate_csv_report(
        report_type, start.isoformat() if start else None, end.isoformat(), group_by
    )
    name = ReportService.REPORT_NAMES[report_type]
    period = f'{start.isoformat() if start else "Tất cả"} đến {end.isoformat()}'
    if report_type == 'low_stock':
        period = 'Tồn kho hiện tại, không lọc theo ngày'
    body = f'<p>Báo cáo: {escape(name)}</p><p>Khoảng thời gian: {escape(period)}</p><pre>{escape(text)}</pre>'
    sent = send_email(
        recipient,
        f'[FashionStore] {name}',
        body,
        attachments=[(f'bao_cao_{report_type}.csv', 'text/csv; charset=utf-8', csv_bytes)],
    )
    if not sent:
        return jsonify(
            {'success': False, 'message': 'Không thể gửi email. Vui lòng kiểm tra cấu hình và thử lại.'}
        ), 502
    return jsonify({'success': True, 'message': 'Đã gửi báo cáo đến máy chủ email'})


@admin_bp.route('/admin/api/search_pixabay', methods=['GET'])
@admin_required
@handle_db_errors
def admin_search_pixabay():
    try:
        return service_response(MediaService.search_pixabay(request.args.get('q', '')))
    except ValidationError:
        return jsonify(success=False, message='Nhập từ khóa tìm ảnh dài từ 1 đến 100 ký tự'), 400


@admin_bp.route('/admin/api/save_pixabay_image', methods=['POST'])
@admin_required
@handle_db_errors
def admin_save_pixabay_image():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'message': 'Dữ liệu JSON không hợp lệ'}), 400
    try:
        return service_response(MediaService.save_pixabay_image(data.get('image_url'), data.get('product_id')))
    except ValidationError:
        return jsonify(success=False, message='Kiểm tra sản phẩm và chọn ảnh HTTPS từ Pixabay'), 400
