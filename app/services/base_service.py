from app.database import get_db_connection

class BaseService:
    @staticmethod
    def get_connection():
        """
        Get a database connection.
        Returns a new connection from the pool/creation function.
        """
        return get_db_connection()
