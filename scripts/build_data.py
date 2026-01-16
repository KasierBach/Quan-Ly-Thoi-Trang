import re
import os

def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def convert_tsql_insert(line):
    # Remove N' prefix for unicode strings
    line = re.sub(r"N'([^']*)'", r"'\1'", line)
    
    # Convert DATEADD/GETDATE
    # DATEADD(DAY, -5, GETDATE()) -> CURRENT_TIMESTAMP - INTERVAL '5 days'
    # Handle the specific pattern in the SQL file
    # Pattern: DATEADD(DAY, -(\d+), GETDATE())
    line = re.sub(r"DATEADD\(DAY,\s*-(\d+),\s*GETDATE\(\)\)", r"CURRENT_TIMESTAMP - INTERVAL '\1 days'", line)
    
    # Handle GETDATE() -> CURRENT_TIMESTAMP
    line = line.replace("GETDATE()", "CURRENT_TIMESTAMP")
    
    # Handle explicit dates 'YYYY-MM-DD HH:MM:SS' (no change needed usually)
    
    # Convert BIT (1/0) to BOOLEAN (TRUE/FALSE) at the end of values
    # Specific for NewsletterSubscribers (IsActive) and ProductComments (IsVisible) which are last columns
    line = re.sub(r",\s*1\s*\)", ", TRUE)", line)
    line = re.sub(r",\s*0\s*\)", ", FALSE)", line)
    line = re.sub(r",\s*1\s*\),", ", TRUE),", line)
    line = re.sub(r",\s*0\s*\),", ", FALSE),", line)
    
    return line

def main():
    base_dir = r"d:\SQL\dbmstestfileshit\thua 2.0"
    data_dir = os.path.join(base_dir, "data")
    
    # Read source files
    pg_data = read_file(os.path.join(data_dir, "postgresql_data.sql"))
    tsql_extra = read_file(os.path.join(data_dir, "Thêm_Bảng_QLTT.sql"))
    
    output_lines = []
    
    # 1. Header and Basic Data (Categories, Colors, Sizes, Products, Variants) from postgresql_data.sql
    # we want to keep the TRUNCATE and the basic inserts, but STOP before Customers/Reviews if we want to customize them
    # Actually postgresql_data.sql is well structured. 
    # Let's take specific sections from postgresql_data.sql
    
    # Extract headers and cleanup
    output_lines.append("-- AUTOMATICALLY GENERATED FROM SQL SERVER DATA MIGRATION")
    output_lines.append("TRUNCATE TABLE OrderDetails, Orders, ProductVariants, ProductComments, Reviews, Wishlist, Products, Categories, Colors, Sizes, Customers, NewsletterSubscribers, PasswordResetTokens RESTART IDENTITY CASCADE;")
    
    # Extract Categories, Colors, Sizes, Products from postgresql_data.sql
    # define sections by comments
    sections = {
        "Categories": (r"-- 1\. Categories", r"-- 2\. Colors"),
        "Colors": (r"-- 2\. Colors", r"-- 3\. Sizes"),
        "Sizes": (r"-- 3\. Sizes", r"-- 4\. Customers"),
        # We will handle Customers manually to add more
        "Customers_Base": (r"-- 4\. Customers", r"-- 5\. Products"),
        "Products": (r"-- 5\. Products", r"-- 6\. Product Variants"), # Note: regex needs to match exact heading
        # Wait, the file has "-- 5. Products", "-- 6. ProductVariants"
        "Variants": (r"-- 6\. ProductVariants", r"-- 7\. Reviews")
    }
    
    # Helper to extract block
    def extract_block(text, start_pat, end_pat):
        start = re.search(start_pat, text)
        if not start: return ""
        end = re.search(end_pat, text)
        if not end: return text[start.start():]
        return text[start.start():end.start()]

    # Categories, Colors, Sizes
    output_lines.append(extract_block(pg_data, r"-- 1\. Categories", r"-- 4\. Customers"))
    
    # Customers: Take the base ones, add 12-20
    base_customers = extract_block(pg_data, r"-- 4\. Customers", r"-- 5\. Products")
    # Remove the last semicolon to append more
    base_customers = base_customers.strip()
    if base_customers.endswith(';'):
        base_customers = base_customers[:-1] + "," # Replace ; with ,
    
    output_lines.append(base_customers)
    
    # Add Customers 12-20 (Dummy data to satisfy FKs)
    # Using same password hash as others
    password_hash = "'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a'"
    extra_customers = []
    for i in range(12, 21):
        extra_customers.append(f"({i}, 'Customer {i}', 'customer{i}@example.com', {password_hash}, '09000000{i}', 'Address {i}', FALSE, CURRENT_TIMESTAMP)")
    
    output_lines.append(",\n".join(extra_customers) + ";\n")
    
    # Products & Variants
    output_lines.append(extract_block(pg_data, r"-- 5\. Products", r"-- 7\. Reviews"))
    
    # 2. Extract Data from Thêm_Bảng_QLTT.sql
    # We want: Reviews, Wishlist, ContactMessages, NewsletterSubscribers, ProductComments
    
    # Parse Thêm_Bảng_QLTT.sql for INSERT statements
    tsql_lines = tsql_extra.splitlines()
    
    reviews = []
    wishlist = []
    messages = []
    subscribers = []
    comments = []
    
    # Simple state machine or just grep inserts
    current_table = None
    
    # Regex for insert start
    # INSERT INTO Table (...)
    insert_pattern = re.compile(r"INSERT INTO (\w+)", re.IGNORECASE)
    
    # We will just collect all INSERT lines and convert them
    # But we want to group them by table for cleanliness
    
    active_inserts = {
        "Reviews": [],
        "Wishlist": [],
        "ContactMessages": [],
        "NewsletterSubscribers": [],
        "ProductComments": []
    }
    
    # Iterate through the file
    # Since INSERTs can span multiple lines (VALUES ...), we need to be careful.
    # But usually in these files they are either one-liners or blocked.
    # Let's just process the whole file content, find insert blocks, and convert.
    
    # Converting the specific blocks we identified
    
    def extract_inserts_for_table(text, table_name):
        # Find all "INSERT INTO table_name ... ;"
        matches = []
        # Case insensitive find
        # We need a regex that captures the whole statement until the checking semicolon
        # Be careful with semicolons in strings, but for this file it's likely fine
        pattern = re.compile(f"INSERT INTO {table_name}.*?;", re.DOTALL | re.IGNORECASE)
        matches = pattern.findall(text)
        return matches

    extra_sql_blocks = []
    
    conflict_clauses = {
        "Reviews": "ON CONFLICT (CustomerID, ProductID) DO NOTHING",
        "Wishlist": "ON CONFLICT (CustomerID, ProductID) DO NOTHING",
        "NewsletterSubscribers": "ON CONFLICT (Email) DO NOTHING",
        "Customers": "ON CONFLICT (Email) DO NOTHING",  # if applicable
        "ProductComments": "" # No unique constraint usually
    }
    
    for table in ["Reviews", "Wishlist", "ContactMessages", "NewsletterSubscribers", "ProductComments"]:
        inserts = extract_inserts_for_table(tsql_extra, table)
        if inserts:
            extra_sql_blocks.append(f"-- {table} from SQL Server")
            for stmt in inserts:
                converted = convert_tsql_insert(stmt)
                # Add conflict clause if needed
                if table in conflict_clauses and conflict_clauses[table]:
                    clause = conflict_clauses[table]
                    # Replace last semicolon
                    if converted.strip().endswith(';'):
                        converted = converted.strip()[:-1] + f" {clause};"
                extra_sql_blocks.append(converted)
    
    output_lines.extend(extra_sql_blocks)
    
    # 3. Add Orders from Quản_Lý_Thời_Trang.sql?
    # Converting EXEC sp_CreateOrder is hard without logic.
    # Let's just Add some dummy orders or skip them. 
    # With the rich Comments/Reviews, orders aren't strictly necessary for the "Reports" view unless we want revenue data.
    # Wait, the User LOVES the "Reports" page (we just fixed it). Reports rely on REVENUE (Orders).
    # If I truncate Orders and don't add any back, the Reports will be EMPTY.
    # `postgresql_data.sql` DOES NOT HAVE ORDERS! (It truncates them and adds none).
    # This is a critical miss. The previous `create_sample_data.py` generated random orders.
    # I MUST generate orders if I want the reports to work.
    
    # Strategy: Use `create_sample_data.py` approach to generate random orders, OR convert the few orders from Quản_Lý_Thời_Trang.
    # But Quản_Lý_Thời_Trang only has 3 orders. That's weak for "All Time" reports.
    # I should probably KEEP the random order generation but UPDATE it to be more robust, OR append a simplified random generation script to this SQL file (using Postgres `generate_series`?).
    
    # Better: Write a python script that generates robust SQL inserts for Orders based on the rich Reviews/Comments (e.g. if someone reviewed it, they probably bought it).
    
    # For now, let's just stick to the requested "data from SQL file". The user said "lấy thêm data" (get *more* data).
    # If the user was using `create_sample_data.py` (which runs on `run.py` startup? No, `run.py` doesn't run it automatically. The user has to run it manually or I run it.)
    # The user complained about "missing data".
    
    # I will Add a block of SQL to generate random orders in Postgres using PL/PGSQL or simple inserts
    # to Ensure the Reports page isn't empty.
    
    random_orders_sql = """
-- Generate Random Orders for Reports
DO $$
DECLARE
    v_CustomerId INT;
    v_OrderId INT;
    v_ProductId INT;
    v_VariantId INT;
    v_Price DECIMAL(18,2);
    v_Date TIMESTAMP;
    i INT;
    j INT;
BEGIN
    -- Generate 50 orders over the last 2 years
    FOR i IN 1..50 LOOP
        -- Random Customer 1-20
        v_CustomerId := floor(random() * 20 + 1)::int;
        -- Random Date
        v_Date := CURRENT_TIMESTAMP - (random() * 700 || ' days')::interval;
        
        INSERT INTO Orders (CustomerID, OrderDate, TotalAmount, Status, PaymentMethod, ShippingAddress)
        VALUES (v_CustomerId, v_Date, 0, 'Delivered', 'COD', 'Address')
        RETURNING OrderID INTO v_OrderId;
        
        -- Add 1-3 items
        FOR j IN 1..floor(random() * 3 + 1)::int LOOP
            -- Random Product 1-22
            v_ProductId := floor(random() * 22 + 1)::int;
            
            -- Get a Variant for this product
            SELECT VariantID INTO v_VariantId FROM ProductVariants WHERE ProductID = v_ProductId LIMIT 1;
            
            IF v_VariantId IS NOT NULL THEN
                SELECT Price INTO v_Price FROM Products WHERE ProductID = v_ProductId;
                
                INSERT INTO OrderDetails (OrderID, VariantID, Quantity, Price)
                VALUES (v_OrderId, v_VariantId, floor(random() * 2 + 1)::int, v_Price);
            END IF;
        END LOOP;
        
        -- Update Total
        UPDATE Orders SET TotalAmount = (SELECT SUM(Quantity * Price) FROM OrderDetails WHERE OrderID = v_OrderId) WHERE OrderID = v_OrderId;
    END LOOP;
END $$;
"""
    output_lines.append(random_orders_sql)

    # Reset sequences
    output_lines.append("""
SELECT setval('categories_categoryid_seq', (SELECT MAX(categoryid) FROM categories));
SELECT setval('colors_colorid_seq', (SELECT MAX(colorid) FROM colors));
SELECT setval('sizes_sizeid_seq', (SELECT MAX(sizeid) FROM sizes));
SELECT setval('customers_customerid_seq', (SELECT MAX(customerid) FROM customers));
SELECT setval('products_productid_seq', (SELECT MAX(productid) FROM products));
SELECT setval('productvariants_variantid_seq', (SELECT MAX(variantid) FROM productvariants));
SELECT setval('orders_orderid_seq', COALESCE((SELECT MAX(orderid) FROM orders), 1));
SELECT setval('orderdetails_orderdetailid_seq', COALESCE((SELECT MAX(orderdetailid) FROM orderdetails), 1));
SELECT setval('reviews_reviewid_seq', (SELECT MAX(reviewid) FROM reviews));
SELECT setval('productcomments_commentid_seq', (SELECT MAX(commentid) FROM productcomments));
""")

    output_path = os.path.join(data_dir, "postgresql_data_full.sql")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(output_lines))
    
    print(f"Created {output_path}")

if __name__ == "__main__":
    main()
