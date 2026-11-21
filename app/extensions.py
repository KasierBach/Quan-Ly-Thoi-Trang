"""Unbound Flask extensions; application factories initialize these objects."""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect


socketio = SocketIO(async_mode='threading')
limiter = Limiter(key_func=get_remote_address)
mail = Mail()
csrf = CSRFProtect()
