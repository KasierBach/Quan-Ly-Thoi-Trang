from app.services.base_service import BaseService

class AttributeService(BaseService):
    @staticmethod
    def get_all_colors():
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM Colors ORDER BY ColorName')
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_all_sizes():
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM Sizes ORDER BY SizeName')
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def add_color(color_name):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO Colors (ColorName) VALUES (%s)', (color_name,))
            conn.commit()
            return {'success': True}
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def add_size(size_name):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO Sizes (SizeName) VALUES (%s)', (size_name,))
            conn.commit()
            return {'success': True}
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def delete_color(color_id):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM Colors WHERE ColorID = %s', (color_id,))
            conn.commit()
            return {'success': True}
        except Exception as e:
            conn.rollback()
            # Check for foreign key usage/integrity error typically raised by DB
            error_str = str(e)
            if "update or delete on table" in error_str and "violates foreign key constraint" in error_str:
                 return {'success': False, 'message': 'Không thể xóa màu này vì đang được sử dụng trong sản phẩm.'}
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def delete_size(size_id):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM Sizes WHERE SizeID = %s', (size_id,))
            conn.commit()
            return {'success': True}
        except Exception as e:
            conn.rollback()
            error_str = str(e)
            if "update or delete on table" in error_str and "violates foreign key constraint" in error_str:
                 return {'success': False, 'message': 'Không thể xóa kích thước này vì đang được sử dụng trong sản phẩm.'}
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()
