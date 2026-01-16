import psycopg2
import os
import sys

# Connection string provided by user
DATABASE_URL = "postgresql://postgres.lpashsckbrlnnpnrjtps:0Comrade_Bach69@aws-1-ap-south-1.pooler.supabase.com:6543/postgres"

def run_sql_file(cursor, file_path):
    print(f"Executing {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        sql = f.read()
        try:
            cursor.execute(sql)
            print(f"Successfully executed {file_path}")
        except Exception as e:
            if hasattr(e, 'diag') and e.diag:
                print(f"Error executing {file_path}:")
                print(f"  Primary: {e.diag.message_primary}")
                print(f"  Detail: {e.diag.message_detail}")
                print(f"  Hint: {e.diag.message_hint}")
                print(f"  Context: {e.diag.context}")
            else:
                print(f"Error executing {file_path}: {e}")
            raise

def main():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cursor = conn.cursor()

        print("Connected to Supabase successfully!")

        # 1. Run Schema
        schema_path = os.path.join('data', 'postgresql_schema.sql')
        if os.path.exists(schema_path):
            run_sql_file(cursor, schema_path)
        else:
            print(f"Warning: {schema_path} not found.")

        # 2. Run Data
        data_path = os.path.join('data', 'postgresql_data_full.sql')
        if os.path.exists(data_path):
            run_sql_file(cursor, data_path)
        else:
            print(f"Warning: {data_path} not found.")

        cursor.close()
        conn.close()
        print("\nMigration completed successfully!")

    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
