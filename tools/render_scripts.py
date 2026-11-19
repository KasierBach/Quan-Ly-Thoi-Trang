import argparse
import json
from pathlib import Path
import sys

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.path.insert(0, str(ROOT))
    from app import create_app
    from app.database import close_db_pool
    from tools.seed_test import test_database_parameters

    parser = argparse.ArgumentParser(
        description='Render main scripts for syntax/lint review using the local disposable database only'
    )
    parser.add_argument('--database-url', required=True)
    args = parser.parse_args()
    test_database_parameters(args.database_url)
    application = create_app(
        {
            'TESTING': True,
            'APP_ENV': 'testing',
            'SECRET_KEY': 'rendered-script-test-secret-not-production-2026',
            'DATABASE_URL': args.database_url,
            'SQLALCHEMY_DATABASE_URI': args.database_url.replace('postgresql://', 'postgresql+psycopg2://'),
            'DB_CONNECT_ENABLED': True,
            'DB_POOL_ENABLED': True,
            'SESSION_REVALIDATION_ENABLED': True,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'SESSION_COOKIE_SECURE': False,
            'MAIL_SUPPRESS_SEND': True,
            'MAIL_USE_TLS': False,
            'MAIL_USE_SSL': False,
        }
    )
    destination = ROOT / 'artifacts' / 'rendered-scripts'
    destination.mkdir(parents=True, exist_ok=True)
    clients = {}
    for name, uid, role in [('guest', None, None), ('customer', 1, 'customer'), ('admin', 2, 'admin')]:
        client = application.test_client()
        if uid is not None:
            with client.session_transaction() as session:
                session.update(user_id=uid, role=role, is_admin=role == 'admin', user_name=name, auth_version=1)
                session['cart'] = [{'variant_id': 1, 'quantity': 1}]
        clients[name] = client
    paths = {
        'guest': ['/', '/login', '/register', '/contact', '/products', '/product/1', '/cart'],
        'customer': ['/my_account', '/wishlist', '/checkout', '/order/1', '/order_confirmation/1', '/messages'],
        'admin': [
            '/admin',
            '/admin/products',
            '/admin/products/edit/1',
            '/admin/orders',
            '/admin/orders/1',
            '/admin/customers',
            '/admin/customers/1',
            '/admin/comments',
            '/admin/contact_messages',
            '/admin/reports?start_date=2026-04-01&end_date=2026-04-30',
            '/admin/attributes',
        ],
    }
    manifest = []
    try:
        for actor, routes in paths.items():
            for number, path in enumerate(routes):
                response = clients[actor].get(path)
                manifest.append({'actor': actor, 'path': path, 'status': response.status_code})
                if response.status_code != 200:
                    continue
                soup = BeautifulSoup(response.data, 'html.parser')
                for index, script in enumerate(soup.find_all('script')):
                    if script.get('src') or script.get('type', '') in {'application/json', 'text/template'}:
                        continue
                    extension = 'mjs' if script.get('type') == 'module' else 'js'
                    (destination / f'{actor}-{number}-{index}.{extension}').write_text(
                        script.get_text(), encoding='utf-8'
                    )
        (ROOT / 'artifacts' / 'rendered-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    finally:
        close_db_pool(application)
    print(f'Rendered scripts and manifest in {destination}')


if __name__ == '__main__':
    main()
