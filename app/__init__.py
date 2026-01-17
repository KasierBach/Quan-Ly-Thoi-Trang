from flask import Flask, session, render_template, request, jsonify
from .config import Config
from .database import db
from flask_mail import Mail
from .utils import DecimalEncoder, resolve_image
import os

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    mail = Mail(app)
    app.mail = mail # Store in app for access in routes
    
    # Register JSON encoder
    app.json_encoder = DecimalEncoder
    
    # Register template filters
    app.jinja_env.filters['resolve_image'] = resolve_image

    # Global Context Processors
    @app.context_processor
    def inject_user():
        return dict(
            user_name=session.get('user_name'),
            is_admin=session.get('is_admin'),
            dark_mode=session.get('dark_mode', False)
        )
    
    @app.context_processor
    def inject_cart_count():
        count = 0
        if 'cart' in session:
            count = sum(item['quantity'] for item in session['cart'])
        return dict(cart_count=count)

    # Global Before Request (Backwards compatibility logic)
    @app.before_request
    def before_request_logic():
        # Check admin hardcoded logic from old app.py, moved here for compatibility
        if 'user_id' in session and session.get('is_admin') is None:
             if session['user_id'] == 19:
                 session['is_admin'] = True

    # Register Blueprints
    from .routes.auth import auth_bp
    from .routes.main import main_bp
    from .routes.product import product_bp
    from .routes.cart import cart_bp
    from .routes.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(product_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(admin_bp)

    # 404 Handler
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('404.html'), 404

    return app
