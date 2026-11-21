import test from 'node:test';
import assert from 'node:assert/strict';
import { CallManager } from '../../app/static/js/chat/call/CallManager.js';

class FakeTarget {
    listeners = new Map();
    addEventListener(type, listener) {
        const listeners = this.listeners.get(type) || new Set();
        listeners.add(listener);
        this.listeners.set(type, listeners);
    }
    removeEventListener(type, listener) { this.listeners.get(type)?.delete(listener); }
    dispatch(type, data = {}) {
        const event = { key: '', keyCode: 0, shiftKey: false, isComposing: false, defaultPrevented: false,
            target: this, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {}, ...data };
        for (const listener of [...(this.listeners.get(type) || [])]) listener(event);
        return event;
    }
    listenerCount() { return [...this.listeners.values()].reduce((sum, listeners) => sum + listeners.size, 0); }
}
class FakeElement extends FakeTarget {
    constructor(tag, document) {
        super();
        this.tagName = tag.toUpperCase();
        this.document = document;
        this.children = [];
        this.attributes = new Map();
        this.style = { display: '', overflow: '' };
        this.dataset = {};
        this.hidden = false;
        this.disabled = false;
        this.tabIndex = ['BUTTON', 'INPUT', 'TEXTAREA'].includes(this.tagName) ? 0 : -1;
        this.value = '';
        this.textContent = '';
        this.srcObject = null;
        this.muted = false;
        this.readyState = 4;
        this.playCalls = 0;
        this.pauseCalls = 0;
        this.play = () => { ++this.playCalls; return Promise.resolve(); };
        this.pause = () => { ++this.pauseCalls; };
        this.className = '';
        this.classList = {
            contains: token => this.className.split(/\s+/).includes(token),
            add: (...tokens) => { this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...tokens])].join(' '); },
            remove: (...tokens) => { this.className = this.className.split(/\s+/).filter(token => token && !tokens.includes(token)).join(' '); },
            toggle: (token, force) => {
                const on = force ?? !this.classList.contains(token);
                this.classList[on ? 'add' : 'remove'](token);
                return on;
            }
        };
    }
    get isConnected() { return this === this.document.body || !!this.parent?.isConnected; }
    appendChild(child) { child.remove(); child.parent = this; this.children.push(child); return child; }
    append(...children) { children.forEach(child => this.appendChild(child)); }
    replaceChildren(...children) { for (const child of [...this.children]) child.remove(); this.append(...children); }
    remove() { if (this.parent) { this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; } }
    contains(target) { return this === target || this.children.some(child => child.contains(target)); }
    setAttribute(key, value) { this.attributes.set(key, String(value)); if (key === 'tabindex') this.tabIndex = Number(value); }
    getAttribute(key) { return this.attributes.get(key) ?? null; }
    removeAttribute(key) { this.attributes.delete(key); }
    matches(selector) {
        if (selector === '[hidden]') return this.hidden;
        if (selector === '[aria-hidden="true"]') return this.getAttribute('aria-hidden') === 'true';
        if (selector === '[tabindex]') return this.attributes.has('tabindex');
        if (selector.startsWith('#')) return this.id === selector.slice(1);
        if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
        return this.tagName.toLowerCase() === selector;
    }
    closest(selector) {
        for (let node = this; node; node = node.parent) if (selector.split(',').some(part => node.matches(part.trim()))) return node;
        return null;
    }
    querySelectorAll(selector) {
        const selectors = selector.split(',').map(part => part.trim());
        const results = [];
        const visit = parent => {
            for (const child of parent.children) {
                if (selectors.some(part => child.matches(part))) results.push(child);
                visit(child);
            }
        };
        visit(this);
        return results;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    getClientRects() { return this.isConnected && !this.closest('[hidden], [aria-hidden="true"]') ? [{}] : []; }
    focus() { if (!this.disabled) { this.document.activeElement = this; this.document.dispatch('focusin', { target: this }); } }
    click() { if (!this.disabled) this.dispatch('click'); }
}
class FakeDocument extends FakeTarget {
    constructor() {
        super();
        this.body = new FakeElement('body', this);
        this.activeElement = this.body;
        this.fullscreenElement = null;
        this.pictureInPictureElement = null;
        this.fullscreenEnabled = false;
        this.pictureInPictureEnabled = false;
    }
    createElement(tag) { return new FakeElement(tag, this); }
    getElementById(id) { return this.body.querySelector(`#${id}`); }
}
class FakeTrack extends FakeTarget {
    constructor(kind, id) { super(); Object.assign(this, { kind, id, enabled: true, muted: false, readyState: 'live', stopped: false }); }
    stop() { this.stopped = true; this.readyState = 'ended'; }
}
class FakeStream extends FakeTarget {
    constructor(...tracks) { super(); this.tracks = tracks; }
    getTracks() { return this.tracks; }
    getAudioTracks() { return this.tracks.filter(track => track.kind === 'audio'); }
    getVideoTracks() { return this.tracks.filter(track => track.kind === 'video'); }
    addTrack(track) { this.tracks.push(track); this.dispatch('addtrack', { track }); }
}
function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}
function fixture(options = {}) {
    const document = new FakeDocument();
    globalThis.document = document;
    const element = (tag, id, parent = document.body, className = '') => {
        const node = document.createElement(tag);
        node.id = id;
        node.className = className;
        parent.appendChild(node);
        return node;
    };
    const button = (id, parent) => {
        const node = element('button', id, parent);
        element('i', '', node);
        element('span', '', node, 'control-label');
        return node;
    };
    button('callTrigger', document.body);
    element('input', 'messageInput');
    const overlay = element('div', 'callOverlay');
    const incoming = element('div', 'incomingCallModal', overlay);
    element('span', 'incomingAvatar', incoming);
    element('h3', 'incomingName', incoming);
    element('p', 'incomingCallType', incoming);
    button('btnRejectCall', incoming);
    button('btnAcceptCall', incoming);
    const view = element('div', 'activeCallView', overlay);
    element('span', 'callChannelName', view);
    element('span', 'callerInfo', view);
    element('span', 'callDuration', view);
    element('span', 'liveIndicator', view);
    element('span', 'qualityBadge', view);
    const primary = element('div', 'primaryStream', view);
    element('video', 'remoteVideo', primary);
    const placeholder = element('div', 'remotePlaceholder', primary);
    element('span', 'remoteMediaState', placeholder);
    element('span', 'remoteNameTag', primary);
    element('div', 'callStatus', primary);
    const strip = element('div', 'participantStrip', view);
    const local = element('div', 'localParticipant', strip, 'participant-item');
    element('video', 'localVideo', local);
    const localPlaceholder = element('div', 'localPlaceholder', local, 'participant-placeholder');
    element('span', 'localMediaState', localPlaceholder);
    const localMic = element('div', 'localMicStatus', local, 'participant-status');
    element('i', '', localMic);
    for (const id of ['btnToggleMic', 'btnToggleCam', 'btnShareScreen', 'btnGridView', 'btnToggleChat',
        'btnFullscreen', 'btnPiP', 'btnPopout', 'btnMoreOptions', 'btnEndCall', 'btnPlayCallAudio']) button(id, view);
    element('span', 'callUIFeedback', view);
    const panel = element('div', 'callChatPanel', view);
    button('btnCloseCallChat', panel);
    element('div', 'callChatMessages', panel);
    element('input', 'callChatInput', panel);
    button('btnSendCallChat', panel);
    const timers = new Map();
    let nextTimer = 0;
    let time = 0;
    const emitted = [];
    const requests = [];
    const toasts = [];
    const app = { userId: 1, userName: 'Bạn', currentConversationId: 2,
        ui: { showToast: text => toasts.push(text), formatTime: () => '12:00' },
        socket: { connected: true, emit: (event, data) => { emitted.push({ event, data }); return true; },
            request: async (event, data) => { requests.push({ event, data }); return { success: true, call_id: data.call_id }; } },
        api: { getConversation: async () => ({ type: 'private' }),
            getParticipants: async () => ({ participants: [{ id: 1, name: 'Bạn' }, { id: 2, name: 'Người nhận' }] }) }
    };
    const manager = new CallManager(app, { iceServers: [],
        mediaDevices: { getDisplayMedia() {}, getUserMedia() {} },
        now: () => time, setTimer: (callback, milliseconds) => { const id = ++nextTimer; timers.set(id, { callback, milliseconds }); return id; },
        clearTimer: id => timers.delete(id), ...options });
    manager.initUI();
    const get = id => document.getElementById(id);
    const begin = (video = true, accepted = true) => {
        const call = manager.beginCall({ call_id: 'call-ui-lifecycle-0001', conversation_id: 2, isVideo: video }, 'ringing');
        call.peerName = 'Người nhận';
        call.accepted = accepted;
        return call;
    };
    const media = (video = true) => {
        const local = new FakeStream(new FakeTrack('audio', 'local-audio'), ...(video ? [new FakeTrack('video', 'local-video')] : []));
        const remote = new FakeStream(new FakeTrack('audio', 'remote-audio'), ...(video ? [new FakeTrack('video', 'remote-video')] : []));
        manager.localStream = local;
        manager.remoteStream = remote;
        manager.updatePrimaryVideo();
        return { local, remote };
    };
    const activate = call => {
        manager.peerConnection = { connectionState: 'connected', close() { this.closed = true; } };
        manager.markConnected(call);
    };
    const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
    return { manager, app, document, get, begin, media, activate, emitted, requests, toasts, timers, flush,
        setTime: value => { time = value; },
        tick: () => { const [id, timer] = timers.entries().next().value; timers.delete(id); timer.callback(); } };
}

test('direct-call local ICE waits for the answer and paces candidates behind server acknowledgements', async () => {
    const f = fixture();
    const firstAck = deferred();
    try {
        const call = f.begin(true, false);
        call.signalReady = true;
        call.localDescriptionReady = true;
        call.awaitingAnswer = true;
        call.localIce.push({ candidate: 'candidate:first' }, { candidate: 'candidate:second' });
        const original = f.app.socket.request;
        f.app.socket.request = async (event, data) => {
            if (event === 'ice_candidate' && data.candidate.candidate === 'candidate:first') {
                f.requests.push({ event, data });
                return firstAck.promise;
            }
            return original(event, data);
        };

        f.manager.flushLocalIce(call);
        await Promise.resolve();
        assert.equal(f.requests.length, 0);
        assert.equal(f.emitted.filter(item => item.event === 'ice_candidate').length, 0);
        assert.equal(call.localIce.length, 2);
        call.awaitingAnswer = false;
        f.manager.flushLocalIce(call);
        await Promise.resolve();
        assert.equal(f.requests.length, 1);
        assert.equal(f.requests[0].data.candidate.candidate, 'candidate:first');
        assert.equal(call.localIce.length, 1);
        firstAck.resolve({ success: true, call_id: call.call_id });
        await call.iceFlush;
        assert.equal(f.requests.filter(item => item.event === 'ice_candidate').length, 2);
        assert.equal(call.localIce.length, 0);
    } finally { firstAck.resolve({ success: true }); f.manager.dispose(); }
});

test('direct-call candidate acknowledgement after cancellation cannot drain the retired call', async () => {
    const f = fixture();
    const ack = deferred();
    try {
        const call = f.begin(true, false);
        call.signalReady = true;
        call.localDescriptionReady = true;
        call.localIce.push({ candidate: 'candidate:first' }, { candidate: 'candidate:retired' });
        f.app.socket.request = async (event, data) => {
            f.requests.push({ event, data });
            return ack.promise;
        };
        f.manager.flushLocalIce(call);
        await Promise.resolve();
        const pending = call.iceFlush;
        f.manager.endCall(true);
        ack.resolve({ success: true, call_id: call.call_id });
        await pending;
        assert.equal(f.requests.length, 1);
        assert.equal(f.manager.currentCall, null);
    } finally { ack.resolve({ success: true }); f.manager.dispose(); }
});

test('out-of-order media snapshots cannot restore an older mic/camera state', () => {
    const f = fixture();
    const call = f.begin();
    f.media();
    f.activate(call);
    const payload = { call_id: call.call_id, conversation_id: call.conversation_id };
    f.manager.handleMediaStatus({ ...payload, type: 'mic', enabled: false, revision: 3 });
    f.manager.handleMediaStatus({ ...payload, type: 'mic', enabled: true, revision: 1 });
    f.manager.handleMediaStatus({ ...payload, type: 'mic', enabled: true });
    assert.equal(call.remoteMedia.mic, false);
    assert.equal(f.get('remoteMicStatus').getAttribute('aria-label'), 'Micro đã tắt');
    f.manager.handleMediaStatus({ ...payload, type: 'cam', enabled: false, revision: 3 });
    f.manager.handleMediaStatus({ ...payload, type: 'cam', enabled: true, revision: 2 });
    assert.equal(call.remoteMedia.cam, false);
    f.manager.handleMediaStatus({ ...payload, type: 'mic', enabled: true, revision: 4 });
    assert.equal(call.remoteMedia.mic, true);
    f.manager.dispose();
});

test('legacy media events still update repeatedly until a sequenced state is observed', () => {
    const f = fixture();
    const call = f.begin();
    f.media();
    const payload = { call_id: call.call_id, conversation_id: call.conversation_id, type: 'mic' };
    f.manager.handleMediaStatus({ ...payload, enabled: false });
    f.manager.handleMediaStatus({ ...payload, enabled: true });
    assert.equal(call.remoteMedia.mic, true);
    f.manager.dispose();
});

test('incoming voice/video copy and all toggle buttons expose actual state and names', () => {
    const f = fixture();
    const call = f.begin(false, false);
    f.manager.showOverlay();
    f.manager.showIncomingModal({ sender_name: 'Untrusted label' });
    assert.equal(f.get('incomingCallType').textContent, 'Cuộc gọi thoại đến');
    assert.equal(f.get('incomingName').textContent, 'Người nhận');
    assert.match(f.get('btnAcceptCall').getAttribute('aria-label'), /thoại/);
    assert.equal(f.document.activeElement, f.get('btnAcceptCall'));
    assert.equal(f.get('callDuration').hidden, true);
    call.isVideo = true;
    f.manager.showIncomingModal({});
    assert.equal(f.get('incomingCallType').textContent, 'Cuộc gọi video đến');
    f.manager.showOutgoingModal('Người nhận');
    assert.equal(f.get('btnAcceptCall').hidden, true);
    assert.equal(f.get('btnRejectCall').querySelector('.control-label').textContent, 'Hủy cuộc gọi');
    call.accepted = true;
    const { local } = f.media();
    f.manager.showActiveView();
    for (const id of ['btnToggleMic', 'btnToggleCam', 'btnShareScreen', 'btnGridView', 'btnToggleChat', 'btnFullscreen', 'btnPiP']) {
        assert.ok(f.get(id).getAttribute('aria-label'));
        assert.match(f.get(id).getAttribute('aria-pressed'), /^(true|false)$/);
        assert.equal(f.get(id).querySelector('i').getAttribute('aria-hidden'), 'true');
    }
    assert.equal(f.get('btnToggleMic').getAttribute('aria-pressed'), 'true');
    f.get('btnToggleMic').click();
    assert.equal(local.getAudioTracks()[0].enabled, false);
    assert.equal(f.get('btnToggleMic').getAttribute('aria-pressed'), 'false');
    assert.equal(f.get('btnToggleMic').querySelector('.control-label').textContent, 'Bật micro');
    f.get('btnToggleCam').click();
    assert.equal(f.get('localVideo').style.display, 'none');
    assert.equal(f.get('localPlaceholder').style.display, 'flex');
    assert.equal(f.get('localMediaState').textContent, 'Camera đã tắt');
    assert.equal(f.get('qualityBadge').hidden, true);
    assert.equal(f.get('btnPopout').hidden, true);
    f.manager.dispose();
});

test('grid retains both actual streams, stable participant and one audio sink even in local focus', async () => {
    const f = fixture();
    const call = f.begin();
    const { local, remote } = f.media();
    f.activate(call);
    await f.flush();
    const participant = f.get('remoteParticipant');
    const audio = f.get('callRemoteAudio');
    assert.equal(audio.srcObject, remote);
    assert.equal(audio.muted, false);
    assert.equal(f.get('remoteParticipantVideo').srcObject, remote);
    f.manager.toggleGridView();
    assert.equal(f.get('localVideo').srcObject, local);
    assert.equal(f.get('remoteParticipantVideo').srcObject, remote);
    assert.equal(f.get('remoteParticipantVideo').muted, true);
    assert.equal(f.get('remoteVideo').muted, true);
    f.manager.updatePrimaryVideo();
    assert.equal(f.manager.isGridView, true);
    assert.equal(f.get('remoteParticipant'), participant);
    f.get('localParticipant').dispatch('keydown', { key: 'Enter' });
    assert.equal(f.manager.isGridView, false);
    assert.equal(f.get('remoteVideo').srcObject, local);
    assert.equal(audio.srcObject, remote);
    assert.equal(audio.muted, false);
    f.manager.toggleGridView();
    assert.equal(audio, f.get('callRemoteAudio'));
    assert.equal(f.document.body.querySelectorAll('audio').length, 1);
    f.manager.dispose();
    assert.equal(audio.srcObject, null);
    assert.equal(audio.isConnected, false);
});

test('voice and remote camera-off/mute/ended tracks produce truthful primary and tile placeholders', async () => {
    const f = fixture();
    const call = f.begin(false);
    const { remote } = f.media(false);
    f.activate(call);
    await f.flush();
    assert.equal(f.get('btnToggleCam').disabled, true);
    assert.equal(f.get('remoteMediaState').textContent, 'Cuộc gọi thoại');
    assert.equal(f.get('localMediaState').textContent, 'Cuộc gọi thoại');
    assert.equal(f.get('remotePlaceholder').style.display, 'flex');
    assert.equal(f.get('remoteParticipantPlaceholder').style.display, 'flex');
    call.isVideo = true;
    const remoteVideo = new FakeTrack('video', 'remote-video');
    remote.addTrack(remoteVideo);
    assert.equal(f.get('remoteVideo').style.display, 'block');
    f.manager.handleMediaStatus({ call_id: call.call_id, conversation_id: 2, type: 'cam', enabled: false });
    assert.equal(f.get('remoteVideo').style.display, 'none');
    assert.equal(f.get('remoteParticipantVideo').style.display, 'none');
    assert.equal(f.get('remoteMediaState').textContent, 'Camera đã tắt');
    f.manager.handleMediaStatus({ call_id: 'another-call-12345', conversation_id: 2, type: 'cam', enabled: true });
    assert.equal(f.get('remoteVideo').style.display, 'none');
    f.manager.handleMediaStatus({ call_id: call.call_id, conversation_id: 2, type: 'cam', enabled: true });
    remoteVideo.muted = true;
    remoteVideo.dispatch('mute');
    assert.equal(f.get('remoteMediaState').textContent, 'Video đang tạm dừng');
    remoteVideo.muted = false;
    remoteVideo.dispatch('unmute');
    assert.equal(f.get('remoteVideo').style.display, 'block');
    remoteVideo.readyState = 'ended';
    remoteVideo.dispatch('ended');
    assert.equal(f.get('remotePlaceholder').style.display, 'flex');
    f.manager.dispose();
    assert.equal(remoteVideo.listenerCount(), 0);
    assert.equal(remote.listenerCount(), 0);
});

test('duration starts only when connected, uses elapsed time, survives repeated connect and tears down', () => {
    const f = fixture();
    const call = f.begin();
    f.manager.peerConnection = { connectionState: 'connecting', close() {} };
    f.manager.markConnected(call);
    assert.equal(f.get('callDuration').hidden, true);
    assert.equal(f.timers.size, 0);
    f.setTime(5000);
    f.activate(call);
    assert.equal(f.get('callDuration').textContent, '00:00');
    assert.equal(f.get('callDuration').hidden, false);
    assert.equal(f.get('callDuration').getAttribute('aria-live'), 'off');
    assert.equal(f.timers.size, 1);
    const staleTick = f.timers.values().next().value.callback;
    f.setTime(71000);
    f.tick();
    assert.equal(f.get('callDuration').textContent, '01:06');
    f.manager.markConnected(call);
    assert.equal(f.timers.size, 1);
    f.setTime(3606000);
    f.tick();
    assert.equal(f.get('callDuration').textContent, '01:00:01');
    f.manager.endCall(true);
    assert.equal(f.timers.size, 0);
    assert.equal(f.get('callDuration').hidden, true);
    staleTick();
    assert.equal(f.timers.size, 0);
    f.begin();
    staleTick();
    assert.equal(f.timers.size, 0);
    f.manager.dispose();
});

test('focus is protected across ring/active/chat/grid and restores prior focus and body scroll', () => {
    const f = fixture();
    const call = f.begin();
    f.document.body.style.overflow = 'auto';
    f.get('callTrigger').focus();
    f.manager.showOverlay();
    f.manager.showIncomingModal({});
    assert.equal(f.document.body.style.overflow, 'hidden');
    f.manager.hideIncomingModal();
    f.manager.showActiveView();
    assert.equal(f.document.activeElement, f.get('btnEndCall'));
    f.manager.isCallActive = true;
    f.manager.toggleCallChat(true);
    assert.equal(f.document.activeElement, f.get('callChatInput'));
    assert.equal(f.get('btnToggleChat').getAttribute('aria-expanded'), 'true');
    const focusable = f.get('callOverlay').querySelectorAll('button, input, textarea, select, a[href], [tabindex]').filter(node =>
        !node.disabled && node.tabIndex >= 0 && !node.closest('[hidden], [aria-hidden="true"]') && node.getClientRects().length);
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    last.focus();
    assert.equal(f.get('callOverlay').dispatch('keydown', { key: 'Tab' }).defaultPrevented, true);
    assert.equal(f.document.activeElement, first);
    assert.equal(f.get('callOverlay').dispatch('keydown', { key: 'Tab', shiftKey: true }).defaultPrevented, true);
    assert.equal(f.document.activeElement, last);
    f.get('callOverlay').dispatch('keydown', { key: 'Escape' });
    assert.equal(f.document.activeElement, f.get('btnToggleChat'));
    assert.equal(f.get('callChatPanel').hidden, true);
    f.manager.toggleCallChat(true);
    f.manager.toggleGridView(true);
    assert.equal(f.document.activeElement, f.get('btnGridView'));
    assert.equal(f.get('callChatPanel').hidden, true);
    f.manager.toggleCallChat(true);
    assert.equal(f.manager.isGridView, false);
    f.get('callTrigger').focus();
    assert.equal(f.document.activeElement, f.get('btnEndCall'));
    f.manager.markConnected(call);
    f.manager.endCall(true);
    assert.equal(f.document.activeElement, f.get('callTrigger'));
    assert.equal(f.document.body.style.overflow, 'auto');
    assert.equal(f.document.listenerCount(), 0);
    assert.equal(f.get('callOverlay').listenerCount(), 0);
    f.manager.dispose();
});

test('call chat Enter ignores IME/Safari composition, shifts and handled events, sends one acked message', async () => {
    const f = fixture();
    const call = f.begin();
    f.activate(call);
    const input = f.get('callChatInput');
    input.value = 'Xin chào';
    for (const data of [{ isComposing: true }, { keyCode: 229 }, { shiftKey: true }, { defaultPrevented: true }]) {
        input.dispatch('keydown', { key: 'Enter', ...data });
    }
    assert.equal(f.requests.length, 0);
    input.dispatch('input');
    const event = input.dispatch('keydown', { key: 'Enter' });
    assert.equal(event.defaultPrevented, true);
    assert.equal(f.get('btnSendCallChat').disabled, true);
    assert.equal(f.get('btnSendCallChat').getAttribute('aria-busy'), 'true');
    await f.flush();
    assert.equal(f.requests.length, 1);
    assert.equal(f.requests[0].data.text, 'Xin chào');
    assert.equal(input.value, '');
    assert.equal(f.get('callChatMessages').children.length, 1);
    const pending = deferred();
    f.app.socket.request = () => pending.promise;
    input.value = 'Bản nháp';
    const send = f.manager.sendCallChatMessage();
    pending.reject(new Error('Máy chủ từ chối'));
    assert.equal(await send, false);
    assert.equal(input.value, 'Bản nháp');
    assert.match(f.get('callUIFeedback').textContent, /Máy chủ từ chối/);
    assert.equal(f.get('btnSendCallChat').getAttribute('aria-busy'), 'false');
    f.manager.endCall(true);
    assert.equal(input.value, '');
    assert.equal(f.get('callChatMessages').children.length, 0);
    f.manager.dispose();
    assert.equal(input.listenerCount(), 0);
    assert.equal(f.get('btnToggleChat').listenerCount(), 0);
});

test('fullscreen/PiP are unavailable without support and track real browser state and failures', async () => {
    const f = fixture();
    const call = f.begin();
    f.media();
    f.activate(call);
    const overlay = f.get('callOverlay');
    const video = f.get('remoteVideo');
    assert.equal(f.get('btnFullscreen').disabled, true);
    assert.equal(f.get('btnPiP').hidden, true);
    f.document.fullscreenEnabled = true;
    overlay.requestFullscreen = async () => { f.document.fullscreenElement = overlay; f.document.dispatch('fullscreenchange'); };
    f.document.exitFullscreen = async () => { f.document.fullscreenElement = null; f.document.dispatch('fullscreenchange'); };
    f.document.pictureInPictureEnabled = true;
    video.requestPictureInPicture = async () => { f.document.pictureInPictureElement = video; video.dispatch('enterpictureinpicture'); };
    f.document.exitPictureInPicture = async () => { f.document.pictureInPictureElement = null; video.dispatch('leavepictureinpicture'); };
    f.manager.updateBrowserControls();
    assert.equal(f.get('btnFullscreen').disabled, false);
    assert.equal(await f.manager.toggleFullscreen(), true);
    assert.equal(f.get('btnFullscreen').getAttribute('aria-pressed'), 'true');
    assert.equal(await f.manager.toggleFullscreen(), true);
    assert.equal(f.get('btnFullscreen').getAttribute('aria-pressed'), 'false');
    assert.equal(await f.manager.togglePictureInPicture(), true);
    assert.equal(f.get('btnPiP').getAttribute('aria-pressed'), 'true');
    assert.equal(await f.manager.togglePictureInPicture(), true);
    const browserError = new Error('Permission denied');
    overlay.requestFullscreen = async () => { throw browserError; };
    assert.equal(await f.manager.toggleFullscreen(), false);
    assert.equal(f.manager.lastUIError, browserError);
    assert.match(f.get('callUIFeedback').textContent, /Permission denied/);
    assert.equal(f.get('btnFullscreen').getAttribute('aria-pressed'), 'false');
    assert.equal(f.get('btnFullscreen').disabled, false);
    assert.equal(f.get('btnFullscreen').getAttribute('aria-busy'), 'false');
    const capture = deferred();
    overlay.requestFullscreen = () => capture.promise;
    const action = f.manager.toggleFullscreen();
    assert.equal(f.get('btnFullscreen').disabled, true);
    f.manager.endCall(true);
    f.document.fullscreenElement = overlay;
    capture.resolve();
    assert.equal(await action, false);
    assert.equal(f.document.fullscreenElement, null);
    assert.equal(f.get('remoteParticipant'), null);
    f.manager.dispose();
});

test('screen-share permission state is pending, cancellable and never suppresses browser error detail', async () => {
    const f = fixture();
    const call = f.begin();
    const { local } = f.media();
    f.activate(call);
    const replacements = [];
    call.videoSender = { replaceTrack: async track => { replacements.push(track); } };
    const capture = deferred();
    f.manager.mediaDevices.getDisplayMedia = () => capture.promise;
    const start = f.manager.startScreenShare();
    assert.equal(f.get('btnShareScreen').disabled, true);
    assert.equal(f.get('btnShareScreen').getAttribute('aria-busy'), 'true');
    const error = Object.assign(new Error('Sharing permission declined'), { name: 'NotAllowedError' });
    capture.reject(error);
    assert.equal(await start, false);
    assert.match(f.get('callUIFeedback').textContent, /Sharing permission declined/);
    assert.equal(f.manager.lastUIError, error);
    assert.equal(f.get('btnShareScreen').disabled, false);
    assert.equal(f.get('btnShareScreen').getAttribute('aria-pressed'), 'false');
    const display = new FakeStream(new FakeTrack('video', 'screen-video'));
    f.manager.mediaDevices.getDisplayMedia = async () => display;
    assert.equal(await f.manager.startScreenShare(), true);
    assert.equal(f.get('btnShareScreen').getAttribute('aria-pressed'), 'true');
    assert.equal(f.get('btnShareScreen').getAttribute('aria-busy'), 'false');
    assert.equal(f.get('localVideo').srcObject, display);
    assert.equal(await f.manager.stopScreenShare(), true);
    assert.equal(replacements.at(-1), local.getVideoTracks()[0]);
    assert.equal(f.get('localVideo').srcObject, local);
    assert.equal(f.get('btnShareScreen').getAttribute('aria-pressed'), 'false');
    assert.equal(display.getTracks()[0].stopped, true);
    const late = deferred();
    f.manager.mediaDevices.getDisplayMedia = () => late.promise;
    const lateStart = f.manager.startScreenShare();
    f.manager.endCall(true);
    const lateStream = new FakeStream(new FakeTrack('video', 'late-screen'));
    late.resolve(lateStream);
    assert.equal(await lateStart, false);
    assert.equal(lateStream.getTracks()[0].stopped, true);
    assert.equal(f.get('callRemoteAudio'), null);
    assert.equal(f.get('remoteParticipant'), null);
    f.manager.dispose();
});

test('blocked remote audio has a real recovery action and late failures cannot revive closed UI', async () => {
    const f = fixture();
    const call = f.begin(false);
    const create = f.document.createElement.bind(f.document);
    const denied = new Error('Autoplay denied');
    f.document.createElement = tag => {
        const element = create(tag);
        if (tag === 'audio') element.play = () => Promise.reject(denied);
        return element;
    };
    f.media(false);
    f.activate(call);
    await f.flush();
    assert.equal(f.get('btnPlayCallAudio').hidden, false);
    assert.match(f.get('callUIFeedback').textContent, /Autoplay denied/);
    f.get('callRemoteAudio').play = () => Promise.resolve();
    f.get('btnPlayCallAudio').click();
    await f.flush();
    assert.equal(f.get('btnPlayCallAudio').hidden, true);
    assert.equal(f.get('callUIFeedback').textContent, '');
    const pending = deferred();
    f.get('callRemoteAudio').play = () => pending.promise;
    const playback = f.manager.playRemoteAudio();
    f.manager.endCall(true);
    pending.reject(new Error('Late playback error'));
    assert.equal(await playback, false);
    assert.equal(f.get('btnPlayCallAudio').hidden, true);
    assert.equal(f.get('callUIFeedback').textContent, '');
    assert.equal(f.get('callRemoteAudio'), null);
    f.manager.dispose();
});
