from run import app
from app.database import get_db_connection
import json

with app.app_context():
    conn = get_db_connection()
    cursor = conn.cursor()

    def get_schema(table_name):
        cursor.execute(f"SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = '{table_name.lower()}'")
        return cursor.fetchall()

    schema = {
        'Messages': get_schema('Messages'),
        'Attachments': get_schema('Attachments')
    }

    print(json.dumps(schema, indent=4))
    conn.close()
