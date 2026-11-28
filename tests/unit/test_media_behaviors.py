from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image
import requests

from app.services.media_service import MediaService


def enabled(app, tmp_path):
    app.config.update(
        TESTING=False, PIXABAY_ENABLED=True, PIXABAY_API_KEY='synthetic-not-real', MAX_CONTENT_LENGTH=1024 * 1024
    )
    app.static_folder = str(tmp_path)


def response(status=200, payload=None, raw=b''):
    result = MagicMock()
    result.status_code = status
    result.json.return_value = payload
    result.headers = {'Content-Type': 'image/png', 'Content-Length': str(len(raw))}
    result.iter_content.return_value = [raw]
    return result


def test_image_search_filters_remote_urls_and_preserves_text(app, tmp_path, monkeypatch):
    enabled(app, tmp_path)
    result = response(
        payload={
            'hits': [
                None,
                {'previewURL': 'https://evil.test/a.png', 'webformatURL': 'https://evil.test/a.png'},
                {
                    'previewURL': 'https://cdn.pixabay.com/a.png',
                    'webformatURL': 'https://pixabay.com/a.png',
                    'tags': '<script>tags</script>',
                },
            ]
        }
    )
    get = MagicMock(return_value=result)
    monkeypatch.setattr('app.services.media_service.requests.get', get)
    with app.app_context():
        data = MediaService.search_pixabay('shirt')
    assert data['success'] and len(data['hits']) == 1
    assert data['hits'][0]['tags'] == '<script>tags</script>'
    assert get.call_args.kwargs['allow_redirects'] is False
    assert get.call_args.kwargs['timeout'] == (3, 10)
    result.close.assert_called_once()


@pytest.mark.parametrize('payload,status', [({}, 200), ([], 200), ({'hits': {}}, 200), (None, 302)])
def test_image_search_invalid_response_is_safe(app, tmp_path, monkeypatch, payload, status):
    enabled(app, tmp_path)
    result = response(status, payload)
    monkeypatch.setattr('app.services.media_service.requests.get', lambda *args, **kwargs: result)
    with app.app_context():
        assert MediaService.search_pixabay('shirt')['status_code'] == 502
    result.close.assert_called_once()


def test_image_search_exception_does_not_expose_api_key(app, tmp_path, monkeypatch):
    enabled(app, tmp_path)
    monkeypatch.setattr(
        'app.services.media_service.requests.get',
        MagicMock(side_effect=requests.RequestException('key=synthetic-secret')),
    )
    with app.app_context():
        result = MediaService.search_pixabay('shirt')
    assert 'secret' not in result['message']


def test_image_download_decodes_to_local_unique_jpeg(app, tmp_path, fake_db, monkeypatch):
    enabled(app, tmp_path)
    fake_db.cursor.fetchone.return_value = [1]
    image = BytesIO()
    Image.new('RGB', (4, 4), 'blue').save(image, 'PNG')
    result = response(raw=image.getvalue())
    monkeypatch.setattr('app.services.media_service.requests.get', lambda *args, **kwargs: result)
    with app.app_context():
        data = MediaService.save_pixabay_image('https://cdn.pixabay.com/image.png', 1)
    assert data['success']
    saved = tmp_path / 'uploads' / 'products' / data['path'].removeprefix('images/')
    assert saved.is_file() and saved.read_bytes().startswith(b'\xff\xd8')
    assert data['path'].startswith('images/pixabay-1-')
    assert not (tmp_path / data['path']).exists()
    with app.test_client().get(f'/static/{data["path"]}') as served:
        assert served.status_code == 200 and served.data == saved.read_bytes()
    result.close.assert_called_once()


def test_legacy_pixabay_file_still_uses_its_original_url(client, app, tmp_path):
    app.static_folder = str(tmp_path)
    legacy = tmp_path / 'images' / f'pixabay-1-{"a" * 32}.jpg'
    legacy.parent.mkdir()
    legacy.write_bytes(b'legacy image')
    with client.get(f'/static/images/{legacy.name}') as served:
        assert served.status_code == 200 and served.data == legacy.read_bytes()


@pytest.mark.parametrize(
    'headers,raw,status',
    [
        ({'Content-Type': 'text/html'}, b'<script>bad</script>', 200),
        ({'Content-Type': 'image/png', 'Content-Length': '999999999'}, b'bad', 200),
        ({'Content-Type': 'image/png', 'Content-Length': 'invalid'}, b'bad', 200),
        ({'Content-Type': 'image/png'}, b'bad', 200),
        ({'Content-Type': 'image/png'}, b'bad', 302),
    ],
)
def test_image_download_rejects_active_or_corrupt_content(app, tmp_path, fake_db, monkeypatch, headers, raw, status):
    enabled(app, tmp_path)
    fake_db.cursor.fetchone.return_value = [1]
    result = response(status=status, raw=raw)
    result.headers = headers
    monkeypatch.setattr('app.services.media_service.requests.get', lambda *args, **kwargs: result)
    with app.app_context():
        assert MediaService.save_pixabay_image('https://cdn.pixabay.com/image.png', 1)['status_code'] == 502
    assert not list(tmp_path.rglob('pixabay-*'))


def test_image_download_missing_product_never_requests_external(app, tmp_path, fake_db, monkeypatch):
    enabled(app, tmp_path)
    fake_db.cursor.fetchone.return_value = None
    get = MagicMock()
    monkeypatch.setattr('app.services.media_service.requests.get', get)
    with app.app_context():
        assert MediaService.save_pixabay_image('https://cdn.pixabay.com/image.png', 99)['status_code'] == 404
    get.assert_not_called()


def test_image_download_stream_limit(app, tmp_path, fake_db, monkeypatch):
    enabled(app, tmp_path)
    app.config['MAX_CONTENT_LENGTH'] = 8
    fake_db.cursor.fetchone.return_value = [1]
    result = response(raw=b'01234567890')
    result.headers = {'Content-Type': 'image/png'}
    monkeypatch.setattr('app.services.media_service.requests.get', lambda *args, **kwargs: result)
    with app.app_context():
        assert MediaService.save_pixabay_image('https://cdn.pixabay.com/image.png', 1)['status_code'] == 502
