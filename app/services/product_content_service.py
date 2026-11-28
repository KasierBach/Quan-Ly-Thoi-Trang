from app.services.base_service import BaseService
from app.services.product_service import ProductService
from app.uploads import expired_product_uploads, remove_unused_product_uploads, save_image
from app.validation import ValidationError, positive_int, required_text


class ProductContentService(BaseService):
    MAX_GALLERY_IMAGES = 5

    @staticmethod
    def read(product_id, category_id, *, selected_sizes=None):
        conn = ProductContentService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT id, image_url, caption FROM ProductGallery WHERE product_id = %s ORDER BY id',
                    (product_id,),
                )
                gallery = cursor.fetchall()
                cursor.execute(
                    """SELECT s.SizeID, s.SizeName, m.chest, m.waist, m.hips
                       FROM CategorySizeMeasurements m JOIN Sizes s ON s.SizeID = m.size_id
                       WHERE m.category_id = %s ORDER BY s.SizeID""",
                    (category_id,),
                )
                measurements = cursor.fetchall()
                if selected_sizes is not None:
                    measurements = [row for row in measurements if row.SizeID in selected_sizes]
                return gallery, measurements
        finally:
            conn.close()

    @staticmethod
    def save_measurements(category_id, size_id, raw_chest, raw_waist, raw_hips):
        category_id = positive_int(category_id, 'Danh mục', ProductService.MAX_INTEGER)
        size_id = positive_int(size_id, 'Kích thước', ProductService.MAX_INTEGER)
        values = tuple(
            positive_int(raw, label, 999) if raw else None
            for raw, label in ((raw_chest, 'Vòng ngực'), (raw_waist, 'Vòng eo'), (raw_hips, 'Vòng mông'))
        )
        if not any(values):
            raise ValidationError('Nhập ít nhất một số đo theo cm')
        conn = ProductContentService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO CategorySizeMeasurements (category_id, size_id, chest, waist, hips)
                       SELECT %s, SizeID, %s, %s, %s FROM Sizes WHERE SizeID = %s
                       ON CONFLICT (category_id, size_id) DO UPDATE SET
                           chest = EXCLUDED.chest, waist = EXCLUDED.waist, hips = EXCLUDED.hips""",
                    (category_id, *values, size_id),
                )
                if not cursor.rowcount:
                    raise ValidationError('Kích thước không tồn tại')
                conn.commit()
        finally:
            conn.close()

    @staticmethod
    def delete_measurements(category_id, size_id):
        size_id = positive_int(size_id, 'Kích thước', ProductService.MAX_INTEGER)
        conn = ProductContentService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM CategorySizeMeasurements WHERE category_id = %s AND size_id = %s',
                    (category_id, size_id),
                )
                return ProductContentService._commit_if_found(conn, cursor)
        finally:
            conn.close()

    @staticmethod
    def add_image(product_id, upload, caption):
        product_id = positive_int(product_id, 'Sản phẩm', ProductService.MAX_INTEGER)
        caption = required_text(caption, 'Tên góc ảnh', 80)
        conn = ProductContentService.get_connection()
        try:
            with conn.cursor() as cursor:
                expired = expired_product_uploads()
                if expired:
                    remove_unused_product_uploads(cursor, expired)
                cursor.execute('SELECT ProductID FROM Products WHERE ProductID = %s FOR UPDATE', (product_id,))
                if not cursor.fetchone():
                    return False
                cursor.execute('SELECT COUNT(*) FROM ProductGallery WHERE product_id = %s', (product_id,))
                if cursor.fetchone()[0] >= ProductContentService.MAX_GALLERY_IMAGES:
                    raise ValidationError('Mỗi sản phẩm có tối đa 5 ảnh bổ sung')
                path, _ = save_image(upload, 'products', prefix=f'gallery-{product_id}-', max_side=1600)
                cursor.execute(
                    'INSERT INTO ProductGallery (product_id, image_url, caption) VALUES (%s, %s, %s)',
                    (product_id, f'images/{path.name}', caption),
                )
                conn.commit()
                return True
        finally:
            conn.close()

    @staticmethod
    def delete_image(product_id, image_id):
        product_id = positive_int(product_id, 'Sản phẩm', ProductService.MAX_INTEGER)
        image_id = positive_int(image_id, 'Ảnh sản phẩm', 9223372036854775807)
        conn = ProductContentService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM ProductGallery WHERE product_id = %s AND id = %s', (product_id, image_id))
                return ProductContentService._commit_if_found(conn, cursor)
        finally:
            conn.close()

    @staticmethod
    def _commit_if_found(conn, cursor):
        if not cursor.rowcount:
            return False
        conn.commit()
        return True
