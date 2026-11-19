from flask import Blueprint, jsonify

# All admin routes use the shared authorization contract.
from app.decorators import admin_required
from app.validation import ValidationError, positive_int


admin_bp = Blueprint('admin', __name__)
__all__ = ['admin_bp', 'admin_required', 'paging_args', 'service_response']


def paging_args(args, default=20, allowed=(10, 20, 50, 100)):
    """Bound malformed query pagination without sending negative/huge SQL offsets."""
    try:
        page = positive_int(args.get('page', '1'), 'Trang', max_value=1000000)
    except ValidationError:
        page = 1
    try:
        per_page = positive_int(args.get('per_page', str(default)), 'Số dòng', max_value=100)
    except ValidationError:
        per_page = default
    if per_page not in allowed:
        per_page = default
    return page, per_page


def service_response(result):
    payload = dict(result)
    status = payload.pop('status_code', 200 if payload.get('success') else 400)
    return jsonify(payload), status
