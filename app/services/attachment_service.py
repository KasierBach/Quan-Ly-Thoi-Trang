from io import BytesIO
import secrets
from typing import Any
from zipfile import BadZipFile, ZipFile

from flask import current_app
import psycopg2
from werkzeug.utils import secure_filename

from app.uploads import image_bytes
from app.validation import ValidationError, positive_int, required_text
from . import attachment_storage
from .base_service import BaseService
from .chat_service import ChatService
from .conversation_service import ChatAccessError, ConversationService, get_identity


class AttachmentService(BaseService):
    @staticmethod
    def storage_path(storage_name):
        return attachment_storage.storage_path(storage_name)

    @staticmethod
    def prepare_upload(file) -> dict[str, Any]:
        if file is None or not file.filename:
            raise ValidationError('Chưa chọn tệp')
        original = required_text(file.filename, 'Tên tệp', 255)
        filename = secure_filename(original.replace('\\', '/').rsplit('/', 1)[-1])
        if not filename or '.' not in filename:
            raise ValidationError('Tên tệp không hợp lệ')
        extension = filename.rsplit('.', 1)[-1].lower()
        limit = min(
            current_app.config.get('CHAT_UPLOAD_MAX_BYTES', 5 * 1024 * 1024),
            current_app.config.get('MAX_CONTENT_LENGTH') or 5 * 1024 * 1024,
        )
        raw = file.stream.read(limit + 1)
        if not raw or len(raw) > limit:
            raise ValidationError('Tệp trống hoặc vượt giới hạn dung lượng')
        mime = file.mimetype or ''
        if extension in {'jpg', 'jpeg', 'png', 'gif', 'webp'}:
            raw, extension, mime = image_bytes(raw)
            filename = f'{filename.rsplit(".", 1)[0]}.{extension}'
            file_type = 'image'
        else:
            file_type, mime = AttachmentService._validated_type(raw, extension, mime)
        storage_name = f'{secrets.token_hex(16)}.{extension}'
        path = AttachmentService.storage_path(storage_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('xb') as output:
                output.write(raw)
        except FileExistsError:
            # A filename collision belongs to an earlier upload, not this request.
            raise
        except OSError:
            path.unlink(missing_ok=True)
            raise
        return {
            'storage_name': storage_name,
            'file_url': '',
            'file_name': filename,
            'file_type': file_type,
            'file_size': len(raw),
            'mime_type': mime,
        }

    @staticmethod
    def _validated_type(raw, extension, declared_mime):
        if extension == 'pdf' and raw.startswith(b'%PDF-'):
            return 'file', 'application/pdf'
        if extension == 'txt':
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError as exc:
                raise ValidationError('Nội dung văn bản không hợp lệ') from exc
            if '\x00' in text or any(ord(char) < 32 and char not in '\r\n\t' for char in text):
                raise ValidationError('Nội dung văn bản không hợp lệ')
            return 'file', 'text/plain'
        if extension in {'zip', 'docx', 'xlsx'} and raw.startswith(b'PK\x03\x04'):
            try:
                with ZipFile(BytesIO(raw)) as archive:
                    entries = archive.infolist()
                    if len(entries) > 2000 or sum(item.file_size for item in entries) > 50 * 1024 * 1024:
                        raise ValidationError('Tệp nén vượt giới hạn')
                    names = {item.filename for item in entries}
                    if any(
                        name.startswith(('/', '\\')) or '..' in name.replace('\\', '/').split('/') for name in names
                    ):
                        raise ValidationError('Tệp nén có đường dẫn không hợp lệ')
                    if extension == 'docx' and not {'[Content_Types].xml', 'word/document.xml'} <= names:
                        raise ValidationError('Tệp Word không hợp lệ')
                    if extension == 'xlsx' and not {'[Content_Types].xml', 'xl/workbook.xml'} <= names:
                        raise ValidationError('Tệp Excel không hợp lệ')
            except BadZipFile as exc:
                raise ValidationError('Tệp nén không hợp lệ') from exc
            return 'file', {
                'zip': 'application/zip',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            }[extension]
        if extension in {'doc', 'xls'} and raw.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
            return 'file', 'application/msword' if extension == 'doc' else 'application/vnd.ms-excel'
        if extension == 'rar' and raw.startswith((b'Rar!\x1a\x07\x00', b'Rar!\x1a\x07\x01\x00')):
            return 'file', 'application/vnd.rar'
        if extension == 'wav' and raw.startswith(b'RIFF') and raw[8:12] == b'WAVE':
            return 'audio', 'audio/wav'
        if extension == 'ogg' and raw.startswith(b'OggS'):
            return 'audio', 'audio/ogg'
        if extension == 'mp3' and (raw.startswith(b'ID3') or (len(raw) > 2 and raw[0] == 255 and raw[1] & 224 == 224)):
            return 'audio', 'audio/mpeg'
        if extension == 'webm' and raw.startswith(b'\x1aE\xdf\xa3') and b'webm' in raw[:4096].lower():
            return ('audio', 'audio/webm') if declared_mime.startswith('audio/webm') else ('video', 'video/webm')
        if extension in {'mp4', 'mov', 'm4a'} and raw[4:8] == b'ftyp' and len(raw) >= 16:
            return (
                ('audio', 'audio/mp4')
                if extension == 'm4a'
                else ('video', 'video/quicktime' if extension == 'mov' else 'video/mp4')
            )
        raise ValidationError('Loại tệp hoặc nội dung không hợp lệ')

    @staticmethod
    def insert_attachment(cursor, message_id, attachment):
        return attachment_storage.insert_attachment(cursor, message_id, attachment)

    @staticmethod
    def get_attachment(attachment_id, *, actor=None):
        actor = actor or get_identity()
        conn = AttachmentService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT a.*, m.conversation_id, m.session_id, m.is_deleted
                    FROM Attachments a JOIN Messages m ON m.id = a.message_id WHERE a.id = %s
                """,
                    (positive_int(attachment_id, 'Tệp', 2147483647),),
                )
                row = cursor.fetchone()
                if row is None or row.is_deleted:
                    raise ChatAccessError('Tệp không tồn tại', 404)
                ConversationService.get_access(row.conversation_id, row.session_id, actor=actor, cursor=cursor)
                # Legacy public/static attachments are not exposed as private downloads.
                if not row.storage_name:
                    raise ChatAccessError('Tệp cần được tải lên lại', 404)
                return dict(row)
        finally:
            conn.close()

    @staticmethod
    def get_message_attachments(message_id, *, actor=None) -> list[dict[str, Any]]:
        actor = actor or get_identity()
        conn = AttachmentService.get_connection()
        try:
            with conn.cursor() as cursor:
                ChatService.get_message_access(message_id, actor=actor, cursor=cursor)
                cursor.execute(
                    'SELECT id, file_url, file_name, file_type, file_size, mime_type FROM Attachments WHERE message_id = %s AND storage_name IS NOT NULL',
                    (message_id,),
                )
                return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def delete_attachments_by_message_id(message_id, app_root=None, *, actor=None) -> bool:
        # Deletion and recall share one DB transaction; physical cleanup happens after commit.
        actor = actor or get_identity()
        conn = AttachmentService.get_connection()
        cleanup = []
        try:
            with conn.cursor() as cursor:
                ChatService.get_message_access(message_id, actor=actor, permission='recall', cursor=cursor)
                cleanup = AttachmentService.delete_records(cursor, message_id)
            conn.commit()
        except ChatAccessError:
            conn.rollback()
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            AttachmentService.handle_error(exc)
            return False
        finally:
            conn.close()
        AttachmentService.cleanup_files(cleanup)
        return True

    @staticmethod
    def delete_records(cursor, message_id):
        return attachment_storage.delete_records(cursor, message_id)

    @staticmethod
    def cleanup_files(storage_names):
        return attachment_storage.cleanup_files(storage_names)
