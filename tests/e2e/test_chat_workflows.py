import re
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect
import pytest


pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


def login(page, email):
    page.goto('/login')
    page.get_by_label('Email', exact=True).fill(email)
    page.get_by_label('Mật khẩu', exact=True).fill('TestUser123!')
    page.get_by_role('button', name=re.compile('Đăng nhập')).click()
    expect(page).to_have_url(re.compile(r'/(?:admin)?$'))


def evidence(page, name):
    destination = ROOT / 'artifacts' / 'e2e'
    destination.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=destination / f'{name}.png')


def test_private_messages_reach_only_conversation_and_can_upload(gui_context, browser, live_app, db_connection):
    base_url, _ = live_app
    other_context = browser.new_context(base_url=base_url, viewport={'width': 1280, 'height': 900})
    other_context.set_default_timeout(5000)
    other_context.route('https://**/*', lambda route: route.abort())
    first, second = gui_context.new_page(), other_context.new_page()
    errors = []
    for page in (first, second):
        page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        login(first, 'customer@example.test')
        login(second, 'other@example.test')
        first.goto('/messages')
        second.goto('/messages')
        # These are seeded real private-conversation participants, not injected sessions.
        first.locator('.conv-item').filter(has_text='Synthetic Private').click()
        second.locator('.conv-item').filter(has_text='Synthetic Private').click()
        expect(first.locator('#currentChatName')).to_contain_text('Synthetic Private')
        expect(first.locator('#btnCall')).to_be_enabled()
        expect(second.locator('#btnCall')).to_be_enabled()
        first.get_by_placeholder('Aa', exact=True).fill(
            'Synthetic private browser message <script>not executable</script>'
        )
        first.get_by_role('button', name='Gửi tin nhắn', exact=True).click()
        expect(second.locator('#messagesArea')).to_contain_text(
            'Synthetic private browser message <script>not executable</script>'
        )
        assert first.locator('#messagesArea script').count() == 0
        assert second.locator('#messagesArea script').count() == 0
        evidence(first, 'private-chat-sent')
        evidence(second, 'private-chat-received')
        with db_connection.cursor() as cursor:
            cursor.execute(
                'SELECT user_id,conversation_id FROM Messages WHERE content=%s',
                ('Synthetic private browser message <script>not executable</script>',),
            )
            row = cursor.fetchone()
            assert row.user_id == 1 and row.conversation_id == 2
        image = BytesIO()
        Image.new('RGB', (12, 12), 'blue').save(image, 'PNG')
        first.locator('#imageInput').set_input_files(
            {'name': 'test-upload.png', 'mimeType': 'image/png', 'buffer': image.getvalue()}
        )
        uploaded = second.locator('#messagesArea .message-image img').last
        expect(uploaded).to_be_visible()
        expect(uploaded).to_have_attribute('src', re.compile(r'^/api/chat/attachments/\d+'))
        evidence(second, 'private-chat-upload-received')
        assert not errors, errors
    finally:
        for page, name in [(first, 'private-chat-first-last'), (second, 'private-chat-second-last')]:
            if not page.is_closed():
                evidence(page, name)
        (ROOT / 'artifacts' / 'e2e' / 'private-chat-errors.txt').write_text('\n'.join(errors), encoding='utf-8')
        first.close()
        second.close()
        other_context.close()


def test_guest_support_widget_sends_acknowledged_message(gui_page, db_connection):
    page = gui_page
    page.goto('/')
    page.get_by_role('button', name='Mở hỗ trợ', exact=True).click()
    page.get_by_role('button', name='Chat hỗ trợ', exact=False).click()
    expect(page.locator('#chatWindow')).to_have_class(re.compile('active'))
    page.locator('#chatInput').fill('Synthetic guest support browser message')
    page.locator('#chatSend').click()
    expect(page.locator('#chatBody')).to_contain_text('Synthetic guest support browser message')
    evidence(page, 'guest-support-sent')
    with db_connection.cursor() as cursor:
        cursor.execute(
            'SELECT user_id,conversation_id,session_id FROM Messages WHERE content=%s',
            ('Synthetic guest support browser message',),
        )
        row = cursor.fetchone()
        assert row.user_id is None and row.conversation_id is None and row.session_id
    assert not page.test_errors, page.test_errors
