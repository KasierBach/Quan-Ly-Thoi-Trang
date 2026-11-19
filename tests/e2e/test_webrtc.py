import re
from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


def login(page, email):
    page.goto('/login')
    page.get_by_label('Email', exact=True).fill(email)
    page.get_by_label('Mật khẩu', exact=True).fill('TestUser123!')
    page.get_by_role('button', name=re.compile('Đăng nhập')).click()
    expect(page).to_have_url(re.compile(r'/(?:admin)?$'))
    page.goto('/messages')
    page.locator('.conv-item').filter(has_text='Synthetic Private').click()
    expect(page.locator('#btnVideo')).to_be_enabled()


@pytest.mark.parametrize('video', [False, True], ids=['voice', 'video'])
def test_webrtc_two_peers_exchange_synthetic_media_and_teardown(gui_context, browser, live_app, video):
    base_url, _ = live_app
    other = browser.new_context(
        base_url=base_url, permissions=['camera', 'microphone'], viewport={'width': 1280, 'height': 900}
    )
    other.set_default_timeout(5000)
    other.route('https://**/*', lambda route: route.abort())
    caller, recipient = gui_context.new_page(), other.new_page()
    errors = []
    for page in (caller, recipient):
        page.on('pageerror', lambda error: errors.append(str(error)))
    destination = ROOT / 'artifacts' / 'e2e'
    destination.mkdir(parents=True, exist_ok=True)
    try:
        login(caller, 'customer@example.test')
        login(recipient, 'other@example.test')
        caller.locator('#btnVideo' if video else '#btnCall').click()
        caller.wait_for_function('() => window.chatApp.callManager.currentCall?.offered === true', timeout=10000)
        expect(recipient.locator('#incomingCallModal')).to_be_visible(timeout=10000)
        recipient.locator('#btnAcceptCall').click()
        # Read-only processed state checks; fake devices are configured before startup, not injected here.
        caller.wait_for_function(
            "() => window.chatApp.callManager.peerConnection?.connectionState === 'connected'", timeout=20000
        )
        recipient.wait_for_function(
            "() => window.chatApp.callManager.peerConnection?.connectionState === 'connected'", timeout=20000
        )
        for page in (caller, recipient):
            assert (
                page.evaluate(
                    "window.chatApp.callManager.remoteStream.getAudioTracks().filter(t => t.readyState === 'live').length"
                )
                >= 1
            )
            if video:
                assert (
                    page.evaluate(
                        "window.chatApp.callManager.remoteStream.getVideoTracks().filter(t => t.readyState === 'live').length"
                    )
                    >= 1
                )
        if video:
            for page in (caller, recipient):
                page.wait_for_function(
                    '() => window.chatApp.callManager.elements.remoteVideo.videoWidth > 0', timeout=10000
                )
        caller.screenshot(path=destination / f'webrtc-{video}-caller.png')
        recipient.screenshot(path=destination / f'webrtc-{video}-recipient.png')
        if video:
            caller.locator('#btnShareScreen').click()
            caller.wait_for_function('() => window.chatApp.callManager.isSharingScreen === true', timeout=10000)
            recipient.wait_for_function(
                "() => window.chatApp.callManager.elements.remoteNameTag.textContent.includes('Chia sẻ màn hình')",
                timeout=10000,
            )
            caller.screenshot(path=destination / 'screen-share-caller.png')
            recipient.screenshot(path=destination / 'screen-share-recipient.png')
            caller.locator('#btnShareScreen').click()
            caller.wait_for_function('() => window.chatApp.callManager.isSharingScreen === false', timeout=10000)
        caller.locator('#btnEndCall').click()
        caller.wait_for_function('() => window.chatApp.callManager.currentCall === null')
        recipient.wait_for_function('() => window.chatApp.callManager.currentCall === null')
        for page in (caller, recipient):
            assert page.evaluate(
                'window.chatApp.callManager.localStream === null && window.chatApp.callManager.peerConnection === null'
            )
        assert not errors, errors
    finally:
        for page, label in [(caller, 'caller'), (recipient, 'recipient')]:
            if not page.is_closed():
                state = page.evaluate(
                    '() => ({error: window.chatApp.callManager.lastError, state: window.chatApp.callManager.peerConnection?.connectionState, signaling: window.chatApp.callManager.peerConnection?.signalingState, local: !!window.chatApp.callManager.localStream, remote: !!window.chatApp.callManager.remoteStream, call: window.chatApp.callManager.currentCall && {id:window.chatApp.callManager.currentCall.call_id, phase:window.chatApp.callManager.currentCall.phase, accepted:window.chatApp.callManager.currentCall.accepted, localIce:window.chatApp.callManager.currentCall.localIce.length, remoteIce:window.chatApp.callManager.currentCall.remoteIce.length}})'
                )
                (destination / f'webrtc-{video}-{label}-state.txt').write_text(str(state), encoding='utf-8')
                page.screenshot(path=destination / f'webrtc-{video}-{label}-last.png')
        (destination / f'webrtc-{video}-errors.txt').write_text('\n'.join(errors), encoding='utf-8')
        caller.close()
        recipient.close()
        other.close()
