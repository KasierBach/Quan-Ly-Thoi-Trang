from functools import wraps
from flask import session, redirect, url_for, flash, request

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập để tiếp tục', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    """
    Decorator to restrict access to users with specific roles.
    Usage: @role_required('admin'), @role_required('admin', 'staff')
    """
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login', next=request.url))
            
            user_role = session.get('role', 'customer')
            
            # Allow verification if user has ANY of the required roles
            # Also support legacy 'is_admin' session check for backward compatibility for a moment if needed,
            # but better to stick to 'role'.
            if user_role not in roles:
                 # Fallback: if 'admin' is required, check legacy is_admin
                if 'admin' in roles and session.get('is_admin'):
                     pass # Allow
                else:
                    flash('Bạn không có quyền truy cập trang này', 'error')
                    return redirect(url_for('main.home'))
            
            return f(*args, **kwargs)
        return decorated_function
    return wrapper

# Alias for backward compatibility or ease of use
def admin_required(f):
    return role_required('admin')(f)
