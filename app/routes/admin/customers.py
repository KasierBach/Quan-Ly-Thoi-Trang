from flask import abort, flash, redirect, render_template, request, session, url_for

from app.decorators import handle_db_errors
from app.services.customer_service import CustomerService
from app.validation import ValidationError

from .blueprint import admin_bp, admin_required, paging_args, service_response


@admin_bp.route('/admin/customers')
@admin_required
@handle_db_errors
def admin_customers():
    args = request.args
    page, per_page = paging_args(args)
    try:
        result = CustomerService.search_customers(
            args.get('search', ''), args.get('role', 'all'), page, per_page, args.get('sort_by', 'newest')
        )
    except ValidationError as exc:
        abort(400, description=str(exc))
    return render_template('admin/customers.html', customers=result['customers'], paging=result)


@admin_bp.route('/admin/customers/delete/<int:customer_id>', methods=['POST'])
@admin_required
@handle_db_errors
def admin_delete_customer(customer_id):
    try:
        result = CustomerService.delete_customer(customer_id, actor_id=session['user_id'])
    except ValidationError as exc:
        result = {'success': False, 'message': str(exc), 'status_code': 400}
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return service_response(result)
    flash(
        result.get('message', 'Xóa khách hàng thành công' if result['success'] else 'Không thể xóa khách hàng'),
        'success' if result['success'] else 'error',
    )
    return redirect(url_for('admin.admin_customers'))


@admin_bp.route('/admin/customers/<int:customer_id>')
@admin_required
@handle_db_errors
def admin_customer_detail(customer_id):
    try:
        details = CustomerService.get_customer_details(customer_id)
    except ValidationError as exc:
        abort(400, description=str(exc))
    if not details:
        abort(404)
    return render_template('admin/customer_detail.html', **details)
