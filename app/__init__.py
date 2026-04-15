from flask import Flask, session, render_template, request, jsonify
from .config import Config
from .database import db
from flask_mail import Mail
from .utils import DecimalEncoder, resolve_image
from flask_socketio import SocketIO
import os
import json
import flask.json

# Monkey patch for flask-wtf/recaptcha compatibility
flask.json.JSONEncoder = json.JSONEncoder

# Initialize SocketIO
socketio = SocketIO(cors_allowed_origins=os.environ.get('ALLOWED_ORIGINS', 'http://localhost:5000,http://127.0.0.1:5000').split(','), async_mode='threading')

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize Limiter with app
    limiter.init_app(app)
    app.limiter = limiter
    
    # Fix for running behind a proxy (like Render/Heroku)
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    
    # Initialize extensions
    db.init_app(app)
    
    # Initialize DB Pool
    from .database import init_db_pool
    with app.app_context():
        # Wrap in try-except in case of missing config/env during build
        try:
             init_db_pool(app)
        except Exception as e:
             print(f"Warning: Could not initialize DB Pool: {e}")

    mail = Mail(app)
    app.mail = mail # Store in app for access in routes
    
    # Initialize CSRF Protection
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect(app)

    # Initialize SocketIO with app
    socketio.init_app(app)
    app.socketio = socketio

    
    # Register JSON encoder
    import decimal
    from flask.json.provider import DefaultJSONProvider
    
    class CustomJSONProvider(DefaultJSONProvider):
        def default(self, o):
            if isinstance(o, decimal.Decimal):
                return float(o)
            return super().default(o)
            
    app.json = CustomJSONProvider(app)
    
    # Register template filters
    app.jinja_env.filters['resolve_image'] = resolve_image

    # Global Context Processors
    @app.context_processor
    def inject_user():
        return dict(
            user_name=session.get('user_name'),
            is_admin=session.get('is_admin'),
            role=session.get('role'),
            dark_mode=session.get('dark_mode', False)
        )
    
    @app.context_processor
    def inject_cart_count():
        count = 0
        if 'cart' in session:
            count = sum(item['quantity'] for item in session['cart'])
        return dict(cart_count=count)

    # Inject Categories globally (Refactored to Service Layer)
    from app.services.category_service import CategoryService
    @app.context_processor
    def inject_categories():
        return dict(categories=CategoryService.get_all_categories())

    # Global Before Request
    @app.before_request
    def before_request_logic():
        # Place any global before_request logic here if needed
        pass

    # Security Headers Middleware
    @app.after_request
    def add_security_headers(response):
        # Prevent Clickjacking
        response.headers['X-Frame-Options'] = 'DENY'
        # Prevent MIME Sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Strict-Transport-Security (HSTS) - Only in production
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        # Content Security Policy (CSP)
        # Allows self, Google Fonts, and FontAwesome
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://code.jquery.com https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: https://images.pixabay.com https://pixabay.com; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none';"
        )
        response.headers['Content-Security-Policy'] = csp
        return response

    # Register Blueprints
    from .routes.auth import auth_bp
    from .routes.main import main_bp
    from .routes.product import product_bp
    from .routes.cart import cart_bp
    from .routes.admin import admin_bp
    from .routes.chat import chat_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(product_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(chat_bp)

    # 404 Handler
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('404.html'), 404

    # Register Socket Events
    from .sockets import register_socket_events
    register_socket_events(socketio)

    return app
