"""Apply the Fashion Store schema and ordered SQL migrations before deployment."""

from contextlib import closing
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg2

from app.config import database_urls


DB_DIRECTORY = Path(__file__).resolve().parents[1] / 'db'


def migration_body(path):
    content = '\n' + path.read_text(encoding='utf-8').strip()
    _, begin, body = content.partition('\nBEGIN;\n')
    if not begin or not body.endswith('\nCOMMIT;'):
        raise ValueError(f'{path.name} must enclose its SQL in BEGIN and COMMIT')
    # Run the SQL and ledger write in the same outer transaction.
    return body.removesuffix('\nCOMMIT;')


def apply_migrations(connection):
    scripts = [
        DB_DIRECTORY / 'bootstrap.sql',
        *sorted((DB_DIRECTORY / 'migrations').glob('[0-9][0-9][0-9][0-9]_*.sql')),
    ]
    applied = []
    with connection, connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('thua2_main_bootstrap'))")
        cursor.execute("""CREATE TABLE IF NOT EXISTS public.thua2_schema_migrations (
            name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute('SELECT name FROM public.thua2_schema_migrations')
        existing = {row[0] for row in cursor.fetchall()}
        for script in scripts:
            if script.name in existing:
                continue
            try:
                cursor.execute(migration_body(script))
                cursor.execute('INSERT INTO public.thua2_schema_migrations (name) VALUES (%s)', (script.name,))
            except psycopg2.Error as error:
                raise RuntimeError(f'{script.name} failed (SQLSTATE {error.pgcode or "unknown"})') from None
            applied.append(script.name)
    return applied


def main():
    run_id = uuid4().hex
    print(f'Migration run_id={run_id}', flush=True)
    try:
        dsn, _ = database_urls(os.environ.get('MIGRATION_DATABASE_URL') or os.environ.get('DATABASE_URL'))
        if not dsn or urlsplit(dsn).scheme != 'postgresql':
            sys.exit('Set MIGRATION_DATABASE_URL or DATABASE_URL to the target PostgreSQL URL.')
        with closing(psycopg2.connect(dsn, connect_timeout=5, application_name='thua2-migrate')) as connection:
            applied = apply_migrations(connection)
    except psycopg2.Error as error:
        sys.exit(f'Database migration failed (SQLSTATE {error.pgcode or "unknown"}).')
    except (OSError, RuntimeError, ValueError) as error:
        sys.exit(f'Database migration failed: {error}')
    print(f'Applied {", ".join(applied)}.' if applied else 'Database schema is up to date.')


if __name__ == '__main__':
    main()
