from app.services.base_service import BaseService

class AttributeService(BaseService):
    @staticmethod
    def get_all_colors():
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM Colors ORDER BY ColorName')
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def get_all_sizes():
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM Sizes ORDER BY SizeName')
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def add_color(color_name):
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('INSERT INTO Colors (ColorName) VALUES (%s)', (color_name,))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return BaseService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def add_size(size_name):
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('INSERT INTO Sizes (SizeName) VALUES (%s)', (size_name,))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return BaseService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def delete_color(color_id):
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM Colors WHERE ColorID = %s', (color_id,))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            msg = 'Không thể xóa màu này vì đang được sử dụng.' if 'foreign key constraint' in str(e).lower() else None
            return BaseService.handle_error(e, msg)
        finally:
            conn.close()

    @staticmethod
    def delete_size(size_id):
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM Sizes WHERE SizeID = %s', (size_id,))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            msg = 'Không thể xóa kích thước này vì đang được sử dụng.' if 'foreign key constraint' in str(e).lower() else None
            return BaseService.handle_error(e, msg)
        finally:
            conn.close()
