import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


def login_group(page, email):
    page.goto('/login')
    page.get_by_label('Email', exact=True).fill(email)
    page.get_by_label('Mật khẩu', exact=True).fill('TestUser123!')
    page.locator('form[action="/login"] button[type="submit"]').click()
    expect(page).to_have_url(re.compile(r'/(?:admin)?$'))
    page.goto('/messages')
    page.locator('.conv-item').filter(has_text='Synthetic Small Group').click()
    expect(page.locator('#activeChatContainer')).to_have_attribute('aria-busy', 'false')
    page.wait_for_function('() => window.chatApp.socket.connected')
    expect(page.locator('#btnVideo')).to_be_enabled()


def context(browser, base_url):
    value = browser.new_context(
        base_url=base_url,
        permissions=['camera', 'microphone'],
        viewport={'width': 1280, 'height': 900},
    )
    value.set_default_timeout(10000)
    value.route('https://**/*', lambda route: route.abort())
    return value


def test_three_member_mesh_exchanges_media_shares_chat_and_survives_one_leave(gui_context, browser, live_app):
    base_url, application = live_app
    second_context, third_context = context(browser, base_url), context(browser, base_url)
    owner, second, third = gui_context.new_page(), second_context.new_page(), third_context.new_page()
    errors = []
    for page in (owner, second, third):
        page.on('pageerror', lambda error: errors.append(str(error)))
    evidence = ROOT / 'artifacts' / 'e2e' / 'mesh'
    evidence.mkdir(parents=True, exist_ok=True)
    try:
        login_group(owner, 'customer@example.test')
        login_group(second, 'admin@example.test')
        login_group(third, 'other@example.test')

        owner.locator('#btnVideo').click()
        for page in (second, third):
            expect(page.locator('#meshCallOverlay')).to_be_visible(timeout=15000)
            expect(page.locator('#meshCallAccept')).to_be_enabled()
        second.locator('#meshCallAccept').click()
        second.wait_for_function(
            '() => window.chatApp.meshCallManager.currentCall?.accepted === true && '
            'window.chatApp.meshCallManager.currentCall?.serverJoined === true',
            timeout=15000,
        )
        owner.wait_for_function(
            '() => window.chatApp.meshCallManager.currentCall?.pairs.size === 1',
            timeout=15000,
        )
        third.locator('#meshCallAccept').click()
        third.wait_for_function(
            '() => window.chatApp.meshCallManager.currentCall?.accepted === true && '
            'window.chatApp.meshCallManager.currentCall?.serverJoined === true',
            timeout=15000,
        )
        owner.wait_for_function(
            '() => window.chatApp.meshCallManager.currentCall?.pairs.size === 2',
            timeout=15000,
        )

        for page in (owner, second, third):
            page.wait_for_function(
                """() => window.chatApp.meshCallManager.remotePeers.size === 2 &&
                    [...window.chatApp.meshCallManager.remotePeers.values()].every(peer =>
                        peer.pc.connectionState === 'connected' &&
                        peer.remoteStream.getAudioTracks().some(track => track.readyState === 'live') &&
                        peer.remoteStream.getVideoTracks().some(track => track.readyState === 'live'))""",
                timeout=30000,
            )

            expect(page.locator('#meshCallGrid .mesh-call-tile')).to_have_count(3)
            expect(page.locator('#meshCallAudioSinks audio')).to_have_count(2)
            page.wait_for_function(
                """() => [...document.querySelectorAll('#meshCallGrid .mesh-call-tile')]
                    .filter(tile => tile.dataset.userId !== String(window.chatApp.userId))
                    .every(tile => tile.querySelector('video').videoWidth > 0)""",
                timeout=15000,
            )
        owner.screenshot(path=evidence / 'mesh-three-video-owner.png')
        second.screenshot(path=evidence / 'mesh-three-video-second.png')
        third.screenshot(path=evidence / 'mesh-three-video-third.png')

        owner.locator('#meshCallMic').click()
        expect(second.locator('[data-user-id="1"] .mesh-call-tile-state')).to_contain_text('Micro tắt')
        expect(third.locator('[data-user-id="1"] .mesh-call-tile-state')).to_contain_text('Micro tắt')
        owner.locator('#meshCallMic').click()
        expect(second.locator('[data-user-id="1"] .mesh-call-tile-state')).to_contain_text('Micro bật')

        owner.locator('#meshCallChatToggle').click()
        owner.locator('#meshCallChatInput').fill('Tin nhắn mesh ba người có dấu')
        owner.locator('#meshCallChatSend').click()
        for page in (second, third):
            expect(page.locator('#meshCallChatList')).to_contain_text('Tin nhắn mesh ba người có dấu')

        owner.locator('#meshCallShare').click()
        owner.wait_for_function('() => window.chatApp.meshCallManager.isSharingScreen === true')
        for page in (second, third):
            tile = page.locator('#meshCallGrid .mesh-call-tile[data-user-id="1"]')
            expect(tile).to_have_attribute('data-sharing', 'true')
            page.wait_for_function(
                """() => document.querySelector('#meshCallGrid .mesh-call-tile[data-user-id="1"] video').videoWidth > 0""",
                timeout=15000,
            )
        owner.screenshot(path=evidence / 'mesh-screen-owner.png')
        second.screenshot(path=evidence / 'mesh-screen-recipient.png')
        owner.locator('#meshCallShare').click()
        owner.wait_for_function('() => window.chatApp.meshCallManager.isSharingScreen === false')

        owner.set_viewport_size({'width': 390, 'height': 844})
        assert not owner.evaluate('document.documentElement.scrollWidth > innerWidth')
        owner.screenshot(path=evidence / 'mesh-three-mobile.png')
        owner.set_viewport_size({'width': 1280, 'height': 900})

        third.locator('#meshCallEnd').click()
        expect(third.locator('#meshCallOverlay')).not_to_be_visible()
        for page in (owner, second):
            page.wait_for_function(
                '() => window.chatApp.meshCallManager.remotePeers.size === 1 && '
                '[...window.chatApp.meshCallManager.remotePeers.values()][0].pc.connectionState === "connected"'
            )
            expect(page.locator('#meshCallGrid .mesh-call-tile')).to_have_count(2)
        owner.screenshot(path=evidence / 'mesh-after-one-leave.png')

        owner.locator('#meshCallEnd').click()
        expect(owner.locator('#meshCallOverlay')).not_to_be_visible()
        expect(second.locator('#meshCallOverlay')).not_to_be_visible()
        for page in (owner, second, third):
            assert page.evaluate(
                'window.chatApp.meshCallManager.currentCall === null && '
                'window.chatApp.meshCallManager.remotePeers.size === 0 && '
                'window.chatApp.meshCallManager.localStream === null'
            )
        assert not errors, errors
    except Exception:
        for page, name in [(owner, 'owner'), (second, 'second'), (third, 'third')]:
            state = page.evaluate(
                """() => {
                    const manager = window.chatApp?.meshCallManager;
                    const call = manager?.currentCall;
                    return {
                        call: call && {phase: call.phase, revision: call.revision, accepted: call.accepted,
                            serverJoined: call.serverJoined, mediaRevision: call.mediaRevision},
                        media: call ? [...call.media.entries()].map(([id, item]) =>
                            ({id, mic: item.mic, cam: item.cam, sharing: item.sharing, revisions: item.revisions})) : null,
                        peerStates: manager ? [...manager.remotePeers.values()].map(peer => ({
                            userId: peer.userId, connection: peer.pc.connectionState,
                            iceQueued: peer.localIce.length, awaitingAnswer: peer.awaitingAnswer})) : null,
                        pendingRequests: window.chatApp?.socket?.pendingRequests.size,
                        lastError: manager?.lastError || null,
                        localTracks: manager?.localStream?.getTracks().map(track => ({
                            kind: track.kind, enabled: track.enabled, state: track.readyState})) || null
                    };
                }"""
            )
            (evidence / f'mesh-failure-{name}.json').write_text(json.dumps(state), encoding='utf-8')
        registry = application.extensions['chat_socket_handlers'].mesh_calls
        with registry.lock:
            server_snapshots = [registry._snapshot(room) for room in registry.calls.values()]
        (evidence / 'mesh-failure-server.json').write_text(json.dumps(server_snapshots), encoding='utf-8')
        raise
    finally:
        owner.close()
        second.close()
        third.close()
        second_context.close()
        third_context.close()
