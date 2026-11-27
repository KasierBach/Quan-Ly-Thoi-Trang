"""CSRF-protected OAuth login and explicit account association endpoints."""

import secrets
import time

import psycopg2
from authlib.integrations.base_client.errors import OAuthError
from flask import Blueprint, current_app, flash, make_response, redirect, render_template, request, session, url_for
from joserfc.errors import JoseError
from requests.exceptions import RequestException

from app.extensions import limiter
from app.routes.auth import establish_session
from app.services.oauth_service import (
    OAuthFailure,
    OAuthService,
    OAuthUnavailable,
    PROVIDERS,
    ProviderRegistry,
)
from app.validation import ValidationError, local_redirect


oauth_bp = Blueprint('oauth', __name__, url_prefix='/oauth')
FLOW_KEY = '_oauth_flow'
REAUTH_KEY = '_oauth_reauth'


def init_oauth(app):
    app.extensions['oauth_providers'] = ProviderRegistry(app)


@oauth_bp.app_context_processor
def oauth_template_context():
    registry = current_app.extensions['oauth_providers']
    data = {'oauth_providers': registry.choices()}
    if request.endpoint != 'auth.my_account':
        return data
    data.update(oauth_identities=[], oauth_links_available=False)
    if not any(item['enabled'] for item in data['oauth_providers']):
        return data
    try:
        data['oauth_identities'] = OAuthService.list_identities(session['user_id'])
        data['oauth_links_available'] = True
    except (psycopg2.Error, RuntimeError):
        # Missing unapplied migration/database is a disabled linking surface,
        # not authority to invent an identity or break password-account pages.
        pass
    return data


@oauth_bp.after_request
def private_oauth_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@oauth_bp.errorhandler(OAuthFailure)
@oauth_bp.errorhandler(ValidationError)
def public_oauth_error(error):
    status = 503 if isinstance(error, OAuthUnavailable) else 400
    message = str(error) if isinstance(error, OAuthFailure) else 'Thông tin xác thực không hợp lệ.'
    return make_response(render_template('partials/oauth_error.html', message=message), status)


@oauth_bp.errorhandler(psycopg2.Error)
@oauth_bp.errorhandler(RequestException)
@oauth_bp.errorhandler(OAuthError)
@oauth_bp.errorhandler(JoseError)
def unavailable_oauth_error(error):
    # Provider response text, URL, codes, subjects and credentials are never logged/echoed.
    return make_response(
        render_template('partials/oauth_error.html', message='Không thể hoàn tất xác thực. Vui lòng thử lại.'), 400
    )


def _registry(provider):
    if provider not in PROVIDERS:
        raise OAuthFailure('Nhà cung cấp đăng nhập không hợp lệ.')
    registry = current_app.extensions['oauth_providers']
    registry.client(provider)
    return registry


def _authenticated_account():
    user_id = session.get('user_id')
    version = session.get('auth_version')
    if type(user_id) is not int or user_id < 1 or type(version) is not int or version < 1:
        raise OAuthFailure('Hãy đăng nhập vào tài khoản của bạn trước khi thay đổi liên kết.')
    return user_id, version


def _check_form_version(version):
    if request.form.get('auth_version') != str(version):
        raise OAuthFailure('Biểu mẫu đã hết hạn. Vui lòng tải lại trang tài khoản.')


def _reauthenticate(user_id, version):
    grant = session.pop(REAUTH_KEY, None)
    if isinstance(grant, dict):
        data = OAuthService.consume_ticket(grant['token'], grant['binding'], 'reauth')
        expected = {'user_id': user_id, 'auth_version': version, 'csrf_token': session.get('csrf_token')}
        if data != expected:
            raise OAuthFailure('Phiên xác thực lại không hợp lệ. Vui lòng thử lại.')
        return
    if OAuthService.reauthenticate_password(user_id, version, request.form.get('current_password')):
        return
    raise OAuthFailure('Cần mật khẩu hiện tại hoặc xác thực lại với Google đã liên kết.')


def _start_flow(provider, intent, user_id=None, version=None, *, next_page=None):
    registry = _registry(provider)
    flow = {
        'state': OAuthService.new_ticket(),
        'binding': OAuthService.new_ticket(),
        'nonce': OAuthService.new_ticket(),
        'provider': provider,
        'intent': intent,
        'user_id': user_id,
        'auth_version': version,
        'csrf_token': session.get('csrf_token'),
        'issued_at': time.time(),
    }
    session[FLOW_KEY] = flow
    try:
        destination = registry.authorize(provider, flow, next_page=next_page)
    except Exception:
        session.pop(FLOW_KEY, None)
        raise
    return redirect(destination)


def _consume_flow(provider):
    flow = session.pop(FLOW_KEY, None)
    state = request.args.get('state')
    if not isinstance(flow, dict):
        raise OAuthFailure('Phiên xác thực không hợp lệ hoặc đã hết hạn. Vui lòng thử lại.')
    # Burn this browser's own ticket even for a mismatched/failed callback.
    # A captured earlier signed cookie must not resurrect an aborted attempt.
    data = OAuthService.consume_ticket(flow['state'], flow['binding'], 'authorization')
    if (
        flow.get('provider') != provider
        or not isinstance(state, str)
        or not state.isascii()
        or len(state) != 43
        or len(request.args.getlist('state')) != 1
        or not secrets.compare_digest(flow.get('state', ''), state)
    ):
        raise OAuthFailure('Phiên xác thực không hợp lệ hoặc đã hết hạn. Vui lòng thử lại.')
    if (
        flow.get('intent') not in {'login', 'link', 'reauth'}
        or flow.get('csrf_token') != session.get('csrf_token')
        or time.time() - flow.get('issued_at', 0) > current_app.config['OAUTH_STATE_TTL']
        or flow.get('user_id') != session.get('user_id')
        or flow.get('auth_version') != session.get('auth_version')
    ):
        raise OAuthFailure('Phiên đăng nhập đã thay đổi. Vui lòng bắt đầu xác thực lại.')
    # Atomic deletion above commits BEFORE any network exchange.
    code = request.args.get('code')
    if request.args.get('error') or len(request.args.getlist('code')) != 1 or not code or len(code) > 2048:
        raise OAuthFailure('Đăng nhập đã bị hủy hoặc nhà cung cấp trả về thông tin không hợp lệ.')
    return flow, data


@oauth_bp.route('/<provider>/login', methods=['POST'])
@limiter.limit('10 per minute')
def login(provider):
    _registry(provider)
    if session.get('user_id'):
        raise OAuthFailure('Bạn đã đăng nhập. Hãy dùng liên kết nhà cung cấp trong trang tài khoản.')
    return _start_flow(provider, 'login', next_page=local_redirect(request.form.get('next')))


@oauth_bp.route('/<provider>/link', methods=['POST'])
@limiter.limit('5 per minute')
def link(provider):
    _registry(provider)
    user_id, version = _authenticated_account()
    _check_form_version(version)
    _reauthenticate(user_id, version)
    return _start_flow(provider, 'link', user_id, version)


@oauth_bp.route('/<provider>/reauth', methods=['POST'])
@limiter.limit('5 per minute')
def reauth(provider):
    _registry(provider)
    user_id, version = _authenticated_account()
    _check_form_version(version)
    if provider != 'google':
        raise OAuthFailure('GitHub không bảo đảm xác thực mới. Hãy dùng mật khẩu hiện tại.')
    session.pop(REAUTH_KEY, None)
    return _start_flow(provider, 'reauth', user_id, version)


@oauth_bp.route('/<provider>/unlink', methods=['POST'])
@limiter.limit('5 per minute')
def unlink(provider):
    _registry(provider)
    user_id, version = _authenticated_account()
    _check_form_version(version)
    _reauthenticate(user_id, version)
    session['auth_version'] = OAuthService.unlink_identity(provider, user_id, version)
    session.pop(FLOW_KEY, None)
    flash('Đã gỡ liên kết nhà cung cấp.', 'success')
    return redirect(url_for('auth.my_account', _anchor='profile'))


@oauth_bp.route('/<provider>/callback', methods=['GET'])
@limiter.limit('20 per minute')
def callback(provider):
    registry = _registry(provider)
    flow, data = _consume_flow(provider)
    next_page = data.pop('next_page', None)
    try:
        identity = registry.exchange(provider, flow, data)
    except (TypeError, KeyError, ValueError, RuntimeError):
        # Malformed provider JSON/claims are authentication failure, never a 500
        # or an HTML echo of upstream error details.
        raise OAuthFailure('Không thể xác minh thông tin từ nhà cung cấp. Vui lòng thử lại.') from None
    if flow['intent'] == 'link':
        session['auth_version'] = OAuthService.link_identity(identity, flow['user_id'], flow['auth_version'])
        flash('Đã liên kết nhà cung cấp với tài khoản của bạn.', 'success')
        return redirect(url_for('auth.my_account', _anchor='profile'))
    if flow['intent'] == 'reauth':
        OAuthService.reauthenticate_identity(identity, flow['user_id'], flow['auth_version'])
        grant = {'token': OAuthService.new_ticket(), 'binding': OAuthService.new_ticket()}
        data = {'user_id': flow['user_id'], 'auth_version': flow['auth_version'], 'csrf_token': flow['csrf_token']}
        OAuthService.issue_ticket(
            grant['token'], grant['binding'], 'reauth', data, current_app.config['OAUTH_REAUTH_TTL']
        )
        session[REAUTH_KEY] = grant
        flash('Đã xác thực lại. Hãy xác nhận biểu mẫu liên kết hoặc gỡ liên kết trong 5 phút.', 'success')
        return redirect(url_for('auth.my_account', _anchor='profile'))
    user = OAuthService.login_or_register(identity)
    establish_session(user.CustomerID, user.FullName, user.Role, user.AuthVersion, user.DarkModeEnabled)
    flash('Đăng nhập thành công!', 'success')
    return redirect(next_page or url_for('admin.admin_dashboard' if user.Role == 'admin' else 'main.home'))
