from io import BytesIO
from pathlib import Path
import secrets

from flask import current_app
from PIL import Image, UnidentifiedImageError

from app.validation import ValidationError


IMAGE_FORMATS = {
    'PNG': ('png', 'image/png'),
    'JPEG': ('jpg', 'image/jpeg'),
    'GIF': ('gif', 'image/gif'),
    'WEBP': ('webp', 'image/webp'),
}


def image_bytes(raw):
    if not raw or len(raw) > current_app.config.get('MAX_CONTENT_LENGTH', 5 * 1024 * 1024):
        raise ValidationError('Ảnh vượt giới hạn dung lượng')
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in IMAGE_FORMATS or image.width * image.height > 20_000_000:
                raise ValidationError('Ảnh không hợp lệ')
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            image.seek(0)
            image.load()
            output = BytesIO()
            image.convert('RGB').save(output, 'JPEG', quality=90)
            return output.getvalue(), 'jpg', 'image/jpeg'
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError('Nội dung ảnh không hợp lệ') from exc


def save_image(file, subdir='avatars'):
    if file is None or not file.filename:
        raise ValidationError('Chưa chọn file ảnh')
    raw = file.stream.read(current_app.config.get('MAX_CONTENT_LENGTH', 5 * 1024 * 1024) + 1)
    cleaned, extension, _ = image_bytes(raw)
    root = Path(current_app.config.get('UPLOAD_ROOT') or Path(current_app.instance_path) / 'uploads')
    directory = root / subdir
    directory.mkdir(parents=True, exist_ok=True)
    filename = f'{secrets.token_hex(16)}.{extension}'
    path = directory / filename
    with path.open('xb') as output:
        output.write(cleaned)
    return path, f'/uploads/{subdir}/{filename}'
