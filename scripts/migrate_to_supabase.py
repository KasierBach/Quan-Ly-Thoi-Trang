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

        # 1.5. Clear existing data to avoid duplicates
        print("Clearing existing data...")
        tables = [
            'OrderDetails', 'Orders', 'ProductVariants', 'Products', 
            'Categories', 'Customers', 'Colors', 'Sizes', 'Wishlist', 
            'Reviews', 'ContactMessages', 'NewsletterSubscribers', 
            'ProductComments', 'PasswordResetTokens'
        ]
        for table in tables:
             # Use CASCADE to handle FKs
             try:
                 cursor.execute(f"TRUNCATE TABLE {table} CASCADE;")
             except psycopg2.errors.UndefinedTable:
                 pass # Table might not exist yet
                 
        print("Data cleared.")

        # 2. Run Data
        data_path = os.path.join('data', 'postgresql_data_full.sql')
        if os.path.exists(data_path):
            run_sql_file(cursor, data_path)
        else:
            print(f"Warning: {data_path} not found.")

        # 3. Apply RBAC Migration (Role column)
        print("Applying RBAC Migration...")
        # Check if Role column exists to avoid error if re-running
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='customers' AND column_name='role';")
        if not cursor.fetchone():
            print("Adding Role column...")
            cursor.execute("ALTER TABLE Customers ADD COLUMN Role VARCHAR(50) DEFAULT 'customer';")
            cursor.execute("UPDATE Customers SET Role = 'admin' WHERE IsAdmin = TRUE;")
            print("RBAC Migration applied.")
        else:
            print("Role column already exists. Skipping.")

        cursor.close()
        conn.close()
        print("\nMigration completed successfully!")

    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
