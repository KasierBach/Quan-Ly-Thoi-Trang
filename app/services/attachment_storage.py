"""Private chat attachment storage primitives without conversation/message dependencies."""

import re

from flask import current_app

from app.uploads import upload_root
from app.validation import ValidationError


def storage_path(storage_name):
    if not isinstance(storage_name, str) or not re.fullmatch(r'[0-9a-f]{32}\.[a-z0-9]{2,5}', storage_name):
        raise ValidationError('Đường dẫn tệp không hợp lệ')
    root = upload_root()
    directory = root / 'chat'
    path = directory / storage_name
    if (
        directory.is_symlink()
        or path.is_symlink()
        or path.resolve().parent != directory.resolve()
        or directory.resolve().parent != root
    ):
        raise ValidationError('Đường dẫn tệp không hợp lệ')
    return path


def insert_attachment(cursor, message_id, attachment):
    name = attachment.get('storage_name')
    storage_path(name)
    cursor.execute(
        """
        INSERT INTO Attachments (message_id, file_url, file_name, file_type, file_size, mime_type, storage_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (
            message_id,
            '',
            attachment['file_name'],
            attachment['file_type'],
            attachment['file_size'],
            attachment['mime_type'],
            name,
        ),
    )
    attachment_id = cursor.fetchone().id
    url = f'/api/chat/attachments/{attachment_id}'
    cursor.execute('UPDATE Attachments SET file_url = %s WHERE id = %s', (url, attachment_id))
    return {
        'id': attachment_id,
        'file_url': url,
        'file_name': attachment['file_name'],
        'file_type': attachment['file_type'],
        'file_size': attachment['file_size'],
        'mime_type': attachment['mime_type'],
    }


def delete_records(cursor, message_id):
    cursor.execute('DELETE FROM Attachments WHERE message_id = %s RETURNING storage_name', (message_id,))
    return [row.storage_name for row in cursor.fetchall()]


def cleanup_files(storage_names):
    for name in storage_names:
        if not name:
            continue
        try:
            storage_path(name).unlink(missing_ok=True)
        except (OSError, ValidationError):
            current_app.logger.exception('Could not remove a private chat attachment')
