import psycopg2
import os
from dotenv import load_dotenv

def update_db(db_url, name):
    print(f"Updating {name} DB...")
    try:
        conn = psycopg2.connect(db_url.replace('postgres://', 'postgresql://', 1))
        cur = conn.cursor()
        
        updates = [
            (34, 'images/34.png'),
            (38, 'images/38.png'),
            (36, 'images/36.png'),
            (37, 'images/37.png')
        ]
        
        for pid, img in updates:
            cur.execute("UPDATE Products SET ImageURL = %s WHERE ProductID = %s", (img, pid))
            print(f"  Updated ProductID {pid} -> {img}")
            
        conn.commit()
        cur.close()
        conn.close()
        print(f"Successfully updated {name} DB.")
    except Exception as e:
        print(f"Error updating {name} DB: {e}")

def main():
    load_dotenv()
    
    # Update Local
    local_url = os.environ.get('DATABASE_URL')
    if local_url:
        update_db(local_url, "Local")
    
    # Update Supabase
    # Getting Supabase URL from the script migrate_to_supabase.py since it's hardcoded there
    supabase_url = "postgresql://postgres.lpashsckbrlnnpnrjtps:0Comrade_Bach69@aws-1-ap-south-1.pooler.supabase.com:6543/postgres"
    update_db(supabase_url, "Supabase")

if __name__ == "__main__":
    main()
