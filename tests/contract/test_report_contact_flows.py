from unittest.mock import MagicMock

import pytest

from app.services.media_service import MediaService
from app.services.report_service import ReportService
from app.services.main_service import MainService


@pytest.mark.parametrize('success', [True, False])
def test_report_email_uses_validated_attachment_and_result(admin_client, app, monkeypatch, success):
    app.config.update(
        TESTING=False, MAIL_SUPPRESS_SEND=False, MAIL_SERVER='example.test', MAIL_DEFAULT_SENDER='sender@example.test'
    )
    monkeypatch.setattr(ReportService, 'generate_csv_report', lambda *_: b'header\nrow')
    send = MagicMock(return_value=success)
    monkeypatch.setattr('app.routes.admin.reports.send_email', send)
    response = admin_client.post(
        '/admin/api/send_report_email',
        json={
            'email': 'target@example.test',
            'message': '<script>bad</script>',
            'report_type': 'daily_revenue',
            'start_date': '2026-04-01',
            'end_date': '2026-04-30',
        },
    )
    assert response.status_code == (200 if success else 502)
    assert response.json['success'] is success
    assert '&lt;script&gt;' in send.call_args.args[2]
    assert send.call_args.kwargs['attachments'][0][2] == b'header\nrow'


@pytest.mark.parametrize(
    'endpoint,method,payload',
    [
        ('/admin/api/search_pixabay?q=test', 'search_pixabay', None),
        (
            '/admin/api/save_pixabay_image',
            'save_pixabay_image',
            {'image_url': 'https://cdn.pixabay.com/a.jpg', 'product_id': 1},
        ),
    ],
)
def test_admin_image_routes_preserve_safe_service_error(admin_client, monkeypatch, endpoint, method, payload):
    monkeypatch.setattr(MediaService, method, lambda *_: {'success': False, 'message': 'Disabled', 'status_code': 503})
    response = admin_client.post(endpoint, json=payload) if payload else admin_client.get(endpoint)
    assert response.status_code == 503
    assert response.json['message'] == 'Disabled'


@pytest.mark.parametrize(
    'endpoint,method,payload',
    [
        ('/admin/api/search_pixabay?q=test', 'search_pixabay', None),
        ('/admin/api/save_pixabay_image', 'save_pixabay_image', {'image_url': 'bad', 'product_id': 1}),
    ],
)
def test_admin_image_routes_keep_internal_validation_details_private(
    admin_client, monkeypatch, endpoint, method, payload
):
    from app.validation import ValidationError

    monkeypatch.setattr(MediaService, method, MagicMock(side_effect=ValidationError('Internal image diagnostic')))
    response = admin_client.post(endpoint, json=payload) if payload else admin_client.get(endpoint)
    assert response.status_code == 400
    assert response.json['success'] is False
    assert 'Internal image diagnostic' not in response.json['message']


def test_invalid_report_export_is_400(admin_client):
    response = admin_client.get('/admin/reports/export?report_type=unknown')
    assert response.status_code == 400


def test_contact_success_redirects_and_failure_preserves_input(client, monkeypatch):
    monkeypatch.setattr(MainService, 'add_contact_message', lambda *_: {'success': True})
    data = {'name': 'Test', 'email': 'user@example.test', 'subject': 'Test', 'message': 'Test message'}
    assert client.post('/contact', data=data).status_code == 302
    monkeypatch.setattr(MainService, 'add_contact_message', lambda *_: {'success': False})
    response = client.post('/contact', data=data)
    assert response.status_code == 500
    assert 'Test message' in response.text


def test_contact_validation_does_not_store(client, monkeypatch):
    save = MagicMock()
    monkeypatch.setattr(MainService, 'add_contact_message', save)
    assert client.post('/contact', data={'name': '', 'email': 'invalid', 'message': ''}).status_code == 400
    save.assert_not_called()


def test_newsletter_success_and_failure_json(client, monkeypatch):
    monkeypatch.setattr(MainService, 'subscribe_newsletter', lambda _: {'success': True, 'message': 'Saved'})
    assert client.post('/subscribe_newsletter', data={'email': 'user@example.test'}).json['success']
    monkeypatch.setattr(
        MainService, 'subscribe_newsletter', lambda _: {'success': False, 'message': 'Failed', 'status_code': 503}
    )
    assert client.post('/subscribe_newsletter', data={'email': 'user@example.test'}).status_code == 503
