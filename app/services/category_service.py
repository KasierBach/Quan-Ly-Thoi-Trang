from app.cache import cached

from .base_service import BaseService


class CategoryService(BaseService):
    @staticmethod
    @cached(timeout=600, key_prefix='categories:')
    def get_all_categories():
        """Failures are handled by the route, not cached as an empty catalog."""
        conn = CategoryService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT CategoryID, CategoryName FROM Categories ORDER BY CategoryName, CategoryID')
                return list(cursor.fetchall())
        finally:
            conn.close()
