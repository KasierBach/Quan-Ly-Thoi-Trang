from flask import render_template, request, redirect, url_for, flash
from app.services.order_service import OrderService
from .blueprint import admin_bp, admin_required
from app.decorators import handle_db_errors

@admin_bp.route('/admin/orders')
@admin_required
@handle_db_errors
def admin_orders():
    args = request.args
    status = args.get('status', '')
    page, per_page = args.get('page', 1, type=int), args.get('per_page', 20, type=int)
    
    if page < 1: page = 1
    if per_page not in [10, 20, 50, 100]: per_page = 20

    res = OrderService.get_orders_admin(status, page, per_page)
    return render_template('admin/orders.html', orders=res['orders'], current_status=status, paging=res)

@admin_bp.route('/admin/orders/<int:order_id>')
@admin_required
@handle_db_errors
def admin_order_detail(order_id):
    detail = OrderService.get_order_detail(order_id)
    if not detail:
        flash('Đơn hàng không tồn tại', 'error')
        return redirect(url_for('admin.admin_orders'))
        
    return render_template('admin/order_detail.html', order=detail['order'], order_details=detail['items'])

@admin_bp.route('/admin/orders/update_status', methods=['POST'])
@admin_required
@handle_db_errors
def admin_update_order_status():
    oid, status = request.form.get('order_id', type=int), request.form.get('status')
    if not oid or not status: return redirect(url_for('admin.admin_orders'))
    
    res = OrderService.update_order_status(oid, status)
    flash('Cập nhật trạng thái thành công!' if res['success'] else res.get('message', 'Lỗi'), 
          'success' if res['success'] else 'error')
    
    return redirect(url_for('admin.admin_order_detail', order_id=oid))
