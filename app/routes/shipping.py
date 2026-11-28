"""Authorized, read-only shipping-address lookup. Register shipping_bp in the app factory."""

import psycopg2
from flask import Blueprint, jsonify, request, session
from werkzeug.exceptions import HTTPException

from app.decorators import handle_db_errors, login_required
from app.extensions import limiter
from app.services.geocode_service import GeocodeError, GeocodeService
from app.services.order_service import OrderService
from app.validation import ValidationError


shipping_bp = Blueprint('shipping', __name__, url_prefix='/shipping')
GEOCODE_ERROR_MESSAGES = {
    404: 'Chưa tìm thấy vị trí phù hợp với địa chỉ đã lưu.',
    422: 'Địa chỉ đã lưu chưa đủ thông tin để xác định vị trí.',
    429: 'Dịch vụ bản đồ đang bận. Vui lòng thử lại sau.',
}


def _error(message, status_code, retry_after=None):
    response = jsonify(success=False, message=message)
    response.status_code = status_code
    if retry_after is not None:
        response.headers['Retry-After'] = str(retry_after)
    return response


def _private_response(response):
    if request.path.startswith('/shipping/geocode/'):
        response.headers['Cache-Control'] = 'private, no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.vary.add('Cookie')
    return response


@shipping_bp.record_once
def _register_privacy_finalizer(state):
    # Run after the existing security hook (Flask runs after_request in reverse)
    # so its generic no-store assignment cannot remove the private directive.
    state.app.after_request_funcs.setdefault(None, []).insert(0, _private_response)


@shipping_bp.app_context_processor
def _map_context():
    return {
        'shipping_map_enabled': GeocodeService.is_configured,
        'shipping_geocode_network_enabled': GeocodeService.network_enabled,
    }


@shipping_bp.before_request
def _json_login_guard():
    # This endpoint is always JSON, even without an Accept header. Keep the
    # existing login_required decorator as the shared authentication boundary.
    if not session.get('user_id'):
        return _error('Vui lòng đăng nhập để xem vị trí theo địa chỉ.', 401)
    return None


@shipping_bp.errorhandler(HTTPException)
def _http_error(error):
    if error.code == 429:
        return _error('Bạn đã xem vị trí quá nhiều lần. Vui lòng thử lại sau.', 429, 60)
    return _error('Không thể xem vị trí theo địa chỉ.', error.code or 503)


@shipping_bp.get('/geocode/<int:order_id>')
@login_required
@limiter.limit('5 per minute')
@handle_db_errors
def geocode(order_id):
    if request.args:
        return _error('Tra cứu chỉ sử dụng địa chỉ đã lưu của đơn hàng.', 400)
    try:
        if session.get('role') == 'admin':
            data = OrderService.get_order_detail(order_id)
        else:
            # Never fetch an unscoped order and compare afterwards; this query
            # applies the real OrderService owner guard before reading items.
            data = OrderService.get_user_order_detail(order_id, session['user_id'])
    except ValidationError:
        return _error('Không tìm thấy đơn hàng.', 404)
    except psycopg2.Error:
        return _error('Dịch vụ dữ liệu tạm thời không khả dụng. Vui lòng thử lại sau.', 503)
    if not data:
        # Foreign IDs and nonexistent orders are deliberately indistinguishable.
        return _error('Không tìm thấy đơn hàng.', 404)
    try:
        point = GeocodeService.geocode(data['order'].ShippingAddress)
    except GeocodeError as error:
        message = GEOCODE_ERROR_MESSAGES.get(
            error.status_code, 'Dịch vụ bản đồ tạm thời không khả dụng. Vui lòng thử lại sau.'
        )
        return _error(message, error.status_code, error.retry_after)
    return jsonify(
        success=True,
        lat=point['lat'],
        lon=point['lon'],
        approximate=True,
        source='shipping_address',
        attribution='© OpenStreetMap contributors',
    )
