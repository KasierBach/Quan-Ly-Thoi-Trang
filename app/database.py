import psycopg2
from psycopg2.extras import NamedTupleCursor
import psycopg2.extensions
from flask_sqlalchemy import SQLAlchemy
from flask import current_app

db = SQLAlchemy()

class CaseInsensitiveRecord(dict):
    """Mô phỏng row object của pyodbc/mssql: cho phép truy cập key bất kể hoa thường qua attribute hoặc key access."""
    def __getattr__(self, name):
        try:
            return self.__getitem__(name)
        except KeyError:
            raise AttributeError(f"Record has no attribute '{name}'")
    
    def __getitem__(self, key):
        if isinstance(key, int):
            # Lấy giá trị theo index nếu key là số nguyên
            return list(self.values())[key]
            
        if key in self:
            return super().__getitem__(key)
        
        if isinstance(key, str):
            lkey = key.lower()
            if lkey in self:
                return super().__getitem__(lkey)
                
            for k in self:
                if isinstance(k, str) and k.lower() == lkey:
                    return super().__getitem__(k)
        
        raise KeyError(key)

    def get(self, key, default=None):
        try:
            return self.__getitem__(key)
        except KeyError:
            return default

    def __setattr__(self, name, value):
        self[name] = value

class CaseInsensitiveCursor(psycopg2.extensions.cursor):
    def _wrap_row(self, row):
        if row is None: return None
        # Tạo record từ mô tả cột và giá trị dòng
        return CaseInsensitiveRecord(zip([d[0] for d in self.description], row))

    def fetchone(self):
        return self._wrap_row(super().fetchone())

    def fetchall(self):
        rows = super().fetchall()
        return [self._wrap_row(r) for r in rows]

    def fetchmany(self, size=None):
        rows = super().fetchmany(size if size is not None else self.arraysize)
        return [self._wrap_row(r) for r in rows]

from psycopg2.pool import ThreadedConnectionPool

# Global pool variable
db_pool = None

class PooledConnection:
    def __init__(self, pool, conn):
        self.pool = pool
        self.conn = conn
    
    def close(self):
        """Override close to return connection to pool instead of closing TCP"""
        if self.pool and self.conn:
            self.pool.putconn(self.conn)
            self.conn = None

    def commit(self):
        return self.conn.commit()

    def rollback(self):
        return self.conn.rollback()

    def cursor(self, *args, **kwargs):
        return self.conn.cursor(*args, **kwargs)

    def __getattr__(self, name):
        """Delegate other attributes to real connection"""
        return getattr(self.conn, name)

def init_db_pool(app):
    global db_pool
    if not db_pool:
        db_pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=10, # Conservative limit for Supabase free tier
            dsn=app.config['SQLALCHEMY_DATABASE_URI'],
            cursor_factory=CaseInsensitiveCursor
        )

def get_db_connection():
    global db_pool
    if not db_pool:
         # Lazy init fallback or script usage
         conn = psycopg2.connect(current_app.config['SQLALCHEMY_DATABASE_URI'], cursor_factory=CaseInsensitiveCursor)
         return conn
         
    real_conn = db_pool.getconn()
    return PooledConnection(db_pool, real_conn)

def close_db_connection(conn):
    # Backward compatibility helper
    conn.close()
