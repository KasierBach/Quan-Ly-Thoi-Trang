from app import create_app, socketio
import os

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 4000))
    socketio.run(app, debug=True, port=port, host='0.0.0.0')