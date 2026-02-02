from flask import Blueprint, session, flash, redirect, url_for

admin_bp = Blueprint('admin', __name__)

def is_admin():
    """Helper to check if current user is admin."""
    return 'user_id' in session and session.get('is_admin') == True

def admin_required(f):
    """Decorator for admin-only routes."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_admin():
            flash('Bạn không có quyền truy cập trang này', 'error')
            return redirect(url_for('main.home'))
        return f(*args, **kwargs)
    return decorated_function
