from app.database import get_db_connection
from app import create_app
import psycopg2

app = create_app()

def migrate():
    with app.app_context():
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # 1. Check if column exists
            print("Checking if Role column exists...")
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='customers' AND column_name='role';")
            if cursor.fetchone():
                print("Role column already exists.")
            else:
                # 2. Add column
                print("Adding Role column...")
                cursor.execute("ALTER TABLE Customers ADD COLUMN Role VARCHAR(50) DEFAULT 'customer';")
                conn.commit()
                print("Role column added.")

            # 3. Migrate data
            print("Migrating IsAdmin to Role...")
            cursor.execute("UPDATE Customers SET Role = 'admin' WHERE IsAdmin = TRUE;")
            cursor.execute("UPDATE Customers SET Role = 'customer' WHERE Role IS NULL;") # Should be handled by default, but safe to run
            
            # Check count
            cursor.execute("SELECT Role, COUNT(*) FROM Customers GROUP BY Role;")
            results = cursor.fetchall()
            print("Migration stats:")
            for row in results:
                print(f"- {row.Role}: {row.count}")

            conn.commit()
            print("Migration completed successfully.")

        except Exception as e:
            conn.rollback()
            print(f"Migration failed: {e}")
        finally:
            cursor.close()
            conn.close()

if __name__ == "__main__":
    migrate()
