from .base_service import BaseService
from typing import Optional, Dict, Any

class AttachmentService(BaseService):
    @staticmethod
    def add_attachment(
        message_id: int,
        file_url: str,
        file_name: str,
        file_type: str,
        file_size: int,
        thumbnail_url: Optional[str] = None,
        mime_type: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> Dict[str, Any]:
        """Add an attachment to a message."""
        conn = AttachmentService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO Attachments (
                    message_id, file_url, file_name, file_type, file_size, 
                    thumbnail_url, mime_type, width, height
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (message_id, file_url, file_name, file_type, file_size, 
                  thumbnail_url, mime_type, width, height))
            attachment_id = cursor.fetchone().id
            conn.commit()
            return AttachmentService.success({'id': attachment_id})
        except Exception as e:
            conn.rollback()
            return AttachmentService.handle_error(e, "Lỗi khi lưu tệp đính kèm")
        finally:
            conn.close()

    @staticmethod
    def get_message_attachments(message_id: int) -> list:
        """Fetch all files attached to a specific message."""
        conn = AttachmentService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM Attachments WHERE message_id = %s', (message_id,))
            return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def delete_attachments_by_message_id(message_id: int, app_root: str) -> bool:
        """Permanently delete physical files and DB records for a message."""
        import os
        from urllib.parse import urlparse

        attachments = AttachmentService.get_message_attachments(message_id)
        if not attachments:
            return True

        conn = AttachmentService.get_connection()
        cursor = conn.cursor()
        try:
            for att in attachments:
                # 1. Delete physical file
                # URL is likely /static/uploads/chat/filename or http://domain/static/...
                # We need to extract relative path from 'static'
                file_url = att.file_url
                parsed = urlparse(file_url)
                path_parts = parsed.path.split('/static/')
                
                if len(path_parts) > 1:
                    relative_path = path_parts[1] # e.g., 'uploads/chat/filename.png'
                    full_path = os.path.join(app_root, 'static', relative_path)
                    
                    if os.path.exists(full_path):
                        try:
                            os.remove(full_path)
                            print(f"Deleted file: {full_path}")
                        except Exception as e:
                            print(f"Error deleting file {full_path}: {e}")
                
                # 2. Delete DB record
                cursor.execute('DELETE FROM Attachments WHERE id = %s', (att.id,))
            
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"Error deleting attachments: {e}")
            return False
        finally:
            conn.close()
