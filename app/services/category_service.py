from app.services.base_service import BaseService

class CategoryService(BaseService):
    @staticmethod
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
            return categories
        except Exception as e:
            print(f"Error fetching categories: {e}")
            return []
        finally:
            cursor.close()
            conn.close()
