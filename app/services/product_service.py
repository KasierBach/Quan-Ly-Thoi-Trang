from decimal import Decimal
from typing import Any

import psycopg2
from flask import url_for

from app.services.base_service import BaseService
from app.cache import cached, invalidate_cache
from app.utils import resolve_image
from app.validation import ValidationError, money, positive_int, required_text


class ProductService(BaseService):
    MAX_INTEGER = 2_147_483_647
    SORTS = {
        'newest': 'p.CreatedAt DESC, sp.ProductID DESC',
        'price_asc': 'sp.Price ASC, sp.ProductID ASC',
        'price_desc': 'sp.Price DESC, sp.ProductID ASC',
        'name_asc': 'sp.ProductName ASC, sp.ProductID ASC',
    }

    @staticmethod
    def optional_text(value, field, max_length):
        if value is None or value == '':
            return ''
        if isinstance(value, str) and not value.strip() and '\x00' not in value:
            return ''
        return required_text(value, field, max_length)

    @staticmethod
    def normalize_cart_items(cart_items):
        """Validate quantities and combine duplicate variants without trusting prices."""
        if not isinstance(cart_items, list):
            raise ValidationError('Giỏ hàng không hợp lệ')
        quantities = {}
        for item in cart_items:
            if not isinstance(item, dict):
                raise ValidationError('Sản phẩm trong giỏ hàng không hợp lệ')
            variant_id = positive_int(item.get('variant_id'), 'Biến thể', ProductService.MAX_INTEGER)
            quantity = positive_int(item.get('quantity'), 'Số lượng', ProductService.MAX_INTEGER)
            quantities[variant_id] = positive_int(
                quantities.get(variant_id, 0) + quantity, 'Số lượng', ProductService.MAX_INTEGER
            )
        return [{'variant_id': vid, 'quantity': qty} for vid, qty in sorted(quantities.items())]

    @staticmethod
    def cart_item(variant_id, quantity, variant):
        """Keep exact decimal prices in the session; use current database metadata."""
        return {
            'variant_id': variant_id,
            'product_id': variant.ProductID,
            'product_name': variant.ProductName,
            'price': str(money(variant.Price, 'Giá sản phẩm')),
            'color': variant.ColorName,
            'size': variant.SizeName,
            'quantity': quantity,
            'stock': variant.Quantity,
            'image_url': variant.ImageURL,
        }

    @staticmethod
    def refresh_cart_items(cart_items, require_stock=False, drop_missing=False):
        refreshed = []
        for item in ProductService.normalize_cart_items(cart_items):
            variant = ProductService.get_variant_detail(item['variant_id'])
            if not variant:
                if drop_missing:
                    continue
                raise ValidationError('Sản phẩm trong giỏ hàng không còn tồn tại')
            if require_stock and item['quantity'] > variant.Quantity:
                raise ValidationError(f'{variant.ProductName}: chỉ còn {variant.Quantity} sản phẩm trong kho')
            refreshed.append(ProductService.cart_item(item['variant_id'], item['quantity'], variant))
        return refreshed

    @staticmethod
    def cart_total(cart_items):
        return sum(
            (
                money(item['price'], 'Giá sản phẩm')
                * positive_int(item['quantity'], 'Số lượng', ProductService.MAX_INTEGER)
                for item in cart_items
            ),
            Decimal('0.00'),
        )

    @staticmethod
    def product_image(product):
        path = resolve_image(product)
        if path.startswith(('https://', 'http://')):
            return path
        return url_for('static', filename=path)

    @staticmethod
    def get_variant_detail(variant_id):
        """Fetch detailed variant information for cart/checkout."""
        variant_id = positive_int(variant_id, 'Biến thể', ProductService.MAX_INTEGER)
        conn = ProductService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT pv.Quantity, p.ProductName, p.Price, c.ColorName, s.SizeName, p.ProductID, p.ImageURL
                    FROM ProductVariants pv
                    JOIN Products p ON pv.ProductID = p.ProductID
                    JOIN Colors c ON pv.ColorID = c.ColorID
                    JOIN Sizes s ON pv.SizeID = s.SizeID
                    WHERE pv.VariantID = %s
                """,
                    (variant_id,),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def get_variant_quantity(variant_id):
        """Fetch available quantity for a variant."""
        variant_id = positive_int(variant_id, 'Biến thể', ProductService.MAX_INTEGER)
        conn = ProductService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT Quantity FROM ProductVariants WHERE VariantID = %s', (variant_id,))
                res = cursor.fetchone()
                return res.Quantity if res else 0
        finally:
            conn.close()

    @staticmethod
    def get_product_by_id(product_id):
        product_id = positive_int(product_id, 'Sản phẩm', ProductService.MAX_INTEGER)
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT p.*, c.CategoryName FROM Products p
                    JOIN Categories c ON p.CategoryID = c.CategoryID
                    WHERE p.ProductID = %s
                """,
                    (product_id,),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def get_product_variants(product_id):
        product_id = positive_int(product_id, 'Sản phẩm', ProductService.MAX_INTEGER)
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT pv.VariantID, c.ColorID, c.ColorName, s.SizeID, s.SizeName, pv.Quantity
                    FROM ProductVariants pv
                    JOIN Colors c ON pv.ColorID = c.ColorID
                    JOIN Sizes s ON pv.SizeID = s.SizeID
                    WHERE pv.ProductID = %s
                """,
                    (product_id,),
                )
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def get_variant_by_details(product_id, color_id, size_id):
        product_id = positive_int(product_id, 'Sản phẩm', ProductService.MAX_INTEGER)
        color_id = positive_int(color_id, 'Màu sắc', ProductService.MAX_INTEGER)
        size_id = positive_int(size_id, 'Kích thước', ProductService.MAX_INTEGER)
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT VariantID, Quantity FROM ProductVariants 
                    WHERE ProductID = %s AND ColorID = %s AND SizeID = %s
                """,
                    (product_id, color_id, size_id),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def search_products(
        search_term, category_id, min_price, max_price, color_id, size_id, in_stock_only, page, per_page, sort_by
    ):
        search_term = required_text(search_term, 'Tìm kiếm', 200) if search_term else ''
        category_id = (
            positive_int(category_id, 'Danh mục', ProductService.MAX_INTEGER) if category_id is not None else None
        )
        color_id = positive_int(color_id, 'Màu sắc', ProductService.MAX_INTEGER) if color_id is not None else None
        size_id = positive_int(size_id, 'Kích thước', ProductService.MAX_INTEGER) if size_id is not None else None
        min_price = money(min_price, 'Giá tối thiểu') if min_price is not None else None
        max_price = money(max_price, 'Giá tối đa') if max_price is not None else None
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ValidationError('Giá tối thiểu không được lớn hơn giá tối đa')
        page = positive_int(page, 'Trang', ProductService.MAX_INTEGER)
        per_page = positive_int(per_page, 'Số sản phẩm mỗi trang')
        if per_page not in (12, 24, 48):
            per_page = 12
        if in_stock_only not in (0, 1, False, True):
            raise ValidationError('Bộ lọc tồn kho không hợp lệ')
        sort_query = ProductService.SORTS.get(
            sort_by if isinstance(sort_by, str) else '', ProductService.SORTS['newest']
        )
        filters = (search_term, category_id, min_price, max_price, color_id, size_id, bool(in_stock_only))
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) FROM sp_SearchProducts(%s, %s, %s, %s, %s, %s, %s)', filters)
                total_records = cursor.fetchone()[0]
                total_pages = max(1, (total_records + per_page - 1) // per_page)
                page = min(page, total_pages)
                offset = (page - 1) * per_page
                cursor.execute(
                    f"""
                    SELECT sp.*,
                    COALESCE((SELECT AVG(Rating) FROM Reviews WHERE ProductID = sp.ProductID), 0) AS AverageRating,
                    (SELECT COUNT(*) FROM Reviews WHERE ProductID = sp.ProductID) AS ReviewCount
                    FROM sp_SearchProducts(%s, %s, %s, %s, %s, %s, %s) sp
                    JOIN Products p ON p.ProductID = sp.ProductID
                    ORDER BY {sort_query} LIMIT %s OFFSET %s
                """,
                    filters + (per_page, offset),
                )
                return {
                    'products': cursor.fetchall(),
                    'total_records': total_records,
                    'total_pages': total_pages,
                    'current_page': page,
                    'offset': offset,
                }
        finally:
            conn.close()

    @staticmethod
    @cached(timeout=600, key_prefix='colors:')
    def get_all_colors():
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM Colors')
                return list(cursor.fetchall())
        finally:
            conn.close()

    @staticmethod
    @cached(timeout=600, key_prefix='sizes:')
    def get_all_sizes():
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM Sizes')
                return list(cursor.fetchall())
        finally:
            conn.close()

    @staticmethod
    def search_autocomplete(query, limit=8):
        query = required_text(query, 'Tìm kiếm', 200)
        limit = positive_int(limit, 'Giới hạn', 50)
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT p.ProductID, p.ProductName, p.Price, p.ImageURL, p.CategoryID, c.CategoryName
                    FROM Products p JOIN Categories c ON p.CategoryID = c.CategoryID
                    WHERE LOWER(p.ProductName) LIKE LOWER(%s)
                    ORDER BY p.ProductName, p.ProductID LIMIT %s
                """,
                    (f'%{query}%', limit),
                )
                return [
                    {
                        'id': p.ProductID,
                        'name': p.ProductName,
                        'price': str(money(p.Price, 'Giá sản phẩm')),
                        'image': ProductService.product_image(p),
                        'category': p.CategoryName,
                    }
                    for p in cursor.fetchall()
                ]
        finally:
            conn.close()

    @staticmethod
    def get_recently_viewed_products(product_ids):
        ids = []
        for value in product_ids if isinstance(product_ids, list) else []:
            try:
                product_id = positive_int(value, 'Sản phẩm', ProductService.MAX_INTEGER)
            except ValidationError:
                continue
            if product_id not in ids:
                ids.append(product_id)
            if len(ids) == 10:
                break
        if not ids:
            return []
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT p.ProductID, p.ProductName, p.Price, p.ImageURL, c.CategoryName
                    FROM Products p JOIN Categories c ON p.CategoryID = c.CategoryID
                    WHERE p.ProductID IN %s
                """,
                    (tuple(ids),),
                )
                products = {
                    p.ProductID: {
                        'product_id': p.ProductID,
                        'product_name': p.ProductName,
                        'price': str(money(p.Price, 'Giá sản phẩm')),
                        'image_url': ProductService.product_image(p),
                        'category_name': p.CategoryName,
                    }
                    for p in cursor.fetchall()
                }
                return [products[pid] for pid in ids if pid in products]
        finally:
            conn.close()

    @staticmethod
    def invalidate_catalog():
        for prefix in ('categories:', 'products:', 'catalog:'):
            invalidate_cache(prefix)

    @staticmethod
    def _mutation_error(exc) -> dict[str, Any]:
        if isinstance(exc, psycopg2.Error) and exc.pgcode == '23503':
            return {
                'success': False,
                'message': 'Dữ liệu tham chiếu không tồn tại hoặc đang được sử dụng',
                'status_code': 409,
            }
        if isinstance(exc, psycopg2.Error) and exc.pgcode == '23505':
            return {'success': False, 'message': 'Dữ liệu đã tồn tại', 'status_code': 409}
        result = BaseService.handle_error(exc)
        result['status_code'] = 503
        return result

    @staticmethod
    def _product_fields(name, description, price, category_id, original_price):
        name = required_text(name, 'Tên sản phẩm', 255)
        description = ProductService.optional_text(description, 'Mô tả', 10000)
        price = money(price, 'Giá bán')
        original_price = money(original_price, 'Giá gốc')
        category_id = positive_int(category_id, 'Danh mục', ProductService.MAX_INTEGER)
        return name, description, price, category_id, original_price

    @staticmethod
    def add_product(name, description, price, category_id, original_price) -> dict[str, Any]:
        try:
            name, description, price, category_id, original_price = ProductService._product_fields(
                name, description, price, category_id, original_price
            )
        except ValidationError as exc:
            return {'success': False, 'message': str(exc), 'status_code': 400}
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT sp_AddProduct(%s, %s, %s, %s, %s) AS ProductID',
                    (name, description, price, original_price, category_id),
                )
                product_id = cursor.fetchone().ProductID
                conn.commit()
                ProductService.invalidate_catalog()
                return {'success': True, 'product_id': product_id}
        except Exception as exc:
            conn.rollback()
            return ProductService._mutation_error(exc)
        finally:
            conn.close()

    @staticmethod
    def update_product(product_id, name, description, price, category_id, original_price, image_url) -> dict[str, Any]:
        try:
            product_id = positive_int(product_id, 'Sản phẩm', ProductService.MAX_INTEGER)
            name, description, price, category_id, original_price = ProductService._product_fields(
                name, description, price, category_id, original_price
            )
            image_url = ProductService.optional_text(image_url, 'Ảnh sản phẩm', 255)
        except ValidationError as exc:
            return {'success': False, 'message': str(exc), 'status_code': 400}
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE Products SET ProductName=%s, Description=%s, Price=%s, OriginalPrice=%s,
                        CategoryID=%s, ImageURL=%s WHERE ProductID=%s
                """,
                    (name, description, price, original_price, category_id, image_url, product_id),
                )
                if cursor.rowcount == 0:
                    return {'success': False, 'message': 'Sản phẩm không tồn tại', 'status_code': 404}
                conn.commit()
                ProductService.invalidate_catalog()
                return {'success': True}
        except Exception as exc:
            conn.rollback()
            return ProductService._mutation_error(exc)
        finally:
            conn.close()

    @staticmethod
    def add_variant(product_id, color_id, size_id, quantity) -> dict[str, Any]:
        try:
            product_id = positive_int(product_id, 'Sản phẩm', ProductService.MAX_INTEGER)
            color_id = positive_int(color_id, 'Màu sắc', ProductService.MAX_INTEGER)
            size_id = positive_int(size_id, 'Kích thước', ProductService.MAX_INTEGER)
            quantity = (
                0
                if not isinstance(quantity, bool) and str(quantity) == '0'
                else positive_int(quantity, 'Tồn kho', ProductService.MAX_INTEGER)
            )
        except ValidationError as exc:
            return {'success': False, 'message': str(exc), 'status_code': 400}
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT sp_AddProductVariant(%s, %s, %s, %s) AS VariantID',
                    (product_id, color_id, size_id, quantity),
                )
                conn.commit()
                ProductService.invalidate_catalog()
                return {'success': True}
        except Exception as exc:
            conn.rollback()
            return ProductService._mutation_error(exc)
        finally:
            conn.close()

    @staticmethod
    def delete_variant(variant_id) -> dict[str, Any]:
        try:
            variant_id = positive_int(variant_id, 'Biến thể', ProductService.MAX_INTEGER)
        except ValidationError as exc:
            return {'success': False, 'message': str(exc), 'status_code': 400}
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT VariantID FROM ProductVariants WHERE VariantID = %s FOR UPDATE', (variant_id,))
                if not cursor.fetchone():
                    return {'success': False, 'message': 'Biến thể không tồn tại', 'status_code': 404}
                cursor.execute('SELECT 1 FROM OrderDetails WHERE VariantID = %s LIMIT 1', (variant_id,))
                if cursor.fetchone():
                    return {
                        'success': False,
                        'message': 'Không thể xóa biến thể đã có trong đơn hàng',
                        'status_code': 409,
                    }
                cursor.execute('DELETE FROM ProductVariants WHERE VariantID = %s', (variant_id,))
                conn.commit()
                ProductService.invalidate_catalog()
                return {'success': True}
        except Exception as exc:
            conn.rollback()
            return ProductService._mutation_error(exc)
        finally:
            conn.close()

    @staticmethod
    def delete_product(product_id) -> dict[str, Any]:
        try:
            product_id = positive_int(product_id, 'Sản phẩm', ProductService.MAX_INTEGER)
        except ValidationError as exc:
            return {'success': False, 'message': str(exc), 'status_code': 400}
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT ProductID FROM Products WHERE ProductID = %s FOR UPDATE', (product_id,))
                if not cursor.fetchone():
                    return {'success': False, 'message': 'Sản phẩm không tồn tại', 'status_code': 404}
                cursor.execute(
                    'SELECT VariantID FROM ProductVariants WHERE ProductID = %s ORDER BY VariantID FOR UPDATE',
                    (product_id,),
                )
                cursor.fetchall()
                cursor.execute(
                    """
                    SELECT 1 FROM OrderDetails od JOIN ProductVariants pv ON od.VariantID = pv.VariantID
                    WHERE pv.ProductID = %s LIMIT 1
                """,
                    (product_id,),
                )
                if cursor.fetchone():
                    return {
                        'success': False,
                        'message': 'Không thể xóa sản phẩm đã có trong đơn hàng',
                        'status_code': 409,
                    }
                for table in ('Wishlist', 'Reviews', 'ProductComments', 'ProductVariants'):
                    cursor.execute(f'DELETE FROM {table} WHERE ProductID = %s', (product_id,))
                cursor.execute('DELETE FROM Products WHERE ProductID = %s', (product_id,))
                conn.commit()
                ProductService.invalidate_catalog()
                return {'success': True}
        except Exception as exc:
            conn.rollback()
            return ProductService._mutation_error(exc)
        finally:
            conn.close()

    @staticmethod
    def get_admin_products(page, per_page, sort_by):
        try:
            page = positive_int(page, 'Trang', ProductService.MAX_INTEGER)
        except ValidationError:
            page = 1
        try:
            per_page = positive_int(per_page, 'Số sản phẩm mỗi trang')
        except ValidationError:
            per_page = 20
        if per_page not in (10, 12, 20, 24, 48, 50, 100):
            per_page = 20
        sort_query = ProductService.SORTS.get(
            sort_by if isinstance(sort_by, str) else '', ProductService.SORTS['newest']
        ).replace('sp.', 'p.')
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) FROM Products')
                total_records = cursor.fetchone()[0]
                total_pages = max(1, (total_records + per_page - 1) // per_page)
                page = min(page, total_pages)
                offset = (page - 1) * per_page
                cursor.execute(
                    f"""
                    SELECT p.*, c.CategoryName,
                    (SELECT COUNT(*) FROM ProductVariants WHERE ProductID = p.ProductID) AS VariantCount,
                    COALESCE((SELECT SUM(Quantity) FROM ProductVariants WHERE ProductID = p.ProductID), 0) AS TotalStock
                    FROM Products p JOIN Categories c ON p.CategoryID = c.CategoryID
                    ORDER BY {sort_query} LIMIT %s OFFSET %s
                """,
                    (per_page, offset),
                )
                return {
                    'products': cursor.fetchall(),
                    'total_records': total_records,
                    'total_pages': total_pages,
                    'current_page': page,
                    'per_page': per_page,
                    'start_index': offset + 1 if total_records else 0,
                    'end_index': min(offset + per_page, total_records),
                }
        finally:
            conn.close()

    @staticmethod
    def get_featured_products(limit=8):
        limit = positive_int(limit, 'Giới hạn', 100)
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT p.ProductID, p.ProductName, p.Price, p.OriginalPrice, c.CategoryName, p.ImageURL,
                    (SELECT cl.ColorName FROM Colors cl JOIN ProductVariants pv ON cl.ColorID = pv.ColorID 
                     WHERE pv.ProductID = p.ProductID LIMIT 1) AS FirstColor,
                    COALESCE((SELECT AVG(Rating) FROM Reviews WHERE ProductID = p.ProductID), 0) as AverageRating,
                    (SELECT COUNT(*) FROM Reviews WHERE ProductID = p.ProductID) as ReviewCount
                    FROM Products p JOIN Categories c ON p.CategoryID = c.CategoryID
                    ORDER BY p.CreatedAt DESC, p.ProductID DESC LIMIT %s
                """,
                    (limit,),
                )
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def get_best_selling_products(limit=8):
        limit = positive_int(limit, 'Giới hạn', 100)
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT bs.ProductID, bs.ProductName, bs.Price, bs.OriginalPrice, bs.CategoryName, bs.TotalSold, p.ImageURL,
                    COALESCE((SELECT AVG(Rating) FROM Reviews WHERE ProductID = bs.ProductID), 0) as AverageRating,
                    (SELECT COUNT(*) FROM Reviews WHERE ProductID = bs.ProductID) as ReviewCount
                    FROM vw_BestSellingProducts bs JOIN Products p ON bs.ProductID = p.ProductID
                    ORDER BY bs.TotalSold DESC, bs.ProductID ASC LIMIT %s
                """,
                    (limit,),
                )
                return cursor.fetchall()
        finally:
            conn.close()
