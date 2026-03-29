from app.services.base_service import BaseService
from werkzeug.security import generate_password_hash, check_password_hash
from flask import current_app
from datetime import datetime, timedelta
import uuid

class AuthService(BaseService):
    @staticmethod
    def login_user(email, password):
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT CustomerID, FullName, Password, IsAdmin, Role, DarkModeEnabled FROM Customers WHERE Email = %s', (email,))
                user = cursor.fetchone()
                
                if user and check_password_hash(user.Password, password):
                    return user
                return None
        finally:
            conn.close()

    @staticmethod
    def register_user(full_name, email, password, phone, address):
        encrypted_password = generate_password_hash(password)
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                # Check email
                cursor.execute('SELECT CustomerID FROM Customers WHERE Email = %s', (email,))
                if cursor.fetchone():
                    return {'success': False, 'message': 'Email đã tồn tại'}

                cursor.execute('SELECT sp_AddCustomer(%s, %s, %s, %s, %s) AS CustomerID', 
                             (full_name, email, encrypted_password, phone, address))
                result = cursor.fetchone()
                conn.commit()
                return {'success': True, 'customer_id': result.CustomerID, 'full_name': full_name}
        except Exception as e:
            conn.rollback()
            return AuthService.handle_error(e, "Lỗi khi đăng ký tài khoản")
        finally:
            conn.close()

    @staticmethod
    def update_profile(user_id, full_name, phone, gender, dob):
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                if phone:
                    cursor.execute('SELECT CustomerID FROM Customers WHERE PhoneNumber = %s AND CustomerID != %s', (phone, user_id))
                    if cursor.fetchone():
                        return {'success': False, 'message': 'Số điện thoại đã được sử dụng'}

                cursor.execute('''
                    UPDATE Customers SET FullName = %s, PhoneNumber = %s, Gender = %s, DateOfBirth = %s
                    WHERE CustomerID = %s
                ''', (full_name, phone, gender, dob if dob else None, user_id))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return AuthService.handle_error(e, "Lỗi khi cập nhật thông tin")
        finally:
            conn.close()

    @staticmethod
    def update_address(user_id, address):
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE Customers SET Address = %s WHERE CustomerID = %s', (address, user_id))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return AuthService.handle_error(e, "Lỗi khi cập nhật địa chỉ")
        finally:
            conn.close()

    @staticmethod
    def change_password(user_id, current_password, new_password):
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT Password FROM Customers WHERE CustomerID = %s', (user_id,))
                user = cursor.fetchone()
                if not user or not check_password_hash(user.Password, current_password):
                    return {'success': False, 'message': 'Mật khẩu hiện tại không đúng'}

                hashed = generate_password_hash(new_password)
                cursor.execute('UPDATE Customers SET Password = %s WHERE CustomerID = %s', (hashed, user_id))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return AuthService.handle_error(e, "Lỗi khi đổi mật khẩu")
        finally:
            conn.close()

    @staticmethod
    def create_password_reset_token(email):
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT CustomerID, FullName FROM Customers WHERE Email = %s', (email,))
                user = cursor.fetchone()
                if not user: return None
                
                token = str(uuid.uuid4())
                cursor.execute('''
                    INSERT INTO PasswordResetTokens (CustomerID, Token, ExpiryDate)
                    VALUES (%s, %s, %s)
                ''', (user.CustomerID, token, datetime.now() + timedelta(hours=24)))
                conn.commit()
                return {'token': token, 'full_name': user.FullName, 'email': email}
        finally:
            conn.close()

    @staticmethod
    def get_customer_profile(user_id):
        """Fetch complete customer profile data."""
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM Customers WHERE CustomerID = %s', (user_id,))
                return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def update_avatar(user_id, avatar_url):
        """Update customer's avatar URL."""
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE Customers SET AvatarUrl = %s WHERE CustomerID = %s', (avatar_url, user_id))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return AuthService.handle_error(e, "Lỗi khi cập nhật ảnh đại diện")
        finally:
            conn.close()

    @staticmethod
    def toggle_dark_mode(user_id, enabled):
        """Toggle dark mode preference for a customer."""
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE Customers SET DarkModeEnabled = %s WHERE CustomerID = %s', (bool(enabled), user_id))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return AuthService.handle_error(e, "Lỗi khi thay đổi chế độ tối")
        finally:
            conn.close()

    @staticmethod
    def reset_password(token, new_password):
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT t.* FROM PasswordResetTokens t
                    WHERE t.Token = %s AND t.ExpiryDate > CURRENT_TIMESTAMP AND t.IsUsed = FALSE
                ''', (token,))
                token_data = cursor.fetchone()
                if not token_data: return {'success': False, 'message': 'Token không hợp lệ hoặc đã hết hạn'}

                hashed = generate_password_hash(new_password)
                cursor.execute('UPDATE Customers SET Password = %s WHERE CustomerID = %s', (hashed, token_data.CustomerID))
                cursor.execute('UPDATE PasswordResetTokens SET IsUsed = TRUE WHERE TokenID = %s', (token_data.TokenID,))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return AuthService.handle_error(e, "Lỗi khi đặt lại mật khẩu")
        finally:
            conn.close()
