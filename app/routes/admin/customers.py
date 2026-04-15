from flask import render_template, request, redirect, url_for, flash, jsonify
from app.services.customer_service import CustomerService
from .blueprint import admin_bp, admin_required
from app.decorators import handle_db_errors

@admin_bp.route('/admin/customers')
@admin_required
@handle_db_errors
def admin_customers():
    args = request.args
    page, per_page = args.get('page', 1, type=int), args.get('per_page', 20, type=int)
    search, role = args.get('search', ''), args.get('role', 'all')
    sort_by = args.get('sort_by', 'newest')
    
    if page < 1: page = 1
    if per_page not in [10, 20, 50, 100]: per_page = 20

    res = CustomerService.search_customers(search, role, page, per_page, sort_by)
    return render_template('admin/customers.html', customers=res['customers'], paging=res)

@admin_bp.route('/admin/customers/delete/<int:customer_id>', methods=['POST'])
@admin_required
@handle_db_errors
def admin_delete_customer(customer_id):
    res = CustomerService.delete_customer(customer_id)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(res)
    flash(res.get('message', 'Thành công') if not res['success'] else 'Xóa khách hàng thành công', 
          'success' if res['success'] else 'error')
    return redirect(url_for('admin.admin_customers'))

@admin_bp.route('/admin/customers/<int:customer_id>')
@admin_required
@handle_db_errors
def admin_customer_detail(customer_id):
    details = CustomerService.get_customer_details(customer_id)
    if not details:
        flash('Khách hàng không tồn tại', 'error')
        return redirect(url_for('admin.admin_customers'))
    
    return render_template('admin/customer_detail.html', 
                           customer=details['customer'], 
                           orders=details['orders'],
                           comments=details.get('comments', []),
                           stats=details.get('stats', {'totalorders': 0, 'totalspent': 0}))
