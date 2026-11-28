import os
from pathlib import Path
import secrets
import tempfile
from urllib.parse import urlsplit, urlunsplit

import requests
from flask import current_app

from app.uploads import image_bytes, upload_root
from app.validation import ValidationError, positive_int, required_text

from .base_service import BaseService


class MediaService(BaseService):
    IMAGE_HOSTS = {'pixabay.com': 'pixabay.com', 'cdn.pixabay.com': 'cdn.pixabay.com'}
    MAX_IMAGE_BYTES = 5 * 1024 * 1024

    @staticmethod
    def pixabay_enabled():
        return (
            not current_app.testing
            and current_app.config.get('PIXABAY_ENABLED', True) is True
            and bool(current_app.config.get('PIXABAY_API_KEY'))
        )

    @staticmethod
    def _disabled():
        return {'success': False, 'message': 'Tìm ảnh Pixabay chưa được cấu hình hoặc đang tắt', 'status_code': 503}

    @staticmethod
    def _url(value, api=False):
        if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 33 for char in value) or '\\' in value:
            raise ValidationError('Địa chỉ ảnh không hợp lệ')
        try:
            parsed = urlsplit(value)
            valid = (
                parsed.scheme == 'https'
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
                and not parsed.fragment
            )
        except ValueError as exc:
            raise ValidationError('Địa chỉ ảnh không hợp lệ') from exc
        if not valid:
            raise ValidationError('Chỉ hỗ trợ địa chỉ HTTPS của Pixabay')
        if api:
            if parsed.hostname == 'pixabay.com' and parsed.path in ('/api', '/api/') and not parsed.query:
                return 'https://pixabay.com/api/' if parsed.path == '/api/' else 'https://pixabay.com/api'
        else:
            host = MediaService.IMAGE_HOSTS.get(parsed.hostname or '')
            if host and parsed.path.strip('/'):
                return urlunsplit(('https', host, parsed.path, parsed.query, ''))
        raise ValidationError('Chỉ hỗ trợ địa chỉ HTTPS của Pixabay')

    @staticmethod
    def _external_error():
        # Requests exceptions can include the API key in their URL; never log that URL.
        current_app.logger.warning('Pixabay request failed or returned invalid content')
        return {
            'success': False,
            'message': 'Không thể tải dữ liệu ảnh từ Pixabay. Vui lòng thử lại sau.',
            'status_code': 502,
        }

    @staticmethod
    def search_pixabay(query):
        query = required_text(query, 'Từ khóa tìm ảnh', 100)
        if not MediaService.pixabay_enabled():
            return MediaService._disabled()
        response = None
        try:
            endpoint = MediaService._url(
                current_app.config.get('PIXABAY_ENDPOINT', 'https://pixabay.com/api/'), api=True
            )
            response = requests.get(
                endpoint,
                params={
                    'key': current_app.config['PIXABAY_API_KEY'],
                    'q': query,
                    'image_type': 'photo',
                    'per_page': 20,
                    'safesearch': 'true',
                },
                timeout=(3, 10),
                allow_redirects=False,
            )
            if response.status_code != 200:
                return MediaService._external_error()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get('hits'), list):
                return MediaService._external_error()
            hits = []
            for hit in payload['hits'][:20]:
                if not isinstance(hit, dict):
                    continue
                try:
                    preview = MediaService._url(hit.get('previewURL'))
                    image = MediaService._url(hit.get('webformatURL'))
                except ValidationError:
                    continue
                tag_value = hit.get('tags')
                tags = tag_value if isinstance(tag_value, str) else ''
                hits.append({'previewURL': preview, 'webformatURL': image, 'tags': tags[:500]})
            return {'success': True, 'hits': hits}
        except (requests.RequestException, ValueError, TypeError):
            return MediaService._external_error()
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def save_pixabay_image(image_url, product_id):
        """Fetch only approved HTTPS images; re-encode, bound and save without overwrites."""
        product_id = positive_int(product_id, 'Sản phẩm', max_value=2147483647)
        image_url = MediaService._url(image_url)
        if not MediaService.pixabay_enabled():
            return MediaService._disabled()
        conn = MediaService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT ProductID FROM Products WHERE ProductID = %s', (product_id,))
                if not cursor.fetchone():
                    return {'success': False, 'message': 'Sản phẩm không tồn tại', 'status_code': 404}
        finally:
            conn.close()
        response = None
        temporary = None
        try:
            response = requests.get(image_url, timeout=(3, 10), stream=True, allow_redirects=False)
            if response.status_code != 200:
                return MediaService._external_error()
            content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
            if content_type not in {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}:
                return MediaService._external_error()
            limit = min(
                MediaService.MAX_IMAGE_BYTES, current_app.config.get('MAX_CONTENT_LENGTH', MediaService.MAX_IMAGE_BYTES)
            )
            length = response.headers.get('Content-Length')
            if length and (not length.isdigit() or int(length) > limit):
                return MediaService._external_error()
            raw = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                raw.extend(chunk)
                if len(raw) > limit:
                    return MediaService._external_error()
            cleaned, extension, _ = image_bytes(bytes(raw))
            folder = upload_root() / 'products'
            folder.mkdir(parents=True, exist_ok=True)
            filename = f'pixabay-{product_id}-{secrets.token_hex(16)}.{extension}'
            with tempfile.NamedTemporaryFile(dir=folder, prefix='.pixabay-', delete=False) as output:
                temporary = Path(output.name)
                output.write(cleaned)
            os.replace(temporary, folder / filename)
            temporary = None
            return {
                'success': True,
                'path': f'images/{filename}',
                'message': 'Đã tải ảnh. Lưu sản phẩm để áp dụng ảnh mới.',
            }
        except (requests.RequestException, ValidationError, OSError, TypeError, ValueError):
            return MediaService._external_error()
        finally:
            if response is not None:
                response.close()
            if temporary is not None:
                temporary.unlink(missing_ok=True)
