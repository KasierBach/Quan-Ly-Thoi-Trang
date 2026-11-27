from app.cache import invalidate_cache
from app.validation import positive_int, required_text

from .base_service import BaseService


class AttributeService(BaseService):
    @staticmethod
    def get_all_colors():
        conn = AttributeService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT ColorID, ColorName FROM Colors ORDER BY ColorName, ColorID')
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def get_all_sizes():
        conn = AttributeService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT SizeID, SizeName FROM Sizes ORDER BY SizeName, SizeID')
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def _add(table, column, name, field):
        # Table/column names only come from the fixed methods below, never input.
        name = required_text(name, field, 50)
        conn = AttributeService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f'SELECT 1 FROM {table} WHERE LOWER(BTRIM({column})) = LOWER(%s)', (name,))
                if cursor.fetchone():
                    return {'success': False, 'message': f'{field} đã tồn tại', 'status_code': 409}
                cursor.execute(f'INSERT INTO {table} ({column}) VALUES (%s)', (name,))
                conn.commit()
                invalidate_cache(f'{table.lower()}:')
                return AttributeService.success(message=f'Đã thêm {field.lower()}')
        except Exception as exc:
            conn.rollback()
            if getattr(exc, 'pgcode', None) == '23505':
                return {'success': False, 'message': f'{field} đã tồn tại', 'status_code': 409}
            result = AttributeService.handle_error(exc)
            result['status_code'] = 500
            return result
        finally:
            conn.close()

    @staticmethod
    def add_color(color_name):
        return AttributeService._add('Colors', 'ColorName', color_name, 'Màu')

    @staticmethod
    def add_size(size_name):
        return AttributeService._add('Sizes', 'SizeName', size_name, 'Kích thước')

    @staticmethod
    def _delete(table, column, value, field):
        value = positive_int(value, field, max_value=2147483647)
        conn = AttributeService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f'SELECT {column} FROM {table} WHERE {column} = %s FOR UPDATE', (value,))
                if not cursor.fetchone():
                    return {'success': False, 'message': f'{field} không tồn tại', 'status_code': 404}
                cursor.execute(f'SELECT 1 FROM ProductVariants WHERE {column} = %s LIMIT 1', (value,))
                if cursor.fetchone():
                    return {
                        'success': False,
                        'message': f'Không thể xóa {field.lower()} đang được sử dụng',
                        'status_code': 409,
                    }
                cursor.execute(f'DELETE FROM {table} WHERE {column} = %s RETURNING {column}', (value,))
                if not cursor.fetchone():
                    conn.rollback()
                    return {'success': False, 'message': f'{field} không tồn tại', 'status_code': 404}
                conn.commit()
                invalidate_cache(f'{table.lower()}:')
                return AttributeService.success(message=f'Đã xóa {field.lower()}')
        except Exception as exc:
            conn.rollback()
            if getattr(exc, 'pgcode', None) == '23503':
                return {
                    'success': False,
                    'message': f'Không thể xóa {field.lower()} đang được sử dụng',
                    'status_code': 409,
                }
            result = AttributeService.handle_error(exc)
            result['status_code'] = 500
            return result
        finally:
            conn.close()

    @staticmethod
    def delete_color(color_id):
        return AttributeService._delete('Colors', 'ColorID', color_id, 'Màu')

    @staticmethod
    def delete_size(size_id):
        return AttributeService._delete('Sizes', 'SizeID', size_id, 'Kích thước')
