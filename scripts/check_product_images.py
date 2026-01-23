
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import unicodedata
import re

# Load environment variables
load_dotenv()

# Slugify function to match utils.py
def slugify(text):
    if not text:
        return ''
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '-', text)

def check_images():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("DATABASE_URL not found in .env")
        return

    try:
        conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        # Check available tables first
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        tables = [t['table_name'] for t in cur.fetchall()]
        print(f"Available tables: {tables}")
        
        product_table = 'Products'
        if 'products' in tables:
            product_table = 'products'
        elif 'Products' in tables:
            product_table = '"Products"' # Quotient required if mixed case in list but usually matches exact
        
        # Try to guess case
        actual_table = next((t for t in tables if t.lower() == 'products'), None)
        if actual_table:
             print(f"Using table: {actual_table}")
             cur.execute(f"SELECT * FROM \"{actual_table}\"") 
        else:
             print("Could not find Products table")
             cur.close()
             return
        products = cur.fetchall()
        
        if products:
             print("First row keys:", products[0].keys())

        image_dir = r"d:\SQL\dbmstestfileshit\thua 2.0\app\static\images"
        extensions = ['.jpg', '.png', '.jpeg']
        
        missing_images = []
        target_ids = [23, 26]
        target_info = {}

        print(f"Checking {len(products)} products...")
        
        for p in products:
            p_id = p['productid']
            p_name = p['productname']
            
            # Check for image by ID
            found = False
            for ext in extensions:
                 if os.path.exists(os.path.join(image_dir, f"{p_id}{ext}")):
                     found = True
                     break
            
            # Check for image by Slug
            if not found and p_name:
                slug = slugify(p_name)
                for ext in extensions:
                    if os.path.exists(os.path.join(image_dir, f"{slug}{ext}")):
                        found = True
                        break
            
            # Check specific Image URL if in DB
            if not found and p.get('imageurl'):
                 # Assuming ImageURL might be a filename or full path
                 # logic in utils.py suggests it returns it directly if present. 
                 # We check if it exists in static/images if it looks like a filename
                 img_url = p['imageurl']
                 if '/' not in img_url and os.path.exists(os.path.join(image_dir, img_url)):
                     found = True
            
            if not found:
                missing_images.append(f"ID: {p_id} | Name: {p_name}")
                if p_id in target_ids:
                    target_info[p_id] = p

            # Capture target info even if found (just in case we want to overwrite/verify)
            # Actually user asked to create for missing ones.
            if p_id in target_ids and p_id not in target_info:
                 target_info[p_id] = p

        print("\n--- Missing Images ---")
        print("\n--- Verification Result ---")
        if missing_images:
            print(f"FAILED: Found {len(missing_images)} missing images:")
            for item in missing_images:
                print(item)
        else:
            print("SUCCESS: All products have images!")
            
        # Removed verbose Target Info print
        cur.close()
        conn.close()

        cur.close()
        conn.close()

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_images()
