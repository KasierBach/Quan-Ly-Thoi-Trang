from app.services.base_service import BaseService
from app.cache import cached

class CategoryService(BaseService):
    @staticmethod
    @cached(timeout=600, key_prefix='categories:')  # Cache for 10 minutes
    def get_all_categories():
        """
        Retrieve all categories from the database.
        Returns a list of category records.
        """
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM Categories')
            categories = cursor.fetchall()
            # Return as list (CaseInsensitiveRecord already works with Jinja2)
            return list(categories)
        except Exception as e:
            print(f"Error fetching categories: {e}")
            return []
        finally:
            cursor.close()
            conn.close()
