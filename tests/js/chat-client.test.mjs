import test from 'node:test';
import assert from 'node:assert/strict';

const elements = new Map();
globalThis.document = {
    getElementById: id => elements.get(id) || null,
    querySelector: () => null, querySelectorAll: () => [],
    addEventListener() {}, activeElement: null, hidden: false,
};
globalThis.window = { addEventListener() {} };

const { default: ChatAPI } = await import('../../app/static/js/chat/core/ChatAPI.js');
const { shouldSendOnEnter } = await import('../../app/static/js/chat/utils/helpers.js');
const { default: ChatSocket } = await import('../../app/static/js/chat/core/ChatSocket.js');
const { ChatApp } = await import('../../app/static/js/chat/core/ChatApp.js');
const { default: CallState } = await import('../../app/static/js/chat/call/CallState.js');
const { CallManager } = await import('../../app/static/js/chat/call/CallManager.js');

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}
const credentials = { session_id: '12345678-1234-1234-1234-123456789abc', auth_token: 'server-signed', expires_in: 3600 };
const response = (data, ok = true) => ({ ok, status: ok ? 200 : 403, json: async () => data });

function fakeUI() {
    return { renderConversationList() {}, hideReplyShelf() {}, renderSettings() {}, switchChatUI() {},
        appendMessage() {}, showToast() {}, formatTime: () => '', showPinnedShelf() {}, renderSeenStatus() {} };
}
function fakeClassList() { return { add() {}, remove() {}, toggle() {} }; }
function track(kind = 'audio') {
    return { kind, stopped: false, enabled: true, id: kind, stop() { this.stopped = true; } };
}
function stream(...tracks) { return { getTracks: () => tracks, getAudioTracks: () => tracks.filter(item => item.kind === 'audio'), getVideoTracks: () => tracks.filter(item => item.kind === 'video') }; }

test('Enter submits only once outside IME, modifier keys and multiline composition', () => {
    assert.equal(shouldSendOnEnter({ key: 'Enter' }), true);
    for (const guard of [
        { shiftKey: true }, { ctrlKey: true }, { metaKey: true }, { altKey: true },
        { isComposing: true }, { keyCode: 229 }, { repeat: true }, { defaultPrevented: true },
    ]) assert.equal(shouldSendOnEnter({ key: 'Enter', ...guard }), false);
    assert.equal(shouldSendOnEnter({ key: 'a' }), false);
});

function readState(socket) {
    return Object.assign(Object.create(ChatApp.prototype), {
        closed: false, hasSelectedConversation: true, userId: 1, currentConversationId: 2,
        pendingReads: new Map(), conversations: [{ id: 2, unread_count: 3 }],
        conversationRevision: 0, socket, scope: id => ({ conversation_id: id }),
        refreshConversationList() { this.rendered = (this.rendered || 0) + 1; },
        scheduleConversationRefresh() { this.refreshed = true; },
    });
}

test('unread clears only after read receipt ACK and concurrent reads coalesce', async () => {
    const pending = deferred();
    let requests = 0;
    const app = readState({ connected: true, request(event, data) {
        ++requests;
        assert.equal(event, 'mark_read');
        assert.deepEqual(data, { conversation_id: 2 });
        return pending.promise;
    } });
    const first = app.markRead();
    const second = app.markRead();
    assert.equal(requests, 1);
    assert.equal(app.conversations[0].unread_count, 3);
    pending.resolve({ success: true });
    await Promise.all([first, second]);
    assert.equal(app.conversations[0].unread_count, 0);
    assert.equal(app.rendered, 1);
    assert.equal(app.refreshed, true);
    assert.equal(app.pendingReads.size, 0);
});

test('failed read receipt never clears the badge or reports optimistic success', async () => {
    const app = readState({ connected: true, request: async () => { throw new Error('Denied'); } });
    await assert.rejects(app.markRead(), /Denied/);
    assert.equal(app.conversations[0].unread_count, 3);
    assert.equal(app.rendered, undefined);
    assert.equal(app.pendingReads.size, 0);
});

test('read receipt uses HTTP when disconnected and hidden pages never mark read', async () => {
    const app = readState({ connected: false });
    const ids = [];
    app.api = { markAsRead: async id => ids.push(id) };
    await app.markRead();
    assert.deepEqual(ids, [2]);
    assert.equal(app.conversations[0].unread_count, 0);
    document.hidden = true;
    try { await app.markRead(); assert.deepEqual(ids, [2]); }
    finally { document.hidden = false; }
});

test('late read ACK after page disposal cannot rerender stale state', async () => {
    const pending = deferred();
    const app = readState({ connected: true, request: () => pending.promise });
    const read = app.markRead();
    app.closed = true;
    pending.resolve({ success: true });
    await read;
    assert.equal(app.conversations[0].unread_count, 3);
    assert.equal(app.rendered, undefined);
});

test('conversation list ignores stale responses when invalidation races refresh', async () => {
    const first = deferred(), second = deferred();
    let requests = 0;
    const app = Object.assign(Object.create(ChatApp.prototype), {
        userId: 1, closed: false, conversationRevision: 0, ui: fakeUI(),
        api: { getConversations: () => ++requests === 1 ? first.promise : second.promise },
        refreshConversationList() { this.rendered = (this.rendered || 0) + 1; },
    });
    const oldLoad = app.loadConversations();
    const newLoad = app.loadConversations();
    second.resolve({ conversations: [{ id: 2, unread_count: 5 }] });
    await newLoad;
    first.resolve({ conversations: [{ id: 2, unread_count: 1 }] });
    await oldLoad;
    assert.equal(app.conversations[0].unread_count, 5);
    assert.equal(app.rendered, 1);
});

test('API coalesces fresh credentials and never requests history before issuance', async () => {
    const pending = deferred();
    const calls = [];
    const original = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
        calls.push({ url, options });
        if (url === '/api/chat/guest-session') return pending.promise;
        return response({ messages: [] });
    };
    try {
        const api = new ChatAPI('csrf');
        const history = api.getHistory(null);
        assert.equal(calls.length, 1);
        pending.resolve(response(credentials));
        await history;
        assert.equal(calls.length, 2);
        assert.match(calls[1].url, /session_id=12345678/);
        assert.equal(calls[1].options.headers['X-Chat-Token'], 'server-signed');
        assert.equal(calls[0].options.headers['X-CSRFToken'], 'csrf');
    } finally { globalThis.fetch = original; }
});

test('API rejects malformed credentials and never tokenizes external attachments', async () => {
    const original = globalThis.fetch;
    globalThis.fetch = async () => response({ ...credentials, session_id: 'caller-uuid' });
    try {
        const api = new ChatAPI('csrf');
        await assert.rejects(api.ensureGuestSession(), /không hợp lệ/);
        assert.equal(api.authToken, null);
        assert.equal(api.attachmentUrl('https://evil.test/file'), null);
        api.authToken = 'signed'; api.expiresAt = Date.now() + 1000;
        assert.equal(api.attachmentUrl('/api/chat/attachments/1'), '/api/chat/attachments/1?auth_token=signed');
        api.authenticated = true;
        assert.equal(api.attachmentUrl('/api/chat/attachments/1'), '/api/chat/attachments/1');
    } finally { globalThis.fetch = original; }
});

test('disconnected Socket.IO mutations are rejected, not buffered', async () => {
    const app = { csrfToken: 'csrf', ui: fakeUI() };
    let emits = 0;
    const socket = new ChatSocket(credentials, app, () => ({ connected: false, on() {}, emit() { ++emits; }, disconnect() {} }));
    assert.equal(socket.emit('send_message', {}), false);
    await assert.rejects(socket.request('send_message', {}), /Chưa kết nối/);
    assert.equal(emits, 0);
    socket.close();
});

test('Socket.IO request waits for server acknowledgement and preserves failures', async () => {
    let acknowledge;
    const socket = new ChatSocket(credentials, { csrfToken: 'csrf', ui: fakeUI() }, () => ({ connected: true, on() {}, emit(_event, _data, ack) { acknowledge = ack; }, disconnect() {} }));
    const request = socket.request('send_message', { content: 'Test' });
    acknowledge({ success: false, message: 'Denied', status: 403 });
    await assert.rejects(request, /Denied/);
    assert.equal(socket.pendingRequests.size, 0);
    socket.close();
});

test('ChatApp does not construct or connect socket before credentials', async () => {
    const pending = deferred();
    const order = [];
    const api = { ensureGuestSession: () => pending.promise, scope: sid => ({ session_id: sid }), getHistory: async () => ({ messages: [] }) };
    const callManager = { initUI() { order.push('ui'); }, dispose() {} };
    const app = new ChatApp({}, { api, ui: fakeUI(), viewer: {}, recorder: { cancel() {} }, callManager,
        socketFactory(value) { order.push('construct'); assert.equal(value.auth_token, 'server-signed'); return { connect() { order.push('connect'); }, close() {} }; } });
    assert.deepEqual(order, []);
    pending.resolve(credentials);
    assert.equal(await app.ready, true);
    assert.deepEqual(order, ['construct', 'ui', 'connect']);
    assert.equal(app.sessionId, credentials.session_id);
    assert.equal(app.hasSelectedConversation, false);
    app.dispose();
});

test('closing ChatApp during credential issuance cannot create a late socket', async () => {
    const pending = deferred();
    let constructed = false;
    const app = new ChatApp({}, { api: { ensureGuestSession: () => pending.promise }, ui: fakeUI(), viewer: {},
        recorder: { cancel() {} }, callManager: { dispose() {} }, socketFactory() { constructed = true; } });
    app.dispose();
    pending.resolve(credentials);
    assert.equal(await app.ready, false);
    assert.equal(constructed, false);
});

test('message ownership is based on persisted user identity, not the admin sender label', () => {
    const state = { userId: 2, sessionId: 'bound-guest' };
    assert.equal(ChatApp.prototype.isOwnMessage.call(state, { user_id: 1, sender_type: 'admin' }), false);
    assert.equal(ChatApp.prototype.isOwnMessage.call(state, { user_id: 2 }), true);
    assert.equal(ChatApp.prototype.isOwnMessage.call({ userId: null, sessionId: 'bound-guest' }, { user_id: null, sender_type: 'user', session_id: 'other' }), false);
});

test('recording cancellation stops late microphone tracks and never publishes a blob', async () => {
    const { default: ChatRecorder } = await import('../../app/static/js/chat/media/MediaRecorder.js');
    const pending = deferred();
    const audio = track();
    const previousNavigator = globalThis.navigator;
    const previousRecorder = globalThis.MediaRecorder;
    Object.defineProperty(globalThis, 'navigator', { value: { mediaDevices: { getUserMedia: () => pending.promise } }, configurable: true });
    globalThis.MediaRecorder = class { static isTypeSupported() { return true; } };
    let sent = false;
    try {
        const recorder = new ChatRecorder(() => { sent = true; });
        const start = recorder.start();
        recorder.cancel();
        pending.resolve(stream(audio));
        assert.equal(await start, false);
        assert.equal(audio.stopped, true);
        assert.equal(sent, false);
    } finally {
        Object.defineProperty(globalThis, 'navigator', { value: previousNavigator, configurable: true });
        globalThis.MediaRecorder = previousRecorder;
    }
});

test('CallState ignores events from another call or conversation', () => {
    const state = new CallState();
    const call = state.begin({ call_id: 'abcdefghijklmnop', conversation_id: 2 }, 'ringing');
    assert.equal(state.matches({ call_id: 'abcdefghijklmnop', conversation_id: 3 }), false);
    assert.equal(state.matches({ call_id: 'other-call-123456', conversation_id: 2 }), false);
    state.end();
    assert.equal(state.isCurrent(call), false);
});

test('late microphone permission after cancellation stops tracks instead of reopening a call', async () => {
    const pending = deferred();
    const audio = track();
    const manager = new CallManager({ ui: fakeUI() }, { mediaDevices: { getUserMedia: () => pending.promise } });
    const call = manager.beginCall({ call_id: 'abcdefghijklmnop', conversation_id: 2 }, 'preparing');
    const result = manager.getMedia(false, call);
    manager.endCall(true);
    pending.resolve(stream(audio));
    assert.equal(await result, false);
    assert.equal(audio.stopped, true);
    assert.equal(manager.localStream, null);
});

test('ICE waits for matching remote description and stale call ICE is ignored', async () => {
    const added = [];
    const manager = new CallManager({ ui: fakeUI() });
    const call = manager.beginCall({ call_id: 'abcdefghijklmnop', conversation_id: 2 }, 'ringing');
    manager.peerConnection = { remoteDescription: null, addIceCandidate: async candidate => added.push(candidate) };
    await manager.handleIceCandidate({ call_id: call.call_id, conversation_id: 2, candidate: { candidate: 'candidate:valid' } });
    assert.equal(added.length, 0);
    manager.peerConnection.remoteDescription = { type: 'answer' };
    call.remoteDescriptionReady = true;
    await manager.processQueuedCandidates(call);
    assert.equal(added.length, 1);
    await manager.handleIceCandidate({ call_id: 'wrong-call-123456', conversation_id: 2, candidate: { candidate: 'candidate:wrong' } });
    assert.equal(added.length, 1);
});

test('call teardown closes peer, clears media and cannot resurrect on stale end event', () => {
    let closed = 0;
    const audio = track();
    const manager = new CallManager({ ui: fakeUI(), socket: { emit() {} } });
    const call = manager.beginCall({ call_id: 'abcdefghijklmnop', conversation_id: 2 }, 'active');
    manager.peerConnection = { close() { ++closed; } };
    manager.localStream = stream(audio);
    manager.elements = { overlay: { classList: fakeClassList() }, btnShare: { classList: fakeClassList() } };
    manager.endCall(true);
    manager.handleCallEnded({ call_id: call.call_id, conversation_id: 2 });
    assert.equal(closed, 1);
    assert.equal(audio.stopped, true);
    assert.equal(manager.currentCall, null);
});
