import argparse
import os
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from app import create_app, socketio
    from tools.seed_test import test_database_parameters

    parser = argparse.ArgumentParser(description='Serve main against the disposable localhost test database only')
    parser.add_argument('--port', type=int, default=4010)
    args = parser.parse_args()
    dsn = os.environ.get('TEST_DATABASE_URL')
    test_database_parameters(dsn)
    application = create_app(
        {
            'APP_ENV': 'development',
            'TESTING': False,
            'SECRET_KEY': 'synthetic-main-smoke-secret-not-a-production-secret-2026',
            'DATABASE_URL': dsn,
            'SQLALCHEMY_DATABASE_URI': dsn.replace('postgresql://', 'postgresql+psycopg2://'),
            'DB_POOL_ENABLED': True,
            'DB_CONNECT_ENABLED': True,
            'SESSION_REVALIDATION_ENABLED': True,
            'WTF_CSRF_ENABLED': True,
            'SESSION_COOKIE_SECURE': False,
            'TRUSTED_HOSTS': ['localhost', '127.0.0.1'],
            'MAIL_SUPPRESS_SEND': True,
            'MAIL_DEFAULT_SENDER': 'test-store@example.test',
            'MAIL_USE_SSL': False,
            'MAIL_USE_TLS': False,
            'RATELIMIT_ENABLED': False,
            'PIXABAY_API_KEY': None,
            'UPLOAD_ROOT': str(root / 'artifacts' / 'test-uploads'),
        }
    )
    socketio.run(
        application, host='127.0.0.1', port=args.port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True
    )


if __name__ == '__main__':
    main()
