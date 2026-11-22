import json
import decimal
import unicodedata
import base64
import re
import os
import requests
from flask_mail import Message
from flask import current_app


# Hàm chuyển đổi decimal sang float cho JSON
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        return super().default(o)


# Helper function for slugify
def slugify(text):
    if not text:
        return ''
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '-', text)


# Hàm gửi email: Brevo HTTP API khi có BREVO_API_KEY (Render chặn port SMTP),
# fallback Flask-Mail SMTP cho môi trường local/self-hosted.
def send_email(to_email, subject, html_content, attachments=None):
    from app.extensions import mail
    from app.validation import email_address

    try:
        recipient = email_address(to_email)
        suppress = bool(current_app.config.get('MAIL_SUPPRESS_SEND'))
        brevo_key = current_app.config.get('BREVO_API_KEY')
        if (
            not suppress
            and not brevo_key
            and not all(
                current_app.config.get(key) for key in ('MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_DEFAULT_SENDER')
            )
        ):
            current_app.logger.warning('Email delivery is not configured')
            return False
        message = Message(subject=subject, recipients=[recipient], html=html_content)
        for filename, content_type, data in attachments or []:
            message.attach(filename, content_type, data)
        if suppress:
            mail.send(message)  # Flask-Mail keeps the suppressed outbox for tests/preview.
            return True
        if brevo_key:
            return send_email_via_brevo(recipient, subject, html_content, attachments, brevo_key)
        mail.send(message)
        return True
    except (ValueError, OSError, RuntimeError, requests.RequestException) as exc:
        current_app.logger.warning('Email delivery failed (%s)', type(exc).__name__)
        return False


def send_email_via_brevo(recipient, subject, html_content, attachments, api_key):
    payload = {
        'sender': {'email': _sender_email()},
        'to': [{'email': recipient}],
        'subject': subject,
        'htmlContent': html_content,
    }
    encoded = [
        {'name': filename, 'content': base64.b64encode(data).decode('ascii')}
        for filename, _content_type, data in attachments or []
        if data
    ]
    if encoded:
        payload['attachment'] = encoded
    response = requests.post(
        current_app.config['BREVO_API_URL'],
        json=payload,
        headers={'api-key': api_key, 'content-type': 'application/json', 'accept': 'application/json'},
        timeout=current_app.config.get('EMAIL_HTTP_TIMEOUT', 10),
    )
    if response.status_code >= 300:
        current_app.logger.warning('Brevo email rejected (%s): %s', response.status_code, response.text[:200])
        return False
    return True


def _sender_email():
    sender = current_app.config.get('MAIL_DEFAULT_SENDER') or ''
    # Flask-Mail accepts "Name <email>"; Brevo needs the bare address.
    match = re.search(r'<([^>]+)>', sender)
    return (match.group(1) if match else sender).strip()


# Template filter to resolve image path
def resolve_image(obj):
    # Default image
    default_image = 'images/default.jpg'

    if not obj:
        return default_image

    # Check if object is a dict
    is_dict = isinstance(obj, dict)

    # 1. Check direct ImageURL (PascalCase or snake_case)
    image_url = obj.get('ImageURL') if is_dict else getattr(obj, 'ImageURL', None)
    if not image_url and is_dict:
        image_url = obj.get('image_url')

    if image_url:
        return image_url

    # 2. Check by ID
    obj_id = obj.get('ProductID') if is_dict else getattr(obj, 'ProductID', None)
    if not obj_id and is_dict:
        obj_id = obj.get('product_id')

    if not obj_id:
        # Try category ID
        obj_id = obj.get('CategoryID') if is_dict else getattr(obj, 'CategoryID', None)
        if not obj_id and is_dict:
            obj_id = obj.get('category_id')

    if obj_id:
        # Check standard extensions
        for ext in ['.jpg', '.png', '.jpeg']:
            filename = f'images/{obj_id}{ext}'
            filepath = os.path.join(current_app.root_path, 'static', filename)
            if os.path.exists(filepath):
                return filename

    # 3. Check by Name (Slug)
    name = obj.get('ProductName') if is_dict else getattr(obj, 'ProductName', None)
    if not name and is_dict:
        name = obj.get('product_name')

    if not name:
        name = obj.get('CategoryName') if is_dict else getattr(obj, 'CategoryName', None)
        if not name and is_dict:
            name = obj.get('category_name')

    if name:
        slug = slugify(name)
        for ext in ['.jpg', '.png', '.jpeg']:
            filename = f'images/{slug}{ext}'
            filepath = os.path.join(current_app.root_path, 'static', filename)
            if os.path.exists(filepath):
                return filename

        # Try common variations if needed (optional)

    return default_image
