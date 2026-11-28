from app.database import DatabaseConnection, get_db_connection
from typing import Any, Dict


class BaseService:
    @staticmethod
    def get_connection() -> DatabaseConnection:
        """Get a database connection."""
        return get_db_connection()

    @staticmethod
    def handle_error(e: Exception, message: str = 'Đã xảy ra lỗi hệ thống. Vui lọc thử lại sau.') -> Dict[str, Any]:
        """Generic secure error handler for services."""
        from flask import current_app, g, has_request_context, request

        # Log detailed trace for admins but hide from clients
        current_app.logger.error(
            'Service operation failed (%s) endpoint=%s request_id=%s',
            type(e).__name__,
            request.endpoint if has_request_context() else '-',
            g.get('request_id', '-'),
        )
        return {'success': False, 'message': message}

    @staticmethod
    def success(data: Any = None, message: str = 'Thành công') -> Dict[str, Any]:
        """Generic success response for services."""
        res = {'success': True, 'message': message}
        if data is not None:
            if isinstance(data, dict):
                res.update(data)
            else:
                res['data'] = data
        return res
