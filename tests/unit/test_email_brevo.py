"""Brevo API email transport regressions; external API is always mocked."""

import base64
from unittest.mock import MagicMock

import pytest
import requests

from app.utils import send_email


@pytest.fixture
def brevo_config(app):
    app.config.update(
        BREVO_API_KEY='synthetic-brevo-key-not-real',
        BREVO_API_URL='https://api.brevo.test/v3/smtp/email',
        MAIL_SUPPRESS_SEND=False,
        MAIL_DEFAULT_SENDER='noreply@example.test',
    )
    with app.app_context():
        yield app


@pytest.fixture
def app_context(app):
    with app.app_context():
        yield app


def mock_brevo(monkeypatch, app, status_code=201, side_effect=None):
    calls = []

    def post(url, **kwargs):
        if side_effect is not None:
            raise side_effect
        calls.append({'url': url, **kwargs})
        response = MagicMock()
        response.status_code = status_code
        response.text = 'synthetic brevo response'
        return response

    monkeypatch.setattr('app.utils.requests.post', post)
    return calls


def test_brevo_transport_sends_verified_payload(brevo_config, monkeypatch):
    calls = mock_brevo(monkeypatch, brevo_config)

    assert send_email('user@example.test', 'Reset password', '<p>Link</p>')

    assert len(calls) == 1
    request = calls[0]
    assert request['url'] == 'https://api.brevo.test/v3/smtp/email'
    assert request['headers']['api-key'] == 'synthetic-brevo-key-not-real'
    assert request['timeout'] == brevo_config.config['EMAIL_HTTP_TIMEOUT']
    payload = request['json']
    assert payload['sender'] == {'email': 'noreply@example.test'}
    assert payload['to'] == [{'email': 'user@example.test'}]
    assert payload['subject'] == 'Reset password'
    assert payload['htmlContent'] == '<p>Link</p>'


def test_brevo_transport_encodes_attachments_as_base64(brevo_config, monkeypatch):
    calls = mock_brevo(monkeypatch, brevo_config)

    assert send_email('user@example.test', 'Report', '<p>Attached</p>', [('report.csv', 'text/csv', b'csv-bytes')])

    payload = calls[0]['json']
    assert payload['attachment'] == [{'name': 'report.csv', 'content': base64.b64encode(b'csv-bytes').decode('ascii')}]


def test_brevo_transport_extracts_bare_address_from_named_sender(brevo_config, monkeypatch):
    brevo_config.config['MAIL_DEFAULT_SENDER'] = 'Fashion Store <noreply@example.test>'
    calls = mock_brevo(monkeypatch, brevo_config)

    assert send_email('user@example.test', 'Subject', '<p>x</p>')

    assert calls[0]['json']['sender'] == {'email': 'noreply@example.test'}


def test_brevo_transport_returns_false_on_http_rejection(brevo_config, monkeypatch):
    mock_brevo(monkeypatch, brevo_config, status_code=401)

    assert not send_email('user@example.test', 'Subject', '<p>x</p>')


def test_brevo_transport_returns_false_on_network_error(brevo_config, monkeypatch):
    mock_brevo(monkeypatch, brevo_config, side_effect=requests.exceptions.Timeout('blocked egress'))

    assert not send_email('user@example.test', 'Subject', '<p>x</p>')


def test_suppressed_mail_uses_flask_mail_outbox_even_with_brevo_key(brevo_config, monkeypatch):
    from app.extensions import mail

    calls = mock_brevo(monkeypatch, brevo_config)
    brevo_config.config['MAIL_SUPPRESS_SEND'] = True

    with mail.record_messages() as outbox:
        assert send_email('user@example.test', 'Subject', '<p>Suppressed</p>')

    assert calls == []
    assert len(outbox) == 1 and outbox[0].subject == 'Subject'


def test_smtp_fallback_still_used_without_brevo_key(app_context, monkeypatch):
    from app.extensions import mail

    app_context.config.update(
        MAIL_SUPPRESS_SEND=False,
        BREVO_API_KEY=None,
        MAIL_USERNAME='test',
        MAIL_PASSWORD='synthetic',
        MAIL_DEFAULT_SENDER='test@example.test',
    )
    calls = mock_brevo(monkeypatch, app_context)
    smtp = MagicMock()
    monkeypatch.setattr(mail, 'send', smtp)

    assert send_email('user@example.test', 'Subject', '<p>SMTP</p>')

    assert calls == []
    smtp.assert_called_once()
