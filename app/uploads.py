from io import BytesIO
from pathlib import Path
import re
import secrets
from time import time
from urllib.parse import unquote

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

from app.validation import ValidationError


IMAGE_FORMATS = {
    'PNG': ('png', 'image/png'),
    'JPEG': ('jpg', 'image/jpeg'),
    'GIF': ('gif', 'image/gif'),
    'WEBP': ('webp', 'image/webp'),
}
PRODUCT_IMAGE_NAME = re.compile(r'(?:pixabay|gallery)-[1-9][0-9]*-[0-9a-f]{32}\.jpg')
PRODUCT_IMAGE_LOCK = "SELECT pg_advisory_xact_lock(hashtext('thua_product_uploads'))"


def managed_product_image(value):
    name = value.removeprefix('/static/').removeprefix('images/')
    return name if PRODUCT_IMAGE_NAME.fullmatch(name) else None


def product_image_file_exists(name):
    path = upload_root() / 'products' / name
    if not path.parent.is_symlink() and not path.is_symlink() and path.is_file():
        return True
    static_folder = current_app.static_folder
    return bool(static_folder and (Path(static_folder) / 'images' / name).is_file())


def expired_product_uploads():
    directory = upload_root() / 'products'
    if directory.is_symlink():
        return []
    stale = []
    cutoff = time() - 24 * 60 * 60
    for path in directory.glob('*.jpg'):
        try:
            if PRODUCT_IMAGE_NAME.fullmatch(path.name) and not path.is_symlink() and path.stat().st_mtime < cutoff:
                stale.append(path)
                if len(stale) == 64:
                    break
        except OSError:
            continue
    return stale


def remove_unused_product_uploads(cursor, paths):
    # Saving an uploaded image uses the same lock and rechecks that its file exists.
    cursor.execute(PRODUCT_IMAGE_LOCK)
    cursor.execute(
        'SELECT ImageURL FROM Products WHERE ImageURL IS NOT NULL UNION ALL SELECT image_url FROM ProductGallery'
    )
    references = {unquote(row[0].split('?', 1)[0].split('#', 1)[0]).rsplit('/', 1)[-1] for row in cursor.fetchall()}
    for path in paths:
        if path.name not in references:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                current_app.logger.warning('Could not remove an expired product upload')


def upload_root() -> Path:
    return Path(current_app.config.get('UPLOAD_ROOT') or Path(current_app.instance_path) / 'uploads').resolve()


def image_bytes(raw, *, max_side=None):
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
            rgb = ImageOps.exif_transpose(image).convert('RGB')
            if max_side is not None:
                rgb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            rgb.save(output, 'JPEG', quality=90)
            return output.getvalue(), 'jpg', 'image/jpeg'
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError('Nội dung ảnh không hợp lệ') from exc


def save_image(file, subdir='avatars', *, prefix='', max_side=None):
    if file is None or not file.filename:
        raise ValidationError('Chưa chọn file ảnh')
    raw = file.stream.read(current_app.config.get('MAX_CONTENT_LENGTH', 5 * 1024 * 1024) + 1)
    cleaned, extension, _ = image_bytes(raw, max_side=max_side)
    directory = upload_root() / subdir
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValidationError('Không thể lưu ảnh')
    filename = f'{prefix}{secrets.token_hex(16)}.{extension}'
    path = directory / filename
    with path.open('xb') as output:
        output.write(cleaned)
    return path, f'/uploads/{subdir}/{filename}'
