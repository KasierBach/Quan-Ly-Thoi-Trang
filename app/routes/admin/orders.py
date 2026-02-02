from flask import render_template, request, redirect, url_for, flash
import psycopg2
from app.database import get_db_connection
from app.services.order_service import OrderService
from .blueprint import admin_bp, admin_required

@admin_bp.route('/admin/orders')
@admin_required
def admin_orders():
    status = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    if page < 1: page = 1
    if per_page not in [10, 20, 50, 100]: per_page = 20

    data = OrderService.get_orders(status, page, per_page)
    orders = data['orders']
    
    paging_data = {
        'total_records': data['total_records'],
        'total_pages': data['total_pages'],
        'current_page': data['current_page'],
        'per_page': data['per_page'],
        'start_index': data['start_index'],
        'end_index': data['end_index']
    }
    
    return render_template('admin/orders.html', orders=orders, current_status=status, paging=paging_data)

@admin_bp.route('/admin/orders/<int:order_id>')
@admin_required
def admin_order_detail(order_id):
    detail = OrderService.get_order_detail(order_id)
    if not detail:
        flash('Đơn hàng không tồn tại', 'error')
        return redirect(url_for('admin.admin_orders'))
        
    order = detail['order']
    order_details = detail['items']
    return render_template('admin/order_detail.html', order=order, order_details=order_details)

@admin_bp.route('/admin/orders/update_status', methods=['POST'])
@admin_required
def admin_update_order_status():
    order_id = request.form.get('order_id', type=int)
    new_status = request.form.get('status')
    if not order_id or not new_status: return redirect(url_for('admin.admin_orders'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, new_status))
        conn.commit()
        flash('Cập nhật trạng thái thành công!', 'success')
    except psycopg2.Error as e:
        conn.rollback()
        flash(f'Lỗi: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin.admin_order_detail', order_id=order_id))
