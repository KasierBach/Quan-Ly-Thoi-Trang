import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')
# New hash for password '123456'
NEW_HASH = 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3'

try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("UPDATE Customers SET Password = %s WHERE Email = 'admin123@gmail.com';", (NEW_HASH,))
    conn.commit()
    print("Admin password has been reset successfully!")
    cur.close()
    conn.close()
except Exception as e:
    print(f"Error updating password: {e}")
