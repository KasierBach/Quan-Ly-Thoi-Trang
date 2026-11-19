"""Additive synthetic seed runner; never imports the app or reads .env files."""

import argparse
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg2


ROOT = Path(__file__).resolve().parents[1]
DATABASE_NAME = 'thua2_main_test'
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}


def test_database_parameters(database_url):
    """Reject remote DBs and libpq query overrides before opening a socket."""
    if not database_url:
        raise ValueError('Pass --database-url or set TEST_DATABASE_URL; .env is not read')
    parsed = urlsplit(database_url)
    if (
        parsed.scheme != 'postgresql'
        or parsed.hostname not in LOOPBACK_HOSTS
        or parsed.path != '/' + DATABASE_NAME
        or parsed.query
        or parsed.fragment
        or not parsed.username
        or parsed.password is None
    ):
        raise ValueError('Seed refuses any URL except an explicit loopback thua2_main_test database')
    return {
        'host': parsed.hostname,
        'port': parsed.port or 5432,
        'dbname': DATABASE_NAME,
        'user': unquote(parsed.username),
        'password': unquote(parsed.password),
        'connect_timeout': 5,
        'application_name': 'thua2-main-test-seed',
    }


def seed_database(database_url):
    parameters = test_database_parameters(database_url)
    connection = psycopg2.connect(**parameters)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_database()')
            if cursor.fetchone()[0] != DATABASE_NAME:
                raise RuntimeError('Connected database is not the disposable test database')
            cursor.execute((ROOT / 'db' / 'bootstrap.sql').read_text(encoding='utf-8'))
            cursor.execute("SELECT set_config('thua2.allow_test_seed', 'loopback-disposable', false)")
            cursor.execute((ROOT / 'db' / 'seed_test.sql').read_text(encoding='utf-8'))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description='Add synthetic fixtures to a disposable local PostgreSQL database')
    parser.add_argument('--database-url', default=os.environ.get('TEST_DATABASE_URL'))
    parser.add_argument(
        '--yes-test-seed', action='store_true', help='Confirm this is the disposable local thua2_main_test database'
    )
    arguments = parser.parse_args()
    if not arguments.yes_test_seed:
        parser.error('--yes-test-seed is required; this runner never resets existing data')
    try:
        seed_database(arguments.database_url)
    except (ValueError, psycopg2.Error, RuntimeError) as error:
        parser.exit(1, f'Seed failed: {error}\n')
    print('Synthetic fixtures ready in thua2_main_test. Accounts: customer/admin/other@example.test; TestUser123!')


if __name__ == '__main__':
    main()
