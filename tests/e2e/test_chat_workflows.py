import re
import time
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
        first.get_by_role('textbox', name='Tin nhắn', exact=True).fill(
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


def test_chat_keyboard_dialog_theme_and_multiline_input(gui_page, db_connection):
    page = gui_page
    login(page, 'customer@example.test')
    page.goto('/messages')
    conversation = page.get_by_role('button').filter(has_text='Synthetic Private')
    conversation.focus()
    conversation.press('Enter')
    expect(page.locator('#currentChatName')).to_have_text('Synthetic Private')
    page.locator('#toggleInfoBtn').click()
    page.locator('#btnInfoTheme').click()
    expect(page.locator('#themeModal')).to_be_visible()
    page.get_by_role('button', name='Vàng', exact=True).focus()
    page.get_by_role('button', name='Vàng', exact=True).press('Enter')
    expect(page.locator('#themeModal')).not_to_be_visible()
    expect(page.locator('#btnInfoTheme')).to_be_focused()
    composer = page.get_by_role('textbox', name='Tin nhắn', exact=True)
    composer.fill('Kiểm tra dòng thứ nhất')
    composer.press('End')
    composer.press('Shift+Enter')
    composer.type('Dòng thứ hai có tiếng Việt')
    composer.press('Enter')
    message = page.locator('.message-group.sent').filter(has_text='Kiểm tra dòng thứ nhất').last
    expect(message).to_contain_text('Dòng thứ hai có tiếng Việt')
    colors = message.locator('.message-bubble').evaluate(
        'el => ({background: getComputedStyle(el).backgroundColor, text: getComputedStyle(el).color})'
    )
    assert colors == {'background': 'rgb(255, 204, 0)', 'text': 'rgb(0, 0, 0)'}
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT content FROM Messages WHERE content LIKE %s', ('Kiểm tra dòng thứ nhất%',))
        assert cursor.fetchone().content == 'Kiểm tra dòng thứ nhất\nDòng thứ hai có tiếng Việt'
    page.locator('#btnInfoEmoji').click()
    expect(page.locator('#emojiDefaultModal')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('#emojiDefaultModal')).not_to_be_visible()
    expect(page.locator('#btnInfoEmoji')).to_be_focused()
    evidence(page, 'chat-keyboard-color-vietnamese')
    assert not page.test_errors, page.test_errors


def test_ime_composition_does_not_publish_until_real_enter(gui_page, db_connection):
    page = gui_page
    login(page, 'customer@example.test')
    page.goto('/messages')
    page.locator('.conv-item').filter(has_text='Synthetic Private').click()
    composer = page.get_by_role('textbox', name='Tin nhắn', exact=True)
    content = 'Không gửi khi đang xác nhận bộ gõ tiếng Việt'
    composer.fill(content)
    # Chromium automation has no native OS IME; exercise its composition event contract.
    composer.dispatch_event('keydown', {'key': 'Enter', 'isComposing': True})
    expect(composer).to_have_value(content)
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS count FROM Messages WHERE content=%s', (content,))
        assert cursor.fetchone().count == 0
    composer.press('Enter')
    expect(page.locator('.message-group.sent')).to_contain_text(content)
    expect(composer).to_have_value('')
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS count FROM Messages WHERE content=%s', (content,))
        assert cursor.fetchone().count == 1
    assert not page.test_errors, page.test_errors


def collect_errors(page):
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.test_errors = errors
    return errors


def test_dark_mode_toggle_persists_and_restyles_chat(gui_context, live_app):
    page = gui_context.new_page()
    errors = collect_errors(page)
    try:
        login(page, 'customer@example.test')
        page.goto('/messages')
        page.locator('.conv-item').filter(has_text='Synthetic Private').click()
        expect(page.locator('#currentChatName')).to_contain_text('Synthetic Private')

        def header_color():
            return page.evaluate("getComputedStyle(document.querySelector('.msg-chat-header')).backgroundColor")

        light_color = header_color()
        page.locator('#toggleTheme').click()
        expect(page.locator('html')).to_have_attribute('data-bs-theme', 'dark')
        assert header_color() != light_color, 'chat header must restyle when the theme flips'
        evidence(page, 'chat-dark-mode')
        # The preference is stored on the account, so a full reload keeps it.
        page.reload()
        expect(page.locator('html')).to_have_attribute('data-bs-theme', 'dark')
        evidence(page, 'chat-dark-mode-reloaded')
        assert not errors, errors
    finally:
        page.close()


def test_mobile_conversation_back_navigation(gui_context, browser, live_app):
    base_url, _ = live_app
    context = browser.new_context(
        viewport={'width': 390, 'height': 844}, base_url=base_url, permissions=['camera', 'microphone']
    )
    context.set_default_timeout(5000)
    context.route('https://**/*', lambda route: route.abort())
    page = context.new_page()
    errors = collect_errors(page)
    try:
        login(page, 'customer@example.test')
        page.goto('/messages')
        expect(page.locator('.msg-sidebar')).to_be_visible()
        page.locator('.conv-item').filter(has_text='Synthetic Private').click()
        expect(page.locator('#currentChatName')).to_contain_text('Synthetic Private')
        expect(page.locator('.messenger-container')).to_have_class(re.compile('mobile-chat-open'))
        sidebar_hidden = page.evaluate("getComputedStyle(document.querySelector('.msg-sidebar')).display === 'none'")
        assert sidebar_hidden, 'sidebar must collapse while a conversation is open on mobile'
        composer = page.get_by_role('textbox', name='Tin nhắn', exact=True)
        composer.fill('Tin nhắn mobile có dấu: chiếc áo mới rất đẹp.')
        expect(page.locator('#sendBtn')).to_be_visible()
        bounds = page.locator('#sendBtn').bounding_box()
        assert bounds is not None and bounds['x'] + bounds['width'] <= 390
        assert bounds['y'] + bounds['height'] <= 844
        page.locator('#sendBtn').click()
        expect(page.locator('#messagesArea')).to_contain_text('Tin nhắn mobile có dấu: chiếc áo mới rất đẹp.')
        evidence(page, 'chat-mobile-open')
        page.locator('#btnMobileBack').click()
        expect(page.locator('.msg-sidebar')).to_be_visible()
        overflow = page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
        assert not overflow, 'back navigation must not introduce horizontal overflow'
        evidence(page, 'chat-mobile-back')
        assert not errors, errors
    finally:
        if not page.is_closed():
            evidence(page, 'chat-mobile-last')
        page.close()
        context.close()


def test_unread_badge_counts_arrival_and_clears_after_read(gui_context, browser, live_app, db_connection):
    base_url, _ = live_app
    other_context = browser.new_context(base_url=base_url, viewport={'width': 1280, 'height': 900})
    other_context.set_default_timeout(5000)
    other_context.route('https://**/*', lambda route: route.abort())
    first, second = gui_context.new_page(), other_context.new_page()
    errors = collect_errors(first)
    try:
        login(first, 'customer@example.test')
        login(second, 'other@example.test')
        first.bring_to_front()
        first.goto('/messages')
        second.goto('/messages')
        first.locator('.conv-item').filter(has_text='Synthetic Private').click()
        expect(first.locator('#currentChatName')).to_contain_text('Synthetic Private')
        # Reading means actually focusing the composer, like a real user.
        first.locator('#messageInput').click()
        expect(first.locator('#messageInput')).to_be_focused()
        first.wait_for_function('() => window.chatApp.pendingReads.size === 0')
        last_read = None
        deadline = time.time() + 5
        while last_read is None and time.time() < deadline:
            with db_connection.cursor() as cursor:
                cursor.execute(
                    'SELECT last_read_at FROM Participants WHERE user_id=%s AND conversation_id=%s',
                    (1, 2),
                )
                last_read = cursor.fetchone().last_read_at
            if last_read is None:
                time.sleep(0.2)
        assert last_read is not None, 'opening the conversation must persist a read receipt'
        # The badge clears as soon as the read receipt broadcast round-trips.
        expect(first.locator('.conv-item').filter(has_text='Synthetic Private').locator('.conv-badge')).to_have_count(0)
        # Step away from the composer: an incoming message must then stay unread.
        first.locator('#currentChatName').click()

        second.locator('.conv-item').filter(has_text='Synthetic Private').click()
        first.locator('.conv-item').filter(has_text='Hỗ trợ khách hàng').click()
        first.locator('#currentChatName').click()
        content = 'Unread badge synthetic message'
        second.get_by_role('textbox', name='Tin nhắn', exact=True).fill(content)
        second.get_by_role('button', name='Gửi tin nhắn', exact=True).click()
        expect(second.locator('#messagesArea')).to_contain_text(content)

        badge = first.locator('.conv-item').filter(has_text='Synthetic Private').locator('.conv-badge')
        expect(badge).to_be_visible()
        expect(badge).to_have_text('1')
        expect(first.locator('#messagesArea')).not_to_contain_text(content)
        first.reload()
        expect(badge).to_have_text('1')
        evidence(first, 'chat-unread-badge')
        # Reading the conversation clears the counter both in UI and on the server.
        first.bring_to_front()
        first.locator('.conv-item').filter(has_text='Synthetic Private').click()
        expect(first.locator('#currentChatName')).to_contain_text('Synthetic Private')
        first.locator('#messageInput').click()
        expect(first.locator('.conv-item').filter(has_text='Synthetic Private').locator('.conv-badge')).to_have_count(0)
        first.reload()
        expect(first.locator('.conv-item').filter(has_text='Synthetic Private').locator('.conv-badge')).to_have_count(0)
        receipt = None
        deadline = time.time() + 5
        while receipt is None and time.time() < deadline:
            with db_connection.cursor() as cursor:
                cursor.execute(
                    """SELECT m.id FROM Messages m
                       JOIN Participants p ON p.conversation_id = m.conversation_id
                       WHERE m.content=%s AND p.user_id=%s AND m.created_at <= p.last_read_at""",
                    (content, 1),
                )
                receipt = cursor.fetchone()
            if receipt is None:
                time.sleep(0.2)
        assert receipt is not None, 'last_read_at must cover the received message'
        assert not errors, errors
    finally:
        for page, name in [(first, 'unread-badge-first-last'), (second, 'unread-badge-second-last')]:
            if not page.is_closed():
                evidence(page, name)
        first.close()
        second.close()
        other_context.close()
