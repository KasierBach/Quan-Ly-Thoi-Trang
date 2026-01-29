from flask import Flask, session, render_template, request, jsonify
from .config import Config
from .database import db
from flask_mail import Mail
from .utils import DecimalEncoder, resolve_image
import os
import json
import flask.json

# Monkey patch for flask-wtf/recaptcha compatibility
flask.json.JSONEncoder = json.JSONEncoder

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    mail = Mail(app)
    app.mail = mail # Store in app for access in routes
    
    # Initialize CSRF Protection
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect(app)
    
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

    return app
