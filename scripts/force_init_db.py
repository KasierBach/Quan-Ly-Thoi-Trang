
import psycopg2
import os

try:
    conn = psycopg2.connect("postgresql://postgres:123@localhost:5432/FashionStoreDB")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            sender_type VARCHAR(50) NOT NULL,
            content TEXT NOT NULL,
            session_id VARCHAR(255),
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read BOOLEAN DEFAULT FALSE
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
    """)
    conn.commit()
    print("Table messages created successfully (direct connection).")
    cur.close()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
