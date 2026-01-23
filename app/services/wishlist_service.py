from app.services.base_service import BaseService

class WishlistService(BaseService):
    @staticmethod
    def get_wishlist_by_user(user_id):
        """Get all wishlist items for a user, including product details and a representative color."""
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            # Optimized query using LATERAL JOIN (if supported) or just keeping the subselect but optimized index usage
            # For simplicity and standard SQL compatibility, we'll stick to the subquery but ensure it's efficient.
            cursor.execute('''
                SELECT w.WishlistID, p.ProductID, p.ProductName, p.Price, c.CategoryName,
                  (SELECT ColorName FROM Colors cl 
                   JOIN ProductVariants pv ON cl.ColorID = pv.ColorID 
                   WHERE pv.ProductID = p.ProductID 
                   ORDER BY pv.VariantID ASC
                   LIMIT 1) AS FirstColor,
                  p.ImageURL, w.AddedDate
                FROM Wishlist w
                JOIN Products p ON w.ProductID = p.ProductID
                JOIN Categories c ON p.CategoryID = c.CategoryID
                WHERE w.CustomerID = %s
                ORDER BY w.AddedDate DESC
            ''', (user_id,))
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def add_to_wishlist(user_id, product_id):
        """Add a product to the user's wishlist if not already present."""
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT WishlistID FROM Wishlist WHERE CustomerID = %s AND ProductID = %s', (user_id, product_id))
            if cursor.fetchone():
                return False, "Sản phẩm đã có trong danh sách yêu thích"
            
            cursor.execute('INSERT INTO Wishlist (CustomerID, ProductID, AddedDate) VALUES (%s, %s, CURRENT_TIMESTAMP)', (user_id, product_id))
            conn.commit()
            return True, "Đã thêm vào danh sách yêu thích"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def remove_from_wishlist(user_id, wishlist_id):
        """Remove an item from the wishlist."""
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT WishlistID FROM Wishlist WHERE WishlistID = %s AND CustomerID = %s', (wishlist_id, user_id))
            if not cursor.fetchone():
                return False, "Không có quyền thực hiện"
            
            cursor.execute('DELETE FROM Wishlist WHERE WishlistID = %s', (wishlist_id,))
            conn.commit()
            return True, "Đã xóa khỏi danh sách yêu thích"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            cursor.close()
            conn.close()
