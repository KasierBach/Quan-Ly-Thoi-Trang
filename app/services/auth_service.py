from app.services.base_service import BaseService
from werkzeug.security import generate_password_hash, check_password_hash

class AuthService(BaseService):
    @staticmethod
    def login_user(email, password):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            # Added Role to selection
            cursor.execute('SELECT CustomerID, FullName, Password, IsAdmin, Role, DarkModeEnabled FROM Customers WHERE Email = %s', (email,))
            user = cursor.fetchone()
            
            if user and check_password_hash(user.Password, password):
                return user
            return None
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def register_user(full_name, email, password, phone, address):
        encrypted_password = generate_password_hash(password)
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            # Check if email exists
            cursor.execute('SELECT CustomerID FROM Customers WHERE Email = %s', (email,))
            if cursor.fetchone():
                return {'success': False, 'message': 'Email đã tồn tại'}

            # Calls stored procedure sp_AddCustomer
            cursor.execute('''
                SELECT sp_AddCustomer(%s, %s, %s, %s, %s) AS CustomerID
            ''', (full_name, email, encrypted_password, phone, address))
            
            result = cursor.fetchone()
            conn.commit()
            
            return {
                'success': True, 
                'customer_id': result.CustomerID,
                'full_name': full_name
            }
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()
