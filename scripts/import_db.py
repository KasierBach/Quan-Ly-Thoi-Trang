import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import os
from dotenv import load_dotenv
import time

load_dotenv()

def import_sql():
    # Lấy thông tin từ .env
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("Lỗi: Không tìm thấy DATABASE_URL trong file .env")
        return

    # Tách thông tin để kết nối tới database hệ thống (postgres) để tạo DB mới
    # postgresql://user:pass@host:port/dbname
    base_url = db_url.rsplit('/', 1)[0] + '/postgres'
    db_name = db_url.rsplit('/', 1)[1]

    conn = None
    try:
        # 1. Kết nối để tạo Database
        print(f"--- Đang kết nối tới server PostgreSQL để tạo database '{db_name}' ---")
        conn = psycopg2.connect(base_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        
        # Kiểm tra xem database đã tồn tại chưa
        cur.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{db_name}'")
        exists = cur.fetchone()
        if not exists:
            cur.execute(f'CREATE DATABASE "{db_name}"')
            print(f"Đã tạo thành công database '{db_name}'.")
        else:
            print(f"Database '{db_name}' đã tồn tại.")
        
        cur.close()
        conn.close()

        # 2. Kết nối tới database mới để chạy script
        print(f"--- Đang kết nối tới '{db_name}' để import dữ liệu ---")
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        # Chạy Schema
        schema_file = 'postgresql_schema.sql'
        if os.path.exists(schema_file):
            print(f"Đang chạy {schema_file}...")
            with open(schema_file, 'r', encoding='utf-8') as f:
                cur.execute(f.read())
            conn.commit()
            print("Import Schema thành công.")
        else:
            print(f"Lỗi: Không tìm thấy file {schema_file}")

        # Chạy Data
        data_file = 'postgresql_data.sql'
        if os.path.exists(data_file):
            print(f"Đang chạy {data_file}...")
            # Đọc file data và thực thi từng khối nếu cần, hoặc thực thi toàn bộ
            with open(data_file, 'r', encoding='utf-8') as f:
                cur.execute(f.read())
            conn.commit()
            print("Import Dữ liệu mẫu thành công.")
        else:
            print(f"Lỗi: Không tìm thấy file {data_file}")

        print("\n--- HOÀN THÀNH ---")
        print("Bây giờ bạn có thể chạy: python app.py")

    except Exception as e:
        print(f"Lỗi xảy ra: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    import_sql()
