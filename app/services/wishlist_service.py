from typing import Any

from app.services.base_service import BaseService
from app.validation import positive_int


class WishlistService(BaseService):
    @staticmethod
    def get_wishlist_by_user(user_id):
        user_id = positive_int(user_id, 'Khách hàng', 2_147_483_647)
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT w.WishlistID, p.ProductID, p.ProductName, p.Price, p.OriginalPrice, c.CategoryName,
                        (SELECT cl.ColorName FROM Colors cl
                         JOIN ProductVariants pv ON cl.ColorID = pv.ColorID
                         WHERE pv.ProductID = p.ProductID ORDER BY pv.VariantID LIMIT 1) AS FirstColor,
                        p.ImageURL, w.AddedDate
                    FROM Wishlist w
                    JOIN Products p ON w.ProductID = p.ProductID
                    JOIN Categories c ON p.CategoryID = c.CategoryID
                    WHERE w.CustomerID = %s
                    ORDER BY w.AddedDate DESC, w.WishlistID DESC
                """,
                    (user_id,),
                )
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def add_to_wishlist(user_id, product_id) -> dict[str, Any]:
        user_id = positive_int(user_id, 'Khách hàng', 2_147_483_647)
        product_id = positive_int(product_id, 'Sản phẩm', 2_147_483_647)
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT ProductID FROM Products WHERE ProductID = %s FOR KEY SHARE', (product_id,))
                if not cursor.fetchone():
                    return {'success': False, 'message': 'Sản phẩm không tồn tại', 'status_code': 404}
                cursor.execute(
                    """
                    INSERT INTO Wishlist (CustomerID, ProductID, AddedDate)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (CustomerID, ProductID) DO NOTHING RETURNING WishlistID
                """,
                    (user_id, product_id),
                )
                added = cursor.fetchone()
                conn.commit()
                if not added:
                    return {
                        'success': False,
                        'message': 'Sản phẩm đã có trong danh sách yêu thích',
                        'status_code': 409,
                    }
                return {'success': True, 'message': 'Đã thêm vào danh sách yêu thích'}
        except Exception as exc:
            conn.rollback()
            result = BaseService.handle_error(exc, 'Không thể thêm vào danh sách yêu thích. Vui lòng thử lại sau.')
            result['status_code'] = 503
            return result
        finally:
            conn.close()

    @staticmethod
    def remove_from_wishlist(user_id, wishlist_id) -> dict[str, Any]:
        user_id = positive_int(user_id, 'Khách hàng', 2_147_483_647)
        wishlist_id = positive_int(wishlist_id, 'Danh sách yêu thích', 2_147_483_647)
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM Wishlist WHERE WishlistID = %s AND CustomerID = %s RETURNING WishlistID
                """,
                    (wishlist_id, user_id),
                )
                if not cursor.fetchone():
                    return {'success': False, 'message': 'Mục yêu thích không tồn tại', 'status_code': 404}
                conn.commit()
                return {'success': True, 'message': 'Đã xóa khỏi danh sách yêu thích'}
        except Exception as exc:
            conn.rollback()
            result = BaseService.handle_error(exc, 'Không thể xóa khỏi danh sách yêu thích. Vui lòng thử lại sau.')
            result['status_code'] = 503
            return result
        finally:
            conn.close()
