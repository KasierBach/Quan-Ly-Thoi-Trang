import threading
import time
from typing import Any, Protocol, cast

import psycopg2
from flask import current_app
from psycopg2.extensions import TRANSACTION_STATUS_IDLE, cursor
from psycopg2.pool import PoolError, ThreadedConnectionPool


class DatabaseCursor(Protocol):
    rowcount: int

    def __enter__(self) -> 'DatabaseCursor': ...
    def __exit__(self, *args) -> bool | None: ...
    def execute(self, query, params=None) -> None: ...
    def fetchone(self) -> Any: ...
    def fetchall(self) -> list['CaseInsensitiveRecord']: ...
    def close(self) -> None: ...


class DatabaseConnection(Protocol):
    def cursor(self, *args, **kwargs) -> DatabaseCursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


class CaseInsensitiveRecord(dict):
    """Keep the legacy row attribute API used by the main templates."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(f"Record has no attribute '{name}'") from exc

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        if isinstance(key, str):
            for candidate in self:
                if isinstance(candidate, str) and candidate.casefold() == key.casefold():
                    return dict.__getitem__(self, candidate)
        raise KeyError(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __setattr__(self, name, value):
        self[name] = value


class CaseInsensitiveCursor(cursor):
    def _wrap_row(self, row):
        if row is None:
            return None
        if self.description is None:
            raise psycopg2.ProgrammingError('A result set is required')
        return CaseInsensitiveRecord(zip([column[0] for column in self.description], row, strict=True))

    def fetchone(self):
        return self._wrap_row(super().fetchone())

    def fetchall(self):
        return [self._wrap_row(row) for row in super().fetchall()]

    def fetchmany(self, size=None):
        return [self._wrap_row(row) for row in super().fetchmany(size if size is not None else self.arraysize)]


class PooledConnection:
    def __init__(self, pool, conn):
        self.pool = pool
        self.conn = conn

    def close(self):
        conn, self.conn = self.conn, None
        if conn is None:
            return
        discard = bool(conn.closed)
        try:
            if not discard and conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                conn.rollback()
        except (psycopg2.Error, OSError):
            discard = True
        finally:
            self.pool.putconn(conn, close=discard)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __getattr__(self, name):
        if self.conn is None:
            raise psycopg2.InterfaceError('Connection has already been returned to the pool')
        return getattr(self.conn, name)


def init_db_pool(app):
    app.extensions.setdefault('db_pool_lock', threading.Lock())
    if not app.config.get('DB_POOL_ENABLED', True) or not app.config.get('DB_CONNECT_ENABLED', True):
        return None
    with app.extensions['db_pool_lock']:
        pool = app.extensions.get('db_pool')
        if pool is None:
            pool = ThreadedConnectionPool(
                minconn=app.config.get('DB_POOL_MIN', 1),
                maxconn=app.config.get('DB_POOL_MAX', 10),
                dsn=app.config['DATABASE_URL'],
                connect_timeout=app.config.get('DB_CONNECT_TIMEOUT', 5),
                cursor_factory=CaseInsensitiveCursor,
            )
            app.extensions['db_pool'] = pool
        return pool


def close_db_pool(app):
    pool = app.extensions.pop('db_pool', None)
    if pool is not None:
        pool.closeall()


def acquire_connection(pool, timeout):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return pool.getconn()
        except PoolError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise psycopg2.OperationalError('Database connection capacity is temporarily unavailable') from None
            time.sleep(min(0.02, remaining))


def get_db_connection() -> DatabaseConnection:
    app = current_app
    if not app.config.get('DB_CONNECT_ENABLED', True):
        raise RuntimeError('Database access is disabled in this configuration')
    if not app.config.get('DB_POOL_ENABLED', True):
        return cast(
            DatabaseConnection,
            psycopg2.connect(
                app.config['DATABASE_URL'],
                connect_timeout=app.config.get('DB_CONNECT_TIMEOUT', 5),
                cursor_factory=CaseInsensitiveCursor,
            ),
        )
    pool = init_db_pool(app)
    if pool is None:
        raise RuntimeError('Database pool is not configured')
    for _ in range(3):
        conn = acquire_connection(pool, app.config.get('DB_POOL_WAIT_TIMEOUT', 2))
        if conn.closed:
            pool.putconn(conn, close=True)
            continue
        try:
            if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                conn.rollback()
            with conn.cursor() as cur:
                cur.execute('SELECT 1')
            conn.rollback()
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            pool.putconn(conn, close=True)
            continue
        return cast(DatabaseConnection, PooledConnection(pool, conn))
    raise psycopg2.OperationalError('No healthy connection is available')


def close_db_connection(conn):
    if conn is not None:
        conn.close()
