from contextlib import contextmanager
from pathlib import Path
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.test_chat_workflows import collect_errors, login


pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def conversation_pair(gui_context, browser, live_app):
    base_url, _ = live_app
    other = browser.new_context(base_url=base_url, viewport={'width': 1280, 'height': 900})
    other.set_default_timeout(5000)
    other.route('https://**/*', lambda route: route.abort())
    first, second = gui_context.new_page(), other.new_page()
    errors = []
    for page, email in [(first, 'customer@example.test'), (second, 'other@example.test')]:
        errors.extend(collect_errors(page))
        login(page, email)
        page.goto('/messages')
        page.locator('.conv-item').filter(has_text='Synthetic Private').click()
        expect(page.locator('#activeChatContainer')).to_have_attribute('aria-busy', 'false')
        page.wait_for_function('() => window.chatApp.socket.connected')
    try:
        yield first, second
        assert not first.test_errors, first.test_errors
        assert not second.test_errors, second.test_errors
    finally:
        destination = ROOT / 'artifacts' / 'e2e'
        destination.mkdir(parents=True, exist_ok=True)
        for page, name in [(first, 'interaction-first'), (second, 'interaction-second')]:
            if page.is_closed():
                continue
            state = page.evaluate(
                '() => ({call:window.chatApp.callManager.currentCall, pending:window.chatApp.callManager.pendingCall, terminal:[...window.chatApp.callManager.terminalCalls], error:window.chatApp.callManager.lastError})'
            )
            (destination / f'{name}-state.txt').write_text(str(state), encoding='utf-8')
        first.close()
        second.close()
        other.close()


def send(page, content):
    page.get_by_role('textbox', name='Tin nhắn', exact=True).fill(content)
    page.locator('#sendBtn').click()
    message = page.locator('.message-group.sent').filter(has_text=content).last
    expect(message).to_be_visible()
    return message


def test_chat_reaction_reply_pin_unpin_and_recall(gui_context, browser, live_app, db_connection):
    with conversation_pair(gui_context, browser, live_app) as (first, second):
        content = 'Thử cảm xúc, trả lời, ghim và thu hồi'
        message = send(first, content)
        received = second.locator('.message-group.received').filter(has_text=content).last
        expect(received).to_be_visible()
        received.hover()
        received.get_by_role('button', name='Thêm cảm xúc', exact=True).click()
        received.get_by_role('button', name='Thả ❤️', exact=True).click()
        expect(message.locator('.reaction-badge')).to_be_visible()
        expect(received.locator('.reaction-badge')).to_have_attribute('aria-pressed', 'true')
        received.locator('.reaction-badge').click()
        expect(message.locator('.reaction-badge')).to_have_count(0)
        received.hover()
        received.get_by_role('button', name='Trả lời', exact=True).click()
        expect(second.locator('#replyShelf')).to_be_visible()
        send(second, 'Trả lời có trích dẫn')
        quoted = first.locator('.message-group.received').filter(has_text='Trả lời có trích dẫn').last
        expect(quoted.locator('.message-reply-quote')).to_contain_text(content)
        message.hover()
        message.get_by_role('button', name='Xem thêm', exact=True).click()
        first.locator('#ctxPinBtn').click()
        expect(second.locator('#pinnedShelf')).to_be_visible()
        expect(second.locator('#pinnedContent')).to_have_text(content)
        message.hover()
        message.get_by_role('button', name='Xem thêm', exact=True).click()
        first.locator('#ctxUnpinBtn').click()
        expect(second.locator('#pinnedShelf')).not_to_be_visible()
        message.hover()
        message.get_by_role('button', name='Xem thêm', exact=True).click()
        first.locator('#ctxRecallBtn').click()
        expect(first.locator('.message-bubble-main').filter(has_text=content)).to_have_count(0)
        expect(second.locator('.message-bubble-main').filter(has_text=content)).to_have_count(0)
        with db_connection.cursor() as cursor:
            cursor.execute('SELECT id,is_deleted FROM Messages WHERE content=%s', (content,))
            row = cursor.fetchone()
            assert row.is_deleted
            cursor.execute('SELECT COUNT(*) AS count FROM PinnedMessages WHERE message_id=%s', (row.id,))
            assert cursor.fetchone().count == 0


def test_typing_and_read_receipt_between_real_contexts(gui_context, browser, live_app):
    with conversation_pair(gui_context, browser, live_app) as (first, second):
        first.get_by_role('textbox', name='Tin nhắn', exact=True).fill('Đang soạn một câu hỏi')
        expect(second.locator('#typingIndicator')).to_be_visible()
        first.locator('#sendBtn').click()
        received = second.locator('.message-group.received').filter(has_text='Đang soạn một câu hỏi')
        expect(received).to_be_visible()
        second.bring_to_front()
        second.locator('#messageInput').click()
        expect(first.locator('.message-group.sent .message-seen-status')).to_have_text('Đã xem')
        expect(second.locator('#typingIndicator')).not_to_be_visible()


def test_private_text_attachment_downloads_from_guarded_endpoint(gui_context, browser, live_app, db_connection):
    with conversation_pair(gui_context, browser, live_app) as (first, second):
        first.locator('#fileInput').set_input_files(
            {
                'name': 'ghi-chu-thu-nghiem.txt',
                'mimeType': 'text/plain',
                'buffer': b'Synthetic private attachment only.',
            }
        )
        link = second.locator('#messagesArea .file-attachment').last
        expect(link).to_be_visible()
        expect(link).to_have_attribute('href', re.compile(r'^/api/chat/attachments/\d+$'))
        with second.expect_download() as download:
            link.click()
        saved = download.value.path()
        assert Path(saved).read_bytes() == b'Synthetic private attachment only.'
        with db_connection.cursor() as cursor:
            cursor.execute('SELECT file_name FROM Attachments WHERE file_name=%s', ('ghi-chu-thu-nghiem.txt',))
            assert cursor.fetchone() is not None


def test_rejected_call_can_be_started_again(gui_context, browser, live_app):
    with conversation_pair(gui_context, browser, live_app) as (first, second):
        expect(first.locator('#btnCall')).to_be_enabled()
        first.locator('#btnCall').click()
        first.wait_for_function('() => window.chatApp.callManager.currentCall?.offered === true')
        expect(second.locator('#incomingCallModal')).to_be_visible(timeout=10000)
        second.locator('#btnRejectCall').click()
        expect(first.locator('#callOverlay')).not_to_be_visible()
        expect(second.locator('#callOverlay')).not_to_be_visible()
        assert first.evaluate('window.chatApp.callManager.currentCall === null')
        assert second.evaluate('window.chatApp.callManager.currentCall === null')
        first.locator('#btnCall').click()
        first.wait_for_function('() => window.chatApp.callManager.currentCall?.offered === true')
        expect(second.locator('#incomingCallModal')).to_be_visible(timeout=10000)
        second.wait_for_function('() => window.chatApp.callManager.currentCall?.phase === "ringing"')
        second.locator('#btnRejectCall').click()
        expect(first.locator('#callOverlay')).not_to_be_visible()
        assert first.evaluate('window.chatApp.callManager.localStream === null')
