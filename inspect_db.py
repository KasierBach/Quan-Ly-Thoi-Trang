from app.database import get_db_connection
from app import create_app

app = create_app()

with app.app_context():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'customers';")
    columns = cursor.fetchall()
    print("Columns in Customers table:")
    for col in columns:
        print(f"- {col.column_name}: {col.data_type}")
    conn.close()
