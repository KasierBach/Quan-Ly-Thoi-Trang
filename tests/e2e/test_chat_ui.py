import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.test_chat_workflows import login


pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


def test_chat_responsive_controls_and_vietnamese_font(gui_page):
    page = gui_page
    login(page, 'customer@example.test')
    page.goto('/messages')
    destination = ROOT / 'artifacts' / 'e2e' / 'chat-ui'
    destination.mkdir(parents=True, exist_ok=True)
    if page.locator('html').get_attribute('data-bs-theme') == 'dark':
        with page.expect_response(re.compile('/toggle_dark_mode$')) as response:
            page.locator('#toggleTheme').click()
        assert response.value.ok
    expect(page.locator('#conversationList')).to_have_attribute('aria-busy', 'false')
    page.locator('.conv-item').filter(has_text='Synthetic Private').click()
    page.get_by_role('textbox', name='Tin nhắn', exact=True).fill('Áo đẹp, kiểu dáng thoải mái. Cảm ơn cửa hàng!')
    page.get_by_role('button', name='Gửi tin nhắn', exact=True).click()
    expect(page.locator('.message-group.sent')).to_contain_text('Áo đẹp, kiểu dáng thoải mái.')
    for width, height in [(1440, 900), (1024, 768), (768, 1024), (390, 844), (320, 720)]:
        page.set_viewport_size({'width': width, 'height': height})
        expect(page.locator('#activeChatContainer')).to_have_attribute('aria-busy', 'false')
        expect(page.locator('#sendBtn')).to_be_visible()
        result = page.evaluate("""() => {
            const targets = ['messageInput', 'sendBtn', 'btnMobileBack', 'btnCall', 'btnVideo', 'toggleInfoBtn'];
            return {
                overflow: document.documentElement.scrollWidth > innerWidth,
                clipped: targets.filter(id => {
                    const el = document.getElementById(id);
                    if (getComputedStyle(el).display === 'none') return false;
                    const r = el.getBoundingClientRect();
                    return r.x < 0 || r.y < 0 || r.right > innerWidth + 1 || r.bottom > innerHeight + 1;
                }),
                font: getComputedStyle(document.getElementById('messageInput')).fontFamily,
                wide: Array.from(document.querySelectorAll('body *')).filter(el => {
                    const r = el.getBoundingClientRect();
                    return getComputedStyle(el).display !== 'none' && r.right > innerWidth + 1;
                }).map(el => ({tag: el.tagName, id: el.id, class: el.className})).slice(0, 12),
            };
        }""")
        assert not result['overflow'], (width, result)
        assert not result['clipped'], (width, result)
        assert 'Inter' in result['font']
        page.wait_for_function('() => document.fonts.status === "loaded"')
        bubble = page.locator('.message-group.sent .message-bubble').last
        palette = bubble.evaluate(
            'el => ({ background: getComputedStyle(el).backgroundColor, color: getComputedStyle(el).color })'
        )
        assert palette == {'background': 'rgb(0, 132, 255)', 'color': 'rgb(0, 0, 0)'}, (width, palette)
        page.screenshot(path=destination / f'chat-light-{width}.png')
        if width > 768:
            page.locator('#toggleInfoBtn').click()
            expect(page.locator('#infoPanel')).to_be_visible()
            page.screenshot(path=destination / f'chat-details-{width}.png')
            page.locator('#closeInfoBtn').click()
        else:
            page.locator('#toggleInfoBtn').click()
            expect(page.locator('#infoPanel')).to_be_visible()
            page.locator('#closeInfoBtn').click()
            expect(page.locator('#toggleInfoBtn')).to_be_focused()
            page.locator('#btnMobileBack').click()
            expect(page.locator('.msg-sidebar')).to_be_visible()
            page.screenshot(path=destination / f'chat-list-{width}.png')
            page.locator('.conv-item').filter(has_text='Synthetic Private').click()
    page.set_viewport_size({'width': 1440, 'height': 900})
    expect(page.locator('#activeChatContainer')).to_have_attribute('aria-busy', 'false')
    with page.expect_response(re.compile('/toggle_dark_mode$')) as response:
        page.locator('#toggleTheme').click()
    assert response.value.ok
    expect(page.locator('html')).to_have_attribute('data-bs-theme', 'dark')
    page.screenshot(path=destination / 'chat-dark-1440.png')
    page.set_viewport_size({'width': 390, 'height': 844})
    expect(page.locator('#activeChatContainer')).to_have_attribute('aria-busy', 'false')
    page.wait_for_function('() => getComputedStyle(document.querySelector(".message-actions")).opacity === "1"')
    assert page.locator('.msg-action-btn').first.evaluate('el => getComputedStyle(el).opacity') == '1'
    assert page.locator('.msg-action-btn').first.evaluate('el => getComputedStyle(el.parentElement).opacity') == '1'
    assert page.locator('.msg-action-btn').first.evaluate('el => getComputedStyle(el).color') == 'rgb(233, 238, 247)'
    page.screenshot(path=destination / 'chat-dark-390.png')
    assert not page.test_errors, page.test_errors
