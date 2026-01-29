from app.services.base_service import BaseService
from app.cache import cached, cache

class ProductService(BaseService):
    @staticmethod
    def get_product_by_id(product_id):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT p.*, c.CategoryName 
                FROM Products p
                JOIN Categories c ON p.CategoryID = c.CategoryID
                WHERE p.ProductID = %s
            ''', (product_id,))
            return cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_product_variants(product_id):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT pv.VariantID, c.ColorID, c.ColorName, s.SizeID, s.SizeName, pv.Quantity
                FROM ProductVariants pv
                JOIN Colors c ON pv.ColorID = c.ColorID
                JOIN Sizes s ON pv.SizeID = s.SizeID
                WHERE pv.ProductID = %s
            ''', (product_id,))
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_variant_by_details(product_id, color_id, size_id):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT VariantID, Quantity 
                FROM ProductVariants 
                WHERE ProductID = %s AND ColorID = %s AND SizeID = %s
            ''', (product_id, color_id, size_id))
            return cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def search_products(search_term, category_id, min_price, max_price, color_id, size_id, in_stock_only, page, per_page, sort_by):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            # Sorting logic
            sort_query = "ProductID DESC"
            if sort_by == 'price_asc': sort_query = "Price ASC"
            elif sort_by == 'price_desc': sort_query = "Price DESC"
            elif sort_by == 'name_asc': sort_query = "ProductName ASC"

            # Count total records
            count_query = f"SELECT COUNT(*) FROM sp_SearchProducts(%s, %s, %s, %s, %s, %s, %s)"
            cursor.execute(count_query, (search_term, category_id, min_price, max_price, color_id, size_id, bool(in_stock_only)))
            total_records = cursor.fetchone()[0]
            
            total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
            if page > total_pages: page = total_pages
            offset = (page - 1) * per_page
            
            cursor.execute(f'''
                SELECT sp.*,
                COALESCE((SELECT AVG(Rating) FROM Reviews WHERE ProductID = sp.ProductID), 0) as AverageRating,
                (SELECT COUNT(*) FROM Reviews WHERE ProductID = sp.ProductID) as ReviewCount
                FROM sp_SearchProducts(%s, %s, %s, %s, %s, %s, %s) sp
                ORDER BY {sort_query}
                LIMIT %s OFFSET %s
            ''', (search_term, category_id, min_price, max_price, color_id, size_id, bool(in_stock_only), per_page, offset))
            
            products = cursor.fetchall()
            
            return {
                'products': products,
                'total_records': total_records,
                'total_pages': total_pages,
                'current_page': page,
                'offset': offset
            }
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    @cached(timeout=600, key_prefix='colors:')  # Cache for 10 minutes
    def get_all_colors():
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM Colors')
            return list(cursor.fetchall())
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    @cached(timeout=600, key_prefix='sizes:')  # Cache for 10 minutes
    def get_all_sizes():
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM Sizes')
            return list(cursor.fetchall())
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def search_autocomplete(query, limit=8):
        """Search products by name for autocomplete suggestions"""
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            search_pattern = f"%{query}%"
            cursor.execute('''
                SELECT p.ProductID, p.ProductName, p.Price, p.ImageURL, p.CategoryID, c.CategoryName
                FROM Products p
                JOIN Categories c ON p.CategoryID = c.CategoryID
                WHERE LOWER(p.ProductName) LIKE LOWER(%s)
                ORDER BY p.ProductName
                LIMIT %s
            ''', (search_pattern, limit))
            products = cursor.fetchall()
            
            results = []
            from app.utils import resolve_image
            
            for p in products:
                # Create a dict-like object or use the row directly if it supports dict access
                # Psycopg2 RealDictCursor rows act like dicts, but standard tuples don't.
                # Here we are fetching tuples or named tuples depending on setup, but let's make a temp dict for resolve_image
                temp_obj = {
                    'ProductID': p.ProductID,
                    'ProductName': p.ProductName,
                    'ImageURL': p.ImageURL,
                    'CategoryID': p.CategoryID if hasattr(p, 'CategoryID') else None, # p might not have CategoryID selected if not in query
                    'CategoryName': p.CategoryName
                }
                
                # Check if we need CategoryID for fallback in resolve_image
                # The query joins Categories but doesn't select CategoryID explicitly in the SELECT list (only p.* might, but let's check query)
                # Query: SELECT p.ProductID, p.ProductName, p.Price, p.ImageURL, c.CategoryName FROM ...
                # It does NOT select CategoryID. We should add it to the query to be safe for resolve_image fallback.
                
                resolved_path = resolve_image(temp_obj)
                image_path = f"/static/{resolved_path}"
                
                results.append({
                    'id': p.ProductID,
                    'name': p.ProductName,
                    'price': float(p.Price),
                    'image': image_path,
                    'category': p.CategoryName
                })
            
            return results
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def add_product(name, description, price, category_id, original_price):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT sp_AddProduct(%s, %s, %s, %s, %s) AS ProductID', 
                           (name, description, price, category_id, original_price))
            result = cursor.fetchone()
            conn.commit()
            return {'success': True, 'product_id': result.ProductID}
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def update_product(product_id, name, description, price, category_id, original_price, image_url):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE Products SET ProductName=%s, Description=%s, Price=%s, OriginalPrice=%s, CategoryID=%s, ImageURL=%s
                WHERE ProductID=%s
            ''', (name, description, price, original_price, category_id, image_url, product_id))
            conn.commit()
            return {'success': True}
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def add_variant(product_id, color_id, size_id, quantity):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT sp_AddProductVariant(%s, %s, %s, %s) AS VariantID', 
                           (product_id, color_id, size_id, quantity))
            conn.commit()
            return {'success': True}
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': str(e)}
        finally:
            conn.close()

    @staticmethod
    def delete_variant(variant_id):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM ProductVariants WHERE VariantID = %s', (variant_id,))
            conn.commit()
            return {'success': True}
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_admin_products(page, per_page, sort_by):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            # Sorting logic
            sort_query = "p.ProductID DESC"
            if sort_by == 'price_asc': sort_query = "p.Price ASC"
            elif sort_by == 'price_desc': sort_query = "p.Price DESC"
            elif sort_by == 'name_asc': sort_query = "p.ProductName ASC"
            
            # Count total records
            cursor.execute("SELECT COUNT(*) FROM Products")
            total_records = cursor.fetchone()[0]
            
            total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
            if page > total_pages: page = total_pages
            offset = (page - 1) * per_page
            
            cursor.execute(f'''
                SELECT p.*, c.CategoryName,
                (SELECT COUNT(*) FROM ProductVariants WHERE ProductID = p.ProductID) AS VariantCount,
                (SELECT SUM(Quantity) FROM ProductVariants WHERE ProductID = p.ProductID) AS TotalStock
                FROM Products p
                JOIN Categories c ON p.CategoryID = c.CategoryID
                ORDER BY {sort_query}
                LIMIT %s OFFSET %s
            ''', (per_page, offset))
            products = cursor.fetchall()
            
            return {
                'products': products,
                'total_records': total_records,
                'total_pages': total_pages,
                'current_page': page,
                'per_page': per_page,
                'start_index': offset + 1 if total_records > 0 else 0,
                'end_index': min(offset + per_page, total_records)
            }
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_featured_products(limit=8):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT p.ProductID, p.ProductName, p.Price, p.OriginalPrice, c.CategoryName, p.ImageURL,
                (SELECT cl.ColorName FROM Colors cl JOIN ProductVariants pv ON cl.ColorID = pv.ColorID 
                 WHERE pv.ProductID = p.ProductID LIMIT 1) AS FirstColor,
                COALESCE((SELECT AVG(Rating) FROM Reviews WHERE ProductID = p.ProductID), 0) as AverageRating,
                (SELECT COUNT(*) FROM Reviews WHERE ProductID = p.ProductID) as ReviewCount
                FROM Products p
                JOIN Categories c ON p.CategoryID = c.CategoryID
                ORDER BY p.CreatedAt DESC
                LIMIT %s
            ''', (limit,))
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_best_selling_products(limit=8):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT bs.ProductID, bs.ProductName, bs.Price, bs.OriginalPrice, bs.CategoryName, bs.TotalSold, p.ImageURL,
                COALESCE((SELECT AVG(Rating) FROM Reviews WHERE ProductID = bs.ProductID), 0) as AverageRating,
                (SELECT COUNT(*) FROM Reviews WHERE ProductID = bs.ProductID) as ReviewCount
                FROM vw_BestSellingProducts bs
                JOIN Products p ON bs.ProductID = p.ProductID
                ORDER BY bs.TotalSold DESC
                LIMIT %s
            ''', (limit,))
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()
