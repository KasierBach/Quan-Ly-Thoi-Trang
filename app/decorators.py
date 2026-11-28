from functools import wraps

import psycopg2
from flask import current_app, flash, jsonify, redirect, request, session, url_for
from werkzeug.exceptions import HTTPException

from app.validation import ValidationError


JSON_ENDPOINTS = {
    'cart.update_cart',
    'cart.remove_from_cart',
    'cart.cancel_order',
    'product.add_to_wishlist',
    'product.remove_from_wishlist',
    'product.add_review',
    'product.add_comment',
    'main.subscribe_newsletter',
    'auth.toggle_dark_mode',
    'auth.upload_avatar',
}


def api_request():
    return (
        request.path.startswith('/api/')
        or request.path.startswith('/admin/api/')
        or request.endpoint in JSON_ENDPOINTS
        or request.is_json
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )


def login_required(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            if api_request():
                return jsonify(success=False, message='Vui lòng đăng nhập để tiếp tục'), 401
            flash('Vui lòng đăng nhập để tiếp tục', 'warning')
            return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))
        return func(*args, **kwargs)

    return decorated


def role_required(*roles):
    def wrapper(func):
        @wraps(func)
        @login_required
        def decorated(*args, **kwargs):
            if session.get('role') not in roles:
                if api_request():
                    return jsonify(success=False, message='Bạn không có quyền truy cập'), 403
                flash('Bạn không có quyền truy cập trang này', 'error')
                return redirect(url_for('main.home'))
            return func(*args, **kwargs)

        return decorated

    return wrapper


def admin_required(func):
    return role_required('admin')(func)


def handle_db_errors(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HTTPException:
            raise
        except ValidationError as exc:
            if api_request():
                return jsonify(success=False, message=str(exc)), 400
            flash(str(exc), 'error')
            return redirect(url_for('main.home'))
        except psycopg2.Error as exc:
            current_app.logger.error(
                'Database operation failed in %s [%s, SQLSTATE=%s]',
                func.__name__,
                type(exc).__name__,
                exc.pgcode or 'unavailable',
            )
            if api_request():
                return jsonify(success=False, message='Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.'), 503
            return current_app.make_response(('Dịch vụ dữ liệu tạm thời không khả dụng', 503))

    return decorated
