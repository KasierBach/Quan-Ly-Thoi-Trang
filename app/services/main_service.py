from hashlib import sha256

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
                    SELECT MessageID, Name, Email, Subject, Message, SubmitDate, Status,
                           delivery.delivery_status, delivery.delivery_reference
                    FROM ContactMessages
                    LEFT JOIN LATERAL (
                        SELECT delivery_status, delivery_id::text AS delivery_reference
                        FROM ContactReplyDeliveries WHERE contact_id = ContactMessages.MessageID
                        ORDER BY started_at DESC, delivery_id DESC LIMIT 1
                    ) delivery ON TRUE{where}
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
    def reserve_contact_reply(message_id, reply):
        digest = sha256(reply.encode('utf-8')).hexdigest()
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ContactReplyDeliveries (contact_id, reply_digest)
                    VALUES (%s, %s) ON CONFLICT (contact_id, reply_digest) DO NOTHING
                    RETURNING delivery_id::text, delivery_status
                    """,
                    (message_id, digest),
                )
                delivery = cursor.fetchone()
                claimed = delivery is not None
                if not claimed:
                    cursor.execute(
                        """SELECT delivery_id::text, delivery_status FROM ContactReplyDeliveries
                           WHERE contact_id = %s AND reply_digest = %s""",
                        (message_id, digest),
                    )
                    delivery = cursor.fetchone()
                conn.commit()
                return claimed, delivery[0], delivery[1]
        finally:
            conn.close()

    @staticmethod
    def finish_contact_reply(delivery_id, sent):
        conn = MainService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """UPDATE ContactReplyDeliveries SET delivery_status = %s, finished_at = CURRENT_TIMESTAMP
                       WHERE delivery_id = %s AND delivery_status = 'Sending' RETURNING contact_id""",
                    ('Sent' if sent else 'Failed', delivery_id),
                )
                delivery = cursor.fetchone()
                if delivery is not None and sent:
                    cursor.execute(
                        "UPDATE ContactMessages SET Status = 'Answered' WHERE MessageID = %s", (delivery[0],)
                    )
                conn.commit()
        finally:
            conn.close()

    @staticmethod
    def check_health():
        """Report readiness only once the database has the required schema."""
        conn = None
        try:
            conn = MainService.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""SELECT
                    NOT EXISTS (
                        SELECT 1 FROM (VALUES
                            ('contactmessages', 'SELECT'),
                            ('contactmessages', 'UPDATE'),
                            ('contactreplydeliveries', 'SELECT'),
                            ('contactreplydeliveries', 'INSERT'),
                            ('contactreplydeliveries', 'UPDATE'),
                            ('customers', 'SELECT'),
                            ('customers', 'INSERT'),
                            ('customers', 'UPDATE'),
                            ('products', 'SELECT'),
                            ('productgallery', 'SELECT'),
                            ('productgallery', 'INSERT'),
                            ('productgallery', 'DELETE'),
                            ('categorysizemeasurements', 'SELECT'),
                            ('categorysizemeasurements', 'INSERT'),
                            ('categorysizemeasurements', 'UPDATE'),
                            ('categorysizemeasurements', 'DELETE'),
                            ('orderstatusevents', 'SELECT'),
                            ('orderstatusevents', 'INSERT'),
                            ('productvariants', 'SELECT'),
                            ('productvariants', 'INSERT'),
                            ('productvariants', 'UPDATE'),
                            ('attachments', 'SELECT'),
                            ('oauthidentities', 'SELECT'),
                            ('oauthstates', 'INSERT'),
                            ('orders', 'SELECT'),
                            ('orders', 'INSERT'),
                            ('orders', 'UPDATE'),
                            ('orderdetails', 'SELECT'),
                            ('orderdetails', 'INSERT'),
                            ('inventoryadjustments', 'SELECT'),
                            ('inventoryadjustments', 'INSERT'),
                            ('passwordresettokens', 'SELECT'),
                            ('passwordresettokens', 'INSERT'),
                            ('passwordresettokens', 'UPDATE'),
                            ('shoppingcarts', 'SELECT'),
                            ('shoppingcarts', 'INSERT'),
                            ('shoppingcarts', 'UPDATE')
                        ) AS required(relation, privilege)
                        WHERE has_table_privilege(to_regclass(relation), privilege) IS NOT TRUE
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM (VALUES
                            ('orders', 'orderid'), ('orderdetails', 'orderdetailid'),
                            ('customers', 'customerid'), ('passwordresettokens', 'tokenid'),
                            ('productvariants', 'variantid')
                        ) AS required(relation, column_name)
                        WHERE has_sequence_privilege(
                            to_regclass(pg_get_serial_sequence(relation, column_name)), 'USAGE'
                        ) IS NOT TRUE
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM (VALUES
                            ('sp_addorderdetail(integer,integer,integer)'),
                            ('sp_updateorderstatus(integer,character varying)'),
                            ('sp_addproductvariant(integer,integer,integer,integer)')
                        ) AS required(signature)
                        WHERE has_function_privilege(to_regprocedure(signature), 'EXECUTE') IS NOT TRUE
                    )
                    AND to_regclass('uq_inventory_adjustments_operation') IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgrelid = to_regclass('orders') AND tgname = 'trg_recordorderstatus'
                          AND tgenabled IN ('O', 'A')
                    )
                    AND EXISTS (
                        SELECT 1 FROM pg_attribute
                        WHERE attrelid = to_regclass('productvariants') AND attname = 'low_stock_threshold'
                          AND attnotnull AND NOT attisdropped
                    )
                    AND EXISTS (
                        SELECT 1 FROM pg_index AS checkout_index
                        JOIN pg_attribute AS checkout_key
                          ON checkout_key.attrelid = checkout_index.indrelid
                         AND checkout_key.attnum = checkout_index.indkey[0]
                        WHERE checkout_index.indrelid = to_regclass('orders')
                          AND checkout_index.indexrelid = to_regclass('uq_orders_checkout_key')
                          AND checkout_index.indisvalid AND checkout_index.indisunique
                          AND checkout_index.indimmediate AND checkout_index.indpred IS NULL
                          AND checkout_index.indnkeyatts = 1
                          AND checkout_key.attname = 'checkout_key' AND checkout_key.atttypid = 'uuid'::regtype
                    )
                    AND EXISTS (
                        SELECT 1 FROM pg_constraint
                        JOIN pg_attribute ON attrelid = conrelid AND attname = 'token' AND NOT attisdropped
                        WHERE conrelid = to_regclass('passwordresettokens')
                          AND conname = 'passwordresettokens_sha256'
                          AND atttypid = 'varchar'::regtype
                          AND convalidated
                    )""")
                return cursor.fetchone()[0] is True
        except Exception:
            return False
        finally:
            if conn is not None:
                conn.close()
