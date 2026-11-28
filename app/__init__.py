import decimal
import re

import psycopg2
from flask import Flask, abort, jsonify, render_template, request, send_from_directory, session, url_for
from flask.json.provider import DefaultJSONProvider
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config, database_urls, validate_config
from .database import db, init_db_pool
from .extensions import csrf, limiter, mail, socketio
from .formatting import format_money
from .uploads import upload_root
from .utils import resolve_image


class CustomJSONProvider(DefaultJSONProvider):
    def default(self, value):
        if isinstance(value, decimal.Decimal):
            return str(value)
        return super().default(value)


def create_app(config_class=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_class is None:
        app.config.update(Config.from_environment())
    elif isinstance(config_class, dict):
        app.config.update(config_class)
    else:
        app.config.from_object(config_class)
    if not app.config.get('DATABASE_URL'):
        raw_url, orm_url = database_urls(app.config.get('SQLALCHEMY_DATABASE_URI'))
        app.config['DATABASE_URL'] = raw_url
        app.config['SQLALCHEMY_DATABASE_URI'] = orm_url
    validate_config(app.config)
    app.json = CustomJSONProvider(app)

    from .http_assets import init_http_assets

    # after_request runs in reverse: private/security hooks must run first.
    init_http_assets(app)

    proxy_count = app.config.get('TRUSTED_PROXY_COUNT', 0)
    if proxy_count:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_count, x_proto=proxy_count, x_host=proxy_count)
    db.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    socket_options = {}
    if app.config.get('SOCKETIO_MESSAGE_QUEUE'):
        socket_options['message_queue'] = app.config['SOCKETIO_MESSAGE_QUEUE']
    if app.config.get('ALLOWED_ORIGINS') is not None:
        socket_options['cors_allowed_origins'] = app.config['ALLOWED_ORIGINS']
    socketio.init_app(app, **socket_options)
    init_db_pool(app)

    app.jinja_env.filters['resolve_image'] = resolve_image
    app.jinja_env.filters['money'] = format_money

    @app.template_filter('image_url')
    def image_url_filter(obj):
        path = resolve_image(obj)
        if path and path.startswith(('http://', 'https://')):
            return path
        return url_for('static', filename=path or 'images/default.jpg')

    @app.context_processor
    def inject_user():
        return {
            'user_name': session.get('user_name'),
            'is_admin': session.get('role') == 'admin',
            'role': session.get('role'),
            'dark_mode': session.get('dark_mode', False),
            'contact_details': {
                'email': app.config.get('CONTACT_EMAIL'),
                'phone': app.config.get('CONTACT_PHONE'),
                'address': app.config.get('CONTACT_ADDRESS'),
            },
        }

    @app.context_processor
    def inject_cart_count():
        from app.services.cart_service import CartService

        cart = session.get('cart', [])
        if app.config.get('DB_CONNECT_ENABLED', True) and session.get('cart_id'):
            try:
                saved = CartService.load(session['cart_id'])
                if saved is not None:
                    cart = saved[1]
            except psycopg2.Error:
                app.logger.warning('Cart count unavailable')
        return {'cart_count': sum(item.get('quantity', 0) for item in cart if isinstance(item, dict))}

    @app.context_processor
    def inject_categories():
        if not app.config.get('DB_CONNECT_ENABLED', True):
            return {'categories': []}
        from app.services.category_service import CategoryService

        return {'categories': CategoryService.get_all_categories()}

    @app.before_request
    def static_uploads():
        if request.endpoint == 'static':
            filename = (request.view_args or {}).get('filename', '').replace('\\', '/')
            if filename.startswith('uploads/chat/'):
                abort(404)
            if re.fullmatch(r'images/pixabay-[1-9][0-9]*-[0-9a-f]{32}\.jpg', filename):
                # Keep URLs already stored on products and fall back to legacy static files.
                directory = upload_root() / 'products'
                image = directory / filename.removeprefix('images/')
                if image.is_file() and not directory.is_symlink() and not image.is_symlink():
                    return send_from_directory(directory, image.name, mimetype='image/jpeg')
        return None

    @app.before_request
    def revalidate_session():
        if not session.get('user_id') or not app.config.get('SESSION_REVALIDATION_ENABLED', True):
            return None
        if request.endpoint in {'static', 'main.health_live', 'main.robots_txt', 'main.sitemap_xml'}:
            return None
        from app.services.auth_service import AuthService

        state = AuthService.get_identity_state(session['user_id'])
        if state is None or state.AuthVersion != session.get('auth_version'):
            cart = {key: session[key] for key in ('cart_id', 'cart', 'cart_revision') if key in session}
            session.clear()
            session.update(cart)
            return None
        identity = {
            'user_name': state.FullName,
            'role': state.Role,
            'is_admin': state.Role == 'admin',
            'dark_mode': state.DarkModeEnabled,
        }
        for key, value in identity.items():
            if session.get(key) != value:
                session[key] = value
        return None

    @app.before_request
    def initialize_page_chat():
        page_endpoints = {
            'main.home',
            'main.contact',
            'auth.login',
            'auth.register',
            'auth.my_account',
            'auth.forgot_password',
            'auth.reset_password',
            'product.products',
            'product.product_detail',
            'product.view_wishlist',
            'cart.view_cart',
            'cart.checkout',
            'cart.order_detail',
            'cart.order_confirmation',
            'chat.messages_page',
        }
        if request.method == 'GET' and request.endpoint in page_endpoints:
            from app.services.cart_service import ensure_cart_id
            from app.services.conversation_service import issue_guest_credentials

            ensure_cart_id()
            issue_guest_credentials()
        return None

    @app.after_request
    def add_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers.setdefault('Referrer-Policy', 'same-origin')
        response.headers['Permissions-Policy'] = 'camera=(self), microphone=(self), display-capture=(self)'
        if app.config.get('APP_ENV') == 'production':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers.setdefault(
            'Content-Security-Policy',
            (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; "
                "img-src 'self' data: https:; media-src 'self' blob:; "
                "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
                # OAuth start forms redirect (302) to the provider's authorize page and the
                # browser enforces form-action on redirect targets, so the two supported
                # provider hosts must be listed here or the navigation is blocked client-side.
                "form-action 'self' https://accounts.google.com https://github.com"
            ),
        )
        if request.endpoint != 'static' and (session.get('user_id') or request.path.startswith('/api/')):
            response.headers['Cache-Control'] = 'no-store'
        return response

    from .routes.admin import admin_bp
    from .routes.auth import auth_bp
    from .routes.cart import cart_bp
    from .routes.chat import chat_bp
    from .routes.main import main_bp
    from .routes.oauth import init_oauth, oauth_bp
    from .routes.product import product_bp
    from .routes.shipping import shipping_bp

    init_oauth(app)
    for blueprint in (auth_bp, main_bp, product_bp, cart_bp, admin_bp, chat_bp, oauth_bp, shipping_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        from app.decorators import api_request

        if api_request():
            return jsonify(success=False, message='Phiên biểu mẫu đã hết hạn. Vui lòng tải lại trang.'), 400
        return 'Phiên biểu mẫu đã hết hạn. Vui lòng tải lại trang.', 400

    @app.errorhandler(404)
    def page_not_found(error):
        if request.path.startswith('/api/'):
            return jsonify(success=False, message='Không tìm thấy dữ liệu'), 404
        return render_template('404.html'), 404

    @app.errorhandler(HTTPException)
    def http_error(error):
        from app.decorators import api_request

        if api_request():
            return jsonify(success=False, message=error.name), error.code
        return error

    @app.errorhandler(500)
    def server_error(error):
        return jsonify(success=False, message='Đã xảy ra lỗi hệ thống'), 500

    from .sockets import register_socket_events

    register_socket_events(socketio, app)
    return app
