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

# Hàm kết nối trực tiếp đến PostgreSQL
def get_db_connection():
    # Use current_app to access config instead of global variable
    conn = psycopg2.connect(current_app.config['SQLALCHEMY_DATABASE_URI'], cursor_factory=CaseInsensitiveCursor)
    return conn
