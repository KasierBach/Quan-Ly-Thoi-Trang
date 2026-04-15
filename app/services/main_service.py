from .base_service import BaseService

class MainService(BaseService):
    @staticmethod
    def add_contact_message(name, email, subject, message):
        """Save a contact message to the database."""
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO ContactMessages (Name, Email, Subject, Message, SubmitDate, Status)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, 'New')
                ''', (name, email, subject, message))
                conn.commit()
                return MainService.success()
        except Exception as e:
            conn.rollback()
            return MainService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def subscribe_newsletter(email):
        """Add a new email subscriber to the newsletter database."""
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1 FROM NewsletterSubscribers WHERE Email = %s', (email,))
                if cursor.fetchone():
                    return MainService.success(message="Email đã đăng ký")
                
                cursor.execute('''
                    INSERT INTO NewsletterSubscribers (Email, SubscribeDate, IsActive)
                    VALUES (%s, CURRENT_TIMESTAMP, TRUE)
                ''', (email,))
                conn.commit()
                return MainService.success(message="Đăng ký thành công")
        except Exception as e:
            conn.rollback()
            return MainService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def get_contact_messages(status_filter=None):
        """Fetch contact messages with optional status filter."""
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                query = 'SELECT * FROM ContactMessages'
                params = []
                if status_filter:
                    query += " WHERE Status = %s"
                    params.append(status_filter)
                query += " ORDER BY SubmitDate DESC"
                cursor.execute(query, params)
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def update_contact_message_status(message_id, new_status):
        """Update the status of a contact message."""
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE ContactMessages SET Status = %s WHERE MessageID = %s', (new_status, message_id))
                conn.commit()
                return {'success': True, 'message': 'Cập nhật trạng thái thành công'}
        except Exception as e:
            conn.rollback()
            return MainService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def check_health():
        """Check database connectivity for health monitoring."""
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1')
                return True
        except Exception:
            return False
        finally:
            conn.close()
