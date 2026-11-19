from flask import abort, flash, redirect, render_template, request, url_for

from app.decorators import handle_db_errors
from app.services.order_service import OrderService
from app.validation import ValidationError, positive_int

from .blueprint import admin_bp, admin_required, paging_args


ORDER_STATES = {'Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled'}
ORDER_TRANSITIONS = {
    'Pending': ('Pending', 'Processing', 'Cancelled'),
    'Processing': ('Processing', 'Shipped', 'Cancelled'),
    'Shipped': ('Shipped', 'Delivered'),
    'Delivered': ('Delivered',),
    'Cancelled': ('Cancelled',),
}
ORDER_LABELS = {
    'Pending': 'Chờ xác nhận',
    'Processing': 'Đang xử lý',
    'Shipped': 'Đang giao hàng',
    'Delivered': 'Đã giao hàng',
    'Cancelled': 'Đã hủy',
}


@admin_bp.route('/admin/orders')
@admin_required
@handle_db_errors
def admin_orders():
    status = request.args.get('status', '')
    if status and status not in ORDER_STATES:
        abort(400, description='Trạng thái đơn hàng không hợp lệ')
    page, per_page = paging_args(request.args)
    result = OrderService.get_orders_admin(status, page, per_page)
    return render_template('admin/orders.html', orders=result['orders'], current_status=status, paging=result)


@admin_bp.route('/admin/orders/<int:order_id>')
@admin_required
@handle_db_errors
def admin_order_detail(order_id):
    try:
        order_id = positive_int(order_id, 'Đơn hàng', max_value=2147483647)
    except ValidationError as exc:
        abort(400, description=str(exc))
    detail = OrderService.get_order_detail(order_id)
    if not detail:
        abort(404)
    order = detail['order']
    return render_template(
        'admin/order_detail.html',
        order=order,
        order_details=detail['items'],
        status_options=ORDER_TRANSITIONS.get(order.Status, ()),
        status_labels=ORDER_LABELS,
    )


@admin_bp.route('/admin/orders/update_status', methods=['POST'])
@admin_required
@handle_db_errors
def admin_update_order_status():
    try:
        order_id = positive_int(request.form.get('order_id'), 'Đơn hàng', max_value=2147483647)
        status = request.form.get('status')
        if status not in ORDER_STATES:
            raise ValidationError('Trạng thái đơn hàng không hợp lệ')
    except ValidationError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admin.admin_orders'))
    result = OrderService.update_order_status(order_id, status)
    flash(
        'Cập nhật trạng thái thành công!'
        if result['success']
        else result.get('message', 'Không thể cập nhật trạng thái'),
        'success' if result['success'] else 'error',
    )
    return redirect(url_for('admin.admin_order_detail', order_id=order_id))
