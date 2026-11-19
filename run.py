import os

from app import create_app, socketio
from app.config import env_bool

app = create_app()

if __name__ == '__main__':
    socketio.run(
        app,
        host=os.environ.get('HOST', '127.0.0.1'),
        port=int(os.environ.get('PORT', '4000')),
        debug=env_bool('APP_DEBUG', False),
        allow_unsafe_werkzeug=app.config.get('APP_ENV') == 'development',
    )
