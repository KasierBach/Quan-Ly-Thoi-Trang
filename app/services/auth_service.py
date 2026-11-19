import hashlib
import secrets
from typing import Any
from datetime import date

import psycopg2
from werkzeug.security import check_password_hash, generate_password_hash

from app.services.base_service import BaseService
from app.validation import (
    ValidationError,
    date_value,
    email_address,
    password_value,
    phone_number,
    positive_int,
    required_text,
)


class AuthService(BaseService):
    @staticmethod
    def login_user(email, password):
        email = email_address(email)
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            return None
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT CustomerID, FullName, Password, IsAdmin,
                           CASE WHEN IsAdmin THEN 'admin' ELSE COALESCE(Role, 'customer') END AS Role,
                           DarkModeEnabled, auth_version AS AuthVersion
                    FROM Customers WHERE LOWER(Email) = %s
                """,
                    (email,),
                )
                user = cursor.fetchone()
                if user and check_password_hash(user.Password, password):
                    return user
                return None
        finally:
            conn.close()

    @staticmethod
    def get_identity_state(user_id):
        user_id = positive_int(user_id, 'Tài khoản')
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT CustomerID, FullName, DarkModeEnabled, auth_version AS AuthVersion,
                           CASE WHEN IsAdmin THEN 'admin' ELSE COALESCE(Role, 'customer') END AS Role
                    FROM Customers WHERE CustomerID = %s
                """,
                    (user_id,),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def register_user(full_name, email, password, phone=None, address=None):
        full_name = required_text(full_name, 'Họ tên', 255)
        email = email_address(email)
        password = password_value(password)
        phone = phone_number(phone, optional=True)
        address = required_text(address, 'Địa chỉ', 500) if address else None
        encrypted = generate_password_hash(password)
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT sp_AddCustomer(%s, %s, %s, %s, %s) AS CustomerID',
                    (full_name, email, encrypted, phone, address),
                )
                result = cursor.fetchone()
                conn.commit()
                return {'success': True, 'customer_id': result.CustomerID, 'full_name': full_name, 'auth_version': 1}
        except psycopg2.IntegrityError:
            conn.rollback()
            return {'success': False, 'message': 'Email hoặc số điện thoại đã được sử dụng'}
        except psycopg2.Error as exc:
            conn.rollback()
            return AuthService.handle_error(exc, 'Không thể đăng ký tài khoản')
        finally:
            conn.close()

    @staticmethod
    def update_profile(user_id, full_name, phone, gender, dob) -> dict[str, Any]:
        full_name = required_text(full_name, 'Họ tên', 255)
        phone = phone_number(phone, optional=True)
        if gender not in {None, '', 'male', 'female', 'other', 'Nam', 'Nữ', 'Khác'}:
            raise ValidationError('Giới tính không hợp lệ')
        birthday = date_value(dob, 'Ngày sinh') if dob else None
        if birthday and birthday > date.today():
            raise ValidationError('Ngày sinh không được ở tương lai')
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE Customers SET FullName = %s, PhoneNumber = %s, Gender = %s, DateOfBirth = %s
                    WHERE CustomerID = %s
                """,
                    (full_name, phone, gender or None, birthday, user_id),
                )
                conn.commit()
                return {'success': True}
        except psycopg2.IntegrityError:
            conn.rollback()
            return {'success': False, 'message': 'Số điện thoại đã được sử dụng'}
        except psycopg2.Error as exc:
            conn.rollback()
            return AuthService.handle_error(exc, 'Không thể cập nhật thông tin')
        finally:
            conn.close()

    @staticmethod
    def update_address(user_id, address) -> dict[str, Any]:
        address = required_text(address, 'Địa chỉ', 500)
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE Customers SET Address = %s WHERE CustomerID = %s', (address, user_id))
                conn.commit()
                return {'success': True}
        except psycopg2.Error as exc:
            conn.rollback()
            return AuthService.handle_error(exc, 'Không thể cập nhật địa chỉ')
        finally:
            conn.close()

    @staticmethod
    def change_password(user_id, current_password, new_password):
        new_password = password_value(new_password)
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT Password FROM Customers WHERE CustomerID = %s FOR UPDATE', (user_id,))
                user = cursor.fetchone()
                if not user or not check_password_hash(user.Password, current_password):
                    return {'success': False, 'message': 'Mật khẩu hiện tại không đúng'}
                cursor.execute(
                    """
                    UPDATE Customers SET Password = %s, auth_version = auth_version + 1
                    WHERE CustomerID = %s RETURNING auth_version AS AuthVersion
                """,
                    (generate_password_hash(new_password), user_id),
                )
                state = cursor.fetchone()
                cursor.execute('UPDATE PasswordResetTokens SET IsUsed = TRUE WHERE CustomerID = %s', (user_id,))
                conn.commit()
                return {'success': True, 'auth_version': state.AuthVersion}
        except psycopg2.Error as exc:
            conn.rollback()
            return AuthService.handle_error(exc, 'Không thể đổi mật khẩu')
        finally:
            conn.close()

    @staticmethod
    def create_password_reset_token(email):
        email = email_address(email)
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT CustomerID, FullName FROM Customers WHERE LOWER(Email) = %s FOR UPDATE', (email,)
                )
                user = cursor.fetchone()
                if not user:
                    return None
                token = secrets.token_urlsafe(32)
                digest = hashlib.sha256(token.encode()).hexdigest()
                cursor.execute('UPDATE PasswordResetTokens SET IsUsed = TRUE WHERE CustomerID = %s', (user.CustomerID,))
                cursor.execute(
                    """
                    INSERT INTO PasswordResetTokens (CustomerID, Token, ExpiryDate)
                    VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '1 hour')
                """,
                    (user.CustomerID, digest),
                )
                conn.commit()
                return {'token': token, 'full_name': user.FullName, 'email': email}
        finally:
            conn.close()

    @staticmethod
    def get_customer_profile(user_id):
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT *, avatar_url AS AvatarUrl FROM Customers WHERE CustomerID = %s', (user_id,))
                return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def update_avatar(user_id, avatar_url):
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE Customers SET avatar_url = %s WHERE CustomerID = %s', (avatar_url, user_id))
                conn.commit()
                return {'success': True}
        except psycopg2.Error as exc:
            conn.rollback()
            return AuthService.handle_error(exc, 'Không thể cập nhật ảnh đại diện')
        finally:
            conn.close()

    @staticmethod
    def toggle_dark_mode(user_id, enabled):
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE Customers SET DarkModeEnabled = %s WHERE CustomerID = %s', (bool(enabled), user_id)
                )
                conn.commit()
                return {'success': True}
        except psycopg2.Error as exc:
            conn.rollback()
            return AuthService.handle_error(exc, 'Không thể thay đổi chế độ tối')
        finally:
            conn.close()

    @staticmethod
    def reset_password(token, new_password) -> dict[str, Any]:
        new_password = password_value(new_password)
        if not isinstance(token, str) or not 20 <= len(token) <= 128:
            return {'success': False, 'message': 'Token không hợp lệ hoặc đã hết hạn'}
        digest = hashlib.sha256(token.encode()).hexdigest()
        conn = AuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT t.* FROM PasswordResetTokens t
                    WHERE t.Token = %s AND t.ExpiryDate > CURRENT_TIMESTAMP AND t.IsUsed = FALSE
                    FOR UPDATE
                """,
                    (digest,),
                )
                record = cursor.fetchone()
                if not record:
                    return {'success': False, 'message': 'Token không hợp lệ hoặc đã hết hạn'}
                cursor.execute(
                    """
                    UPDATE Customers SET Password = %s, auth_version = auth_version + 1
                    WHERE CustomerID = %s
                """,
                    (generate_password_hash(new_password), record.CustomerID),
                )
                cursor.execute(
                    'UPDATE PasswordResetTokens SET IsUsed = TRUE WHERE CustomerID = %s', (record.CustomerID,)
                )
                conn.commit()
                return {'success': True}
        except psycopg2.Error as exc:
            conn.rollback()
            return AuthService.handle_error(exc, 'Không thể đặt lại mật khẩu')
        finally:
            conn.close()
