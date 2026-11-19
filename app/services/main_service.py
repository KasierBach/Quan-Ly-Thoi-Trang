from app.validation import ValidationError, email_address, positive_int, required_text

from .base_service import BaseService


class MainService(BaseService):
    CONTACT_STATUSES = {'New', 'Processing', 'Answered'}

    @staticmethod
    def validate_contact(name, email, subject, message):
        name = required_text(name, 'Họ và tên', 100)
        email = email_address(email)
        if subject is None or subject == '':
            subject = None
        else:
            subject = required_text(subject, 'Tiêu đề', 200)
        message = required_text(message, 'Nội dung', 5000)
        return name, email, subject, message

    @staticmethod
    def add_contact_message(name, email, subject, message):
        """Validate and save a contact; receipt is not an email-delivery claim."""
        name, email, subject, message = MainService.validate_contact(name, email, subject, message)
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ContactMessages (Name, Email, Subject, Message, SubmitDate, Status)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, 'New')
                """,
                    (name, email, subject, message),
                )
                conn.commit()
                return MainService.success(message='Đã lưu tin nhắn liên hệ của bạn')
        except Exception as exc:
            conn.rollback()
            result = MainService.handle_error(exc)
            result['status_code'] = 500
            return result
        finally:
            conn.close()

    @staticmethod
    def subscribe_newsletter(email):
        """Store a normalized address once, including concurrent subscriptions."""
        email = email_address(email)
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO NewsletterSubscribers (Email, SubscribeDate, IsActive)
                    VALUES (%s, CURRENT_TIMESTAMP, TRUE)
                    ON CONFLICT DO NOTHING
                    RETURNING Email
                """,
                    (email,),
                )
                inserted = cursor.fetchone()
                conn.commit()
                return MainService.success(message='Đã lưu đăng ký nhận tin' if inserted else 'Email đã đăng ký')
        except Exception as exc:
            conn.rollback()
            result = MainService.handle_error(exc)
            result['status_code'] = 500
            return result
        finally:
            conn.close()

    @staticmethod
    def validate_contact_status(status, allow_all=False):
        if allow_all and status in (None, ''):
            return ''
        if not isinstance(status, str) or status not in MainService.CONTACT_STATUSES:
            raise ValidationError('Trạng thái tin nhắn không hợp lệ')
        return status

    @staticmethod
    def get_contact_messages(status_filter=None, page=1, per_page=20):
        status_filter = MainService.validate_contact_status(status_filter, allow_all=True)
        page = positive_int(page, 'Trang', max_value=1000000)
        per_page = positive_int(per_page, 'Số dòng', max_value=100)
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                where = ' WHERE Status = %s' if status_filter else ''
                params = [status_filter] if status_filter else []
                cursor.execute(f'SELECT COUNT(*) FROM ContactMessages{where}', params)
                total = cursor.fetchone()[0]
                total_pages = max(1, (total + per_page - 1) // per_page)
                page = min(page, total_pages)
                offset = (page - 1) * per_page
                cursor.execute(
                    f"""
                    SELECT MessageID, Name, Email, Subject, Message, SubmitDate, Status
                    FROM ContactMessages{where}
                    ORDER BY SubmitDate DESC, MessageID DESC LIMIT %s OFFSET %s
                """,
                    params + [per_page, offset],
                )
                return {
                    'messages': cursor.fetchall(),
                    'total_records': total,
                    'total_pages': total_pages,
                    'current_page': page,
                    'per_page': per_page,
                    'start_index': offset + 1 if total else 0,
                    'end_index': min(offset + per_page, total),
                }
        finally:
            conn.close()

    @staticmethod
    def get_contact_message(message_id):
        message_id = positive_int(message_id, 'Tin nhắn', max_value=2147483647)
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT MessageID, Name, Email, Subject, Message, SubmitDate, Status
                    FROM ContactMessages WHERE MessageID = %s
                """,
                    (message_id,),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def update_contact_message_status(message_id, new_status):
        message_id = positive_int(message_id, 'Tin nhắn', max_value=2147483647)
        new_status = MainService.validate_contact_status(new_status)
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE ContactMessages SET Status = %s WHERE MessageID = %s RETURNING MessageID
                """,
                    (new_status, message_id),
                )
                if not cursor.fetchone():
                    conn.rollback()
                    return {'success': False, 'message': 'Tin nhắn không tồn tại', 'status_code': 404}
                conn.commit()
                return MainService.success(message='Cập nhật trạng thái thành công')
        except Exception as exc:
            conn.rollback()
            result = MainService.handle_error(exc)
            result['status_code'] = 500
            return result
        finally:
            conn.close()

    @staticmethod
    def check_health():
        """A connection failure is an unhealthy result, not an uncaught exception."""
        conn = None
        try:
            conn = MainService.get_connection()
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1')
                return cursor.fetchone()[0] == 1
        except Exception:
            return False
        finally:
            if conn is not None:
                conn.close()
