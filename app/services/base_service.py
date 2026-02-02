from app.database import get_db_connection
import psycopg2
from typing import Any, Dict

class BaseService:
    @staticmethod
    def get_connection():
        """Get a database connection."""
        return get_db_connection()

    @staticmethod
    def handle_error(e: Exception, message: str = "Đã xảy ra lỗi hệ thống") -> Dict[str, Any]:
        """Generic error handler for services."""
        print(f"Service Error: {str(e)}")
        return {
            'success': False,
            'message': message,
            'error': str(e)
        }

    @staticmethod
    def success(data: Any = None, message: str = "Thành công") -> Dict[str, Any]:
        """Generic success response for services."""
        res = {'success': True, 'message': message}
        if data is not None:
            if isinstance(data, dict):
                res.update(data)
            else:
                res['data'] = data
        return res
