import test from 'node:test';
import assert from 'node:assert/strict';
import { MeshCallManager } from '../../app/static/js/chat/call/MeshCallManager.js';

const CALL_ID = 'mesh_call_test_0001';
const OTHER_CALL_ID = 'mesh_call_test_0002';
const deferred = () => {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
};
class FakeTarget {
    listeners = new Map();
    addEventListener(type, fn) { const list = this.listeners.get(type) || new Set(); list.add(fn); this.listeners.set(type, list); }
    removeEventListener(type, fn) { this.listeners.get(type)?.delete(fn); }
    dispatch(type, extra = {}) {
        const event = { key: '', keyCode: 0, defaultPrevented: false, target: this,
            preventDefault() { this.defaultPrevented = true; }, ...extra };
        for (const fn of [...(this.listeners.get(type) || [])]) fn(event);
        return event;
    }
    listenerCount() { return [...this.listeners.values()].reduce((sum, list) => sum + list.size, 0); }
}
class FakeTrack extends FakeTarget {
    constructor(kind, id) { super(); Object.assign(this, { kind, id, enabled: true, muted: false, readyState: 'live', stopped: false }); }
    stop() { this.stopped = true; this.readyState = 'ended'; }
}
class FakeStream {
    constructor(...tracks) { this.tracks = tracks; }
    getTracks() { return [...this.tracks]; }
    getAudioTracks() { return this.tracks.filter(track => track.kind === 'audio'); }
    getVideoTracks() { return this.tracks.filter(track => track.kind === 'video'); }
    addTrack(track) { if (!this.tracks.includes(track)) this.tracks.push(track); }
}
class FakePeer {
    constructor(config) {
        Object.assign(this, { config, connectionState: 'new', signalingState: 'stable', senders: [], ice: [], log: [], offers: 0, answers: 0 });
    }
    addTrack(track, stream) {
        const sender = { track, stream, replacements: [], replaceTrack: async next => { sender.replacements.push(next); sender.track = next; this.log.push(`replace:${next?.id || 'null'}`); } };
        this.senders.push(sender);
        return sender;
    }
    addTransceiver(kind) { const sender = this.addTrack(null, null); sender.kind = kind; return { sender }; }
    async createOffer() { ++this.offers; this.log.push('offer'); return { type: 'offer', sdp: `offline-offer-${this.offers}` }; }
    async createAnswer() { ++this.answers; this.log.push('answer'); return { type: 'answer', sdp: `offline-answer-${this.answers}` }; }
    async setLocalDescription(description) {
        this.localDescription = description;
        this.signalingState = description.type === 'offer' ? 'have-local-offer' : 'stable';
        this.log.push(`local:${description.type}`);
    }
    async setRemoteDescription(description) {
        this.remoteDescription = description;
        this.signalingState = description.type === 'offer' ? 'have-remote-offer' : 'stable';
        this.log.push(`remote:${description.type}`);
    }
    async addIceCandidate(candidate) { assert.ok(this.remoteDescription, 'ICE waits for the remote SDP'); this.ice.push(candidate); this.log.push(`ice:${candidate.candidate}`); }
    close() { this.closed = true; this.connectionState = 'closed'; }
    connect() { this.connectionState = 'connected'; this.onconnectionstatechange?.(); }
    emitTrack(...tracks) { this.ontrack?.({ track: tracks[0], streams: [new FakeStream(...tracks)] }); }
}
class FakeElement extends FakeTarget {
    constructor(tag, document) {
        super(); Object.assign(this, { tagName: tag.toUpperCase(), document, children: [], attributes: new Map(), dataset: {}, hidden: false,
            disabled: false, className: '', textContent: '', value: '', srcObject: null, muted: false, open: false,
            playCalls: 0, pauseCalls: 0 });
    }
    appendChild(child) { child.remove(); child.parent = this; this.children.push(child); return child; }
    append(...children) { for (const child of children) this.appendChild(child); }
    remove() { if (this.parent) { this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; } }
    replaceChildren(...children) { for (const child of [...this.children]) child.remove(); this.append(...children); }
    get isConnected() { return this === this.document.body || !!this.parent?.isConnected; }
    setAttribute(key, value) { this.attributes.set(key, String(value)); if (key === 'open') this.open = true; }
    getAttribute(key) { return this.attributes.get(key) ?? null; }
    removeAttribute(key) { this.attributes.delete(key); if (key === 'open') this.open = false; }
    matches(selector) {
        if (selector === '[hidden]') return this.hidden;
        if (selector.startsWith('#')) return this.id === selector.slice(1);
        if (selector.startsWith('.')) return this.className.split(/\s+/).includes(selector.slice(1));
        return this.tagName.toLowerCase() === selector;
    }
    closest(selector) { for (let node = this; node; node = node.parent) if (node.matches(selector)) return node; return null; }
    querySelectorAll(selector) {
        const matches = selector.split(',').map(part => part.trim());
        return this.children.flatMap(child => [...(matches.some(part => child.matches(part)) ? [child] : []), ...child.querySelectorAll(selector)]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    focus() { if (!this.disabled) this.document.activeElement = this; }
    showModal() { this.open = true; }
    close() { this.open = false; this.dispatch('close'); }
    play() { ++this.playCalls; return this.playReject ? Promise.reject(new Error('Gesture required')) : Promise.resolve(); }
    pause() { ++this.pauseCalls; }
}
class FakeDocument {
    constructor() { this.body = new FakeElement('body', this); this.activeElement = this.body; }
    createElement(tag) { return new FakeElement(tag, this); }
    getElementById(id) { return this.body.querySelector(`#${id}`); }
}
function wireDOM() {
    const document = new FakeDocument();
    const element = (tag, id, parent = document.body) => { const node = document.createElement(tag); node.id = id; parent.appendChild(node); return node; };
    const button = (id, parent) => { const node = element('button', id, parent); const label = element('span', '', node); label.className = 'mesh-call-control-label'; return node; };
    const trigger = button('meshTrigger', document.body);
    trigger.focus();
    const overlay = element('dialog', 'meshCallOverlay');
    element('h2', 'meshCallTitle', overlay);
    element('p', 'meshCallStatus', overlay);
    element('p', 'meshCallFeedback', overlay);
    button('meshCallEnd', overlay);
    const invite = element('div', 'meshCallInviteActions', overlay);
    button('meshCallReject', invite);
    button('meshCallAccept', invite);
    element('div', 'meshCallGrid', overlay);
    const panel = element('section', 'meshCallChatPanel', overlay);
    panel.hidden = true;
    button('meshCallChatClose', panel);
    element('div', 'meshCallChatList', panel);
    element('textarea', 'meshCallChatInput', panel);
    button('meshCallChatSend', panel);
    for (const id of ['meshCallMic', 'meshCallCamera', 'meshCallShare', 'meshCallChatToggle', 'meshCallPlayAudio']) button(id, overlay);
    element('div', 'meshCallAudioSinks', overlay);
    return { document, trigger, overlay };
}
function room({ callId = CALL_ID, revision = 1, ownId = 1, ids = [1, 2, 3, 4], joined = ids, pairRevision = 1, status = 'active', isVideo = true } = {}) {
    const participants = ids.map(id => ({ user_id: id, name: `Thành viên ${id}`, status: joined.includes(id) ? 'joined' : 'invited',
        mic_enabled: true, cam_enabled: isVideo, is_sharing: false, media_revision: 0, stream_revision: 0 }));
    const pairs = [];
    for (let a = 0; a < joined.length; ++a) for (let b = a + 1; b < joined.length; ++b) {
        const userIds = [joined[a], joined[b]].sort((x, y) => x - y);
        pairs.push({ pair_id: `pair_${userIds.join('_')}`, peer_revision: pairRevision, offerer_user_id: userIds[0], user_ids: userIds });
    }
    assert.ok(ids.includes(ownId));
    return { call_id: callId, conversation_id: 7, revision, isVideo, status, participants, pairs };
}
function signal(sender, type, payload, { ownId = 1, callId = CALL_ID, pairRevision = 1 } = {}) {
    return { call_id: callId, conversation_id: 7, sender_id: sender, target_user_id: ownId,
        pair_id: `pair_${[sender, ownId].sort((a, b) => a - b).join('_')}`, peer_revision: pairRevision, type, payload };
}
function fixture(options = {}) {
    const peers = [];
    const requests = [];
    const emitted = [];
    const toasts = [];
    const timers = new Map();
    let timerId = 0;
    let captures = 0;
    let displays = 0;
    const ownId = options.ownId || 1;
    const ids = options.ids || [1, 2, 3, 4];
    const local = new FakeStream(new FakeTrack('audio', 'local_mic'), ...(options.video === false ? [] : [new FakeTrack('video', 'local_cam')]));
    const screen = new FakeStream(new FakeTrack('video', 'screen_track'));
    const dom = options.dom ? wireDOM() : { document: undefined };
    if (dom.document) globalThis.document = dom.document;
    const app = { userId: ownId, userName: 'Bạn', currentConversationId: 7, currentConversationType: 'group', selectionRevision: 1,
        participants: ids.map(id => ({ id, name: `Thành viên ${id}` })), rtcIceServers: [{ urls: 'stun:offline.example.invalid' }],
        callManager: { currentCall: null }, ui: { showToast: text => toasts.push(text), formatTime: () => '12:00' } };
    app.socket = {
        connected: true,
        emit: (event, data) => { emitted.push({ event, data }); return true; },
        request: async (event, data) => {
            requests.push({ event, data });
            if (options.request) return options.request(event, data);
            return { success: true, call_id: data.call_id, conversation_id: data.conversation_id,
                ...(['group_call_start', 'group_call_join'].includes(event) ? { state: room({ ownId, ids, isVideo: options.video !== false }) } : {}) };
        }
    };
    const manager = new MeshCallManager(app, {
        document: dom.document, newCallId: () => CALL_ID, makeStream: () => new FakeStream(),
        makePeer: config => { const peer = new FakePeer(config); peers.push(peer); return peer; },
        mediaDevices: { getUserMedia: async () => { ++captures; return options.capture ? options.capture.promise : local; },
            getDisplayMedia: async () => { ++displays; return options.display ? options.display.promise : screen; } },
        setTimer: (fn, milliseconds) => { const id = ++timerId; timers.set(id, { fn, milliseconds }); return id; },
        clearTimer: id => timers.delete(id), now: () => 1234, ...options.dependencies
    });
    if (dom.document) manager.initUI();
    return { app, manager, peers, requests, emitted, toasts, timers, local, screen, ...dom,
        get captures() { return captures; }, get displays() { return displays; } };
}
async function idle(manager) {
    for (let i = 0; i < 5; ++i) { await Promise.all([...manager.remotePeers.values()].map(peer => peer.queue)); await Promise.resolve(); }
}
async function start(f) { assert.equal(await f.manager.startCall(f.local.getVideoTracks().length > 0), true); await idle(f.manager); }
async function answerAll(f) {
    for (const peer of f.manager.remotePeers.values()) await f.manager.handleSignal(signal(peer.userId, 'answer', { type: 'answer', sdp: `answer-${peer.userId}` }, { ownId: f.app.userId }));
    await idle(f.manager);
}

// All fixtures below are local lifecycle mocks. They do not establish browser, NAT or TURN reachability.
test('offerer waits for the SDP answer before flushing local ICE', async () => {
    const f = fixture();
    try {
        await start(f);
        const peer = f.manager.remotePeers.get(2);
        peer.localIce.push({ candidate: 'queued-local-ice', sdpMid: '0', sdpMLineIndex: 0 });
        f.manager.flushLocalIce(f.manager.currentCall, peer);
        await idle(f.manager);
        assert.equal(f.requests.filter(item => item.event === 'group_call_signal' && item.data.type === 'ice').length, 0);
        assert.equal(await f.manager.handleSignal(signal(2, 'answer', { type: 'answer', sdp: 'answer-2' })), true);
        await idle(f.manager);
        assert.equal(peer.awaitingAnswer, false);
        assert.equal(f.requests.filter(item => item.event === 'group_call_signal' && item.data.type === 'ice').length, 1);
    } finally { await f.manager.dispose(); }
});

test('outbound ICE ACK cannot block applying an inbound candidate on the same peer', async () => {
    const iceAck = deferred();
    const f = fixture({ request: (event, data) => {
        if (event === 'group_call_signal' && data.type === 'ice') return iceAck.promise;
        return { success: true, call_id: data.call_id, conversation_id: data.conversation_id,
            ...(event === 'group_call_start' ? { state: room() } : {}) };
    } });
    try {
        await start(f);
        const peer = f.manager.remotePeers.get(2);
        peer.localIce.push({ candidate: 'outbound-awaiting-ack', sdpMid: '0', sdpMLineIndex: 0 });
        assert.equal(await f.manager.handleSignal(signal(2, 'answer', { type: 'answer', sdp: 'answer-2' })), true);
        assert.equal(f.requests.filter(item => item.event === 'group_call_signal' && item.data.type === 'ice').length, 1);

        const inbound = f.manager.handleSignal(signal(2, 'ice', { candidate: 'inbound-while-ack-pending', sdpMid: '0', sdpMLineIndex: 0 }));
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(peer.pc.ice.map(candidate => candidate.candidate), ['inbound-while-ack-pending']);
        assert.equal(await inbound, true);
    } finally {
        iceAck.resolve({ success: true, call_id: CALL_ID, conversation_id: 7 });
        await f.manager.dispose();
    }
});

test('captures once for three authorized peer edges, signals exact scoped offers, never invents connected state from ACK', async () => {
    const f = fixture();
    try {
        await start(f);
        assert.equal(f.captures, 1);
        assert.equal(f.peers.length, 3);
        assert.equal(f.manager.remotePeers.size, 3);
        assert.equal(f.manager.isBusy, true);
        assert.equal(f.manager.isCallActive, false);
        assert.equal(f.manager.currentCall.phase, 'connecting');
        assert.deepEqual(f.requests[0], { event: 'group_call_start', data: { call_id: CALL_ID, conversation_id: 7,
            request_id: CALL_ID, invite_user_ids: [2, 3, 4], isVideo: true } });
        const offers = f.requests.filter(item => item.event === 'group_call_signal' && item.data.type === 'offer');
        assert.equal(offers.length, 3);
        for (const { data } of offers) {
            assert.equal(data.call_id, CALL_ID);
            assert.equal(data.conversation_id, 7);
            assert.equal(data.pair_id, `pair_1_${data.target_user_id}`);
            assert.equal(data.peer_revision, 1);
            assert.deepEqual(Object.keys(data).sort(), ['call_id', 'conversation_id', 'pair_id', 'payload', 'peer_revision', 'target_user_id', 'type']);
        }
        for (const pc of f.peers) {
            assert.deepEqual(pc.config, { iceServers: f.app.rtcIceServers });
            assert.equal(pc.senders[0].track, f.local.getAudioTracks()[0]);
            assert.equal(pc.senders[1].track, f.local.getVideoTracks()[0]);
        }
        await answerAll(f);
        assert.equal(f.manager.isCallActive, false);
        f.peers[0].connect();
        assert.equal(f.manager.isCallActive, true);
        f.peers[0].connectionState = 'disconnected';
        f.peers[0].onconnectionstatechange();
        assert.equal(f.manager.isCallActive, false);
        assert.ok([...f.timers.values()].some(timer => timer.milliseconds === 10000));
    } finally { await f.manager.dispose(); }
});

test('cap is small groups only; rejects five members, private scope, duplicates and direct incumbent without capturing', async () => {
    for (const configure of [
        f => { f.app.participants.push({ id: 5 }); },
        f => { f.app.currentConversationType = 'private'; },
        f => { f.app.participants[3].id = 2; },
        f => { f.app.callManager.currentCall = { call_id: 'direct' }; }
    ]) {
        const f = fixture();
        configure(f);
        assert.equal(await f.manager.startCall(), false);
        assert.equal(f.captures, 0);
        assert.equal(f.requests.length, 0);
        assert.equal(f.manager.currentCall, null);
        await f.manager.dispose();
    }
});

test('rejected start or join ACK cannot mark accepted or create peers, and captures are released', async () => {
    const f = fixture({ request: (event, data) => ({ success: event === 'group_call_leave', call_id: data.call_id }) });
    assert.equal(await f.manager.startCall(), false);
    assert.equal(f.captures, 0);
    assert.equal(f.peers.length, 0);
    assert.equal(f.manager.currentCall, null);
    const join = fixture({ ownId: 4, request: (event, data) => ({ success: event === 'group_call_leave', call_id: data.call_id }) });
    assert.equal(join.manager.handleInvited({ call_id: CALL_ID, conversation_id: 7, invite_id: 'invite_4', sender_id: 1, isVideo: true }), true);
    assert.equal(await join.manager.acceptCall(), false);
    assert.equal(join.captures, 1);
    assert.ok(join.local.getTracks().every(track => track.stopped));
    assert.equal(join.peers.length, 0);
    await Promise.all([f.manager.dispose(), join.manager.dispose()]);
});

test('invite waits for explicit acceptance; accepts once and answers all incumbents instead of offering', async () => {
    const f = fixture({ ownId: 4 });
    try {
        const invited = { call_id: CALL_ID, conversation_id: 7, invite_id: 'invite_4', sender_id: 1, sender_name: 'Người gọi', isVideo: true };
        assert.equal(f.manager.handleInvited(invited), true);
        assert.equal(f.manager.handleInvited(invited), false);
        assert.equal(f.captures, 0);
        const first = f.manager.acceptCall();
        assert.equal(await f.manager.acceptCall(), false);
        assert.equal(await first, true);
        await idle(f.manager);
        assert.equal(f.peers.length, 3);
        assert.equal(f.peers.reduce((sum, pc) => sum + pc.offers, 0), 0);
        assert.deepEqual(f.requests.find(item => item.event === 'group_call_join').data,
            { call_id: CALL_ID, conversation_id: 7, invite_id: 'invite_4' });
        for (const id of [1, 2, 3]) {
            await f.manager.handleSignal(signal(id, 'ice', { candidate: `ice-${id}` }, { ownId: 4 }));
            assert.equal(f.manager.remotePeers.get(id).pc.ice.length, 0);
            await f.manager.handleSignal(signal(id, 'offer', { type: 'offer', sdp: `offer-${id}` }, { ownId: 4 }));
        }
        await idle(f.manager);
        assert.equal(f.requests.filter(item => item.event === 'group_call_signal' && item.data.type === 'answer').length, 3);
        assert.ok(f.peers.every(pc => pc.answers === 1 && pc.ice.length === 1));
        assert.equal(f.manager.isCallActive, false);
    } finally { await f.manager.dispose(); }
});

test('signals and ICE before invite/state stay bounded and cannot authorize PCs; matching state drains each edge', async () => {
    const f = fixture({ ownId: 4 });
    try {
        for (let index = 0; index < 180; ++index) await f.manager.handleSignal(signal(1, 'ice', { candidate: `early-${index}` }, { ownId: 4 }));
        assert.equal(f.manager.earlySignals.get(`7:${CALL_ID}`).values().next().value.length, 128);
        assert.equal(f.peers.length, 0);
        assert.equal(f.captures, 0);
        await f.manager.handleSignal(signal(2, 'offer', { type: 'offer', sdp: 'early-offer-2' }, { ownId: 4 }));
        await f.manager.handleState(room({ ownId: 4, joined: [1, 2, 3], status: 'waiting' }));
        f.manager.handleInvited({ call_id: CALL_ID, conversation_id: 7, invite_id: 'invite_4', sender_id: 1, isVideo: true });
        assert.equal(f.captures, 0);
        assert.equal(f.peers.length, 0);
        assert.equal(await f.manager.acceptCall(), true);
        await f.manager.handleState(room({ ownId: 4, revision: 2 }));
        await idle(f.manager);
        assert.equal(f.manager.remotePeers.get(2).pc.answers, 1);
        assert.equal(f.manager.remotePeers.get(1).queuedIce.length, 128);
        await f.manager.handleSignal(signal(1, 'offer', { type: 'offer', sdp: 'early-offer-1' }, { ownId: 4 }));
        assert.equal(f.manager.remotePeers.get(1).pc.ice.length, 128);
        await f.manager.handleSignal(signal(1, 'ice', { candidate: 'early-0' }, { ownId: 4 }));
        assert.equal(f.manager.remotePeers.get(1).pc.ice.length, 128);
    } finally { await f.manager.dispose(); }
});

test('room revisions, accepted pairs and directed signal revisions isolate each peer and retire old generations', async () => {
    const f = fixture();
    try {
        await start(f);
        const previous = f.manager.remotePeers.get(2);
        assert.equal(await f.manager.handleState(room({ revision: 1, joined: [1] })), false);
        assert.equal(f.manager.remotePeers.size, 3);
        assert.equal(await f.manager.handleSignal({ ...signal(2, 'answer', { type: 'answer', sdp: 'wrong-target' }), target_user_id: 9 }), false);
        assert.equal(await f.manager.handleSignal(signal(2, 'answer', { type: 'answer', sdp: 'wrong-call' }, { callId: OTHER_CALL_ID })), false);
        await f.manager.handleState(room({ revision: 2, joined: [1, 3, 4] }));
        assert.equal(previous.pc.closed, true);
        assert.equal(f.manager.remotePeers.size, 2);
        await f.manager.handleState(room({ revision: 3, pairRevision: 2 }));
        await idle(f.manager);
        const replacement = f.manager.remotePeers.get(2);
        assert.notEqual(replacement, previous);
        assert.equal(f.manager.remotePeers.size, 3);
        assert.equal(await f.manager.handleSignal(signal(2, 'answer', { type: 'answer', sdp: 'retired' })), false);
        assert.equal(replacement.pc.remoteDescription, undefined);
        assert.equal(await f.manager.handleSignal(signal(2, 'answer', { type: 'answer', sdp: 'current' }, { pairRevision: 2 })), true);
        assert.equal(replacement.pc.remoteDescription.sdp, 'current');
        const unauthorized = room({ revision: 4 });
        unauthorized.pairs[0].user_ids = [1, 999];
        assert.equal(await f.manager.handleState(unauthorized), false);
        assert.equal(f.manager.currentCall.revision, 3);
    } finally { await f.manager.dispose(); }
});

test('end, socket loss, timeout and conversation switch stop every late permission track and never revive a call', async () => {
    for (const mode of ['end', 'disconnect', 'timeout', 'switch', 'dispose']) {
        const capture = deferred();
        const f = fixture({ capture });
        const starting = f.manager.startCall();
        await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
        if (mode === 'end') await f.manager.endCall();
        if (mode === 'disconnect') { f.app.socket.connected = false; await f.manager.handleSocketDisconnected(); }
        if (mode === 'timeout') [...f.timers.values()].find(timer => timer.milliseconds === 30000).fn();
        if (mode === 'switch') { f.app.currentConversationId = 8; ++f.app.selectionRevision; }
        if (mode === 'dispose') await f.manager.dispose();
        capture.resolve(f.local);
        assert.equal(await starting, false, mode);
        assert.equal(f.manager.currentCall, null, mode);
        assert.ok(f.local.getTracks().every(track => track.stopped), mode);
        assert.equal(f.peers.length, 0, mode);
        await f.manager.dispose();
    }
});

test('pending offer work cannot send after leave or overwrite the next generation', async () => {
    const f = fixture();
    const offer = deferred();
    f.manager.makePeer = config => { const pc = new FakePeer(config); pc.createOffer = () => offer.promise; f.peers.push(pc); return pc; };
    assert.equal(await f.manager.startCall(), true);
    await f.manager.endCall();
    offer.resolve({ type: 'offer', sdp: 'late-offer' });
    await idle(f.manager);
    assert.equal(f.requests.some(item => item.event === 'group_call_signal'), false);
    assert.ok(f.peers.every(pc => pc.closed));
    await f.manager.dispose();
});

test('one remote failure does not end other peers; per-peer tracks are deduplicated and audio is independent', async () => {
    const f = fixture({ dom: true });
    try {
        await start(f);
        await answerAll(f);
        for (const [id, peer] of f.manager.remotePeers) {
            peer.pc.connect();
            const audio = new FakeTrack('audio', `remote-audio-${id}`);
            const video = new FakeTrack('video', `remote-video-${id}`);
            peer.pc.emitTrack(audio, video);
            peer.pc.emitTrack(audio, video);
            assert.equal(peer.remoteStream.getTracks().length, 2);
            assert.equal(peer.audioStream.getTracks().length, 1);
            assert.equal(peer.videoStream.getTracks().length, 1);
            assert.equal(peer.audio.muted, false);
            assert.equal(peer.audio.srcObject, peer.audioStream);
            const tile = f.manager.tiles.get(id);
            assert.equal(tile.video.muted, true);
            assert.equal(tile.video.srcObject, peer.videoStream);
            assert.equal(tile.placeholder.hidden, true);
        }
        assert.equal(f.manager.elements.audioSinks.children.length, 3);
        const failed = f.manager.remotePeers.get(2);
        failed.pc.connectionState = 'failed'; failed.pc.onconnectionstatechange();
        assert.ok(failed.remoteStream.getTracks().every(track => track.stopped));
        assert.equal(failed.pc.closed, true);
        assert.equal(f.manager.isCallActive, true);
        assert.equal(f.manager.currentCall.call_id, CALL_ID);
        assert.equal(f.manager.elements.audioSinks.children.length, 2);
        assert.match(f.manager.elements.feedback.textContent, /Các thành viên khác/);
    } finally { await f.manager.dispose(); }
});

test('screen sender replacements serialize across all peers, preserve SDP, and late join sends current shared track', async () => {
    const f = fixture({ request: (event, data) => ({ success: true, call_id: data.call_id,
        ...(event === 'group_call_start' ? { state: room({ joined: [1, 2, 3], status: 'active' }) } : {}) }) });
    try {
        await start(f);
        assert.equal(f.peers.length, 2);
        const offersBefore = f.peers.reduce((sum, pc) => sum + pc.offers, 0);
        const sharing = f.manager.startScreenShare();
        const stopping = f.manager.stopScreenShare();
        assert.equal(await sharing, true);
        assert.equal(await stopping, true);
        for (const peer of f.manager.remotePeers.values()) {
            assert.deepEqual(peer.videoSender.replacements, [f.screen.getVideoTracks()[0], f.local.getVideoTracks()[0]]);
        }
        assert.equal(f.displays, 1);
        assert.equal(f.peers.reduce((sum, pc) => sum + pc.offers, 0), offersBefore);
        assert.equal(f.manager.isSharingScreen, false);
        assert.ok(f.screen.getTracks().every(track => track.stopped));
        const nextScreen = new FakeStream(new FakeTrack('video', 'screen-2'));
        f.manager.mediaDevices.getDisplayMedia = async () => nextScreen;
        assert.equal(await f.manager.startScreenShare(), true);
        await f.manager.handleState(room({ revision: 2 }));
        await idle(f.manager);
        const latePeer = f.manager.remotePeers.get(4);
        assert.equal(latePeer.videoSender.track, nextScreen.getVideoTracks()[0]);
        assert.equal(latePeer.audioSender.track, f.local.getAudioTracks()[0]);
        await f.manager.stopScreenShare();
        assert.equal(latePeer.videoSender.track, f.local.getVideoTracks()[0]);
        assert.equal(latePeer.pc.offers, 1);
        assert.deepEqual(f.emitted.filter(item => item.event === 'stream_status').map(item => item.data.is_streaming), [true, false, true, false]);
    } finally { await f.manager.dispose(); }
});

test('voice calls reserve a video transceiver for screen share without reacquiring camera or renegotiating', async () => {
    const f = fixture({ video: false });
    try {
        await start(f);
        const peers = [...f.manager.remotePeers.values()];
        assert.ok(peers.every(peer => peer.videoSender.track === null));
        assert.equal(await f.manager.startScreenShare(), true);
        assert.equal(await f.manager.stopScreenShare(), true);
        assert.ok(peers.every(peer => peer.videoSender.track === null && peer.pc.offers === 1));
        assert.equal(f.captures, 1);
        assert.equal(f.manager.toggleCamera(), false);
    } finally { await f.manager.dispose(); }
});

test('cancelled late screen capture releases every display track and does not publish sharing', async () => {
    const display = deferred();
    const f = fixture({ display });
    await start(f);
    const sharing = f.manager.startScreenShare();
    await Promise.resolve();
    await f.manager.endCall();
    display.resolve(f.screen);
    assert.equal(await sharing, false);
    assert.ok(f.screen.getTracks().every(track => track.stopped));
    assert.equal(f.emitted.some(item => item.event === 'stream_status'), false);
    await f.manager.dispose();
});

test('media and share status are participant-scoped, revisioned and reflected in voice/camera placeholders', async () => {
    const f = fixture({ dom: true });
    try {
        await start(f);
        const peer = f.manager.remotePeers.get(2);
        peer.pc.connect();
        peer.pc.emitTrack(new FakeTrack('video', 'remote_video'));
        assert.equal(f.manager.handleMediaStatus({ call_id: CALL_ID, conversation_id: 7, sender_id: 2, type: 'cam', enabled: false, revision: 2 }), true);
        assert.equal(f.manager.tiles.get(2).placeholder.hidden, false);
        assert.equal(f.manager.handleMediaStatus({ call_id: CALL_ID, conversation_id: 7, sender_id: 2, type: 'cam', enabled: true, revision: 1 }), false);
        assert.equal(f.manager.handleMediaStatus({ call_id: CALL_ID, conversation_id: 7, sender_id: 99, type: 'mic', enabled: false, revision: 3 }), false);
        assert.equal(f.manager.handleStreamStatus({ call_id: CALL_ID, conversation_id: 7, sender_id: 2, is_streaming: true, revision: 1 }), true);
        assert.equal(f.manager.tiles.get(2).placeholder.hidden, true);
        assert.equal(f.manager.handleStreamStatus({ call_id: CALL_ID, conversation_id: 7, sender_id: 2, is_streaming: false, revision: 1 }), false);
        assert.equal(f.manager.mediaFor(f.manager.currentCall, 3).cam, true);
        f.manager.toggleMic();
        assert.equal(f.local.getAudioTracks()[0].enabled, false);
        assert.equal(f.manager.elements.mic.getAttribute('aria-label'), 'Bật micro');
        f.manager.toggleCamera();
        assert.equal(f.local.getVideoTracks()[0].enabled, false);
        assert.equal(f.manager.elements.camera.getAttribute('aria-label'), 'Bật camera');
        assert.ok(f.emitted.filter(item => item.event === 'media_status').every(item => item.data.call_id === CALL_ID && item.data.conversation_id === 7));
    } finally { await f.manager.dispose(); }
});

test('chat awaits actual success, handles IME/modifiers, scopes sender identity and renders text safely', async () => {
    const chatAck = deferred();
    const f = fixture({ dom: true, request: (event, data) => event === 'call_chat_message' ? chatAck.promise :
        { success: true, call_id: data.call_id, ...(event === 'group_call_start' ? { state: room() } : {}) } });
    try {
        await start(f);
        const input = f.manager.elements.chatInput;
        input.value = '<img src=x onerror=alert(1)>';
        const sending = f.manager.sendCallChatMessage();
        assert.equal(f.manager.currentCall.chatMessages.length, 0);
        assert.equal(await f.manager.sendCallChatMessage(), false);
        chatAck.resolve({ success: false, call_id: CALL_ID });
        assert.equal(await sending, false);
        assert.equal(f.manager.currentCall.chatMessages.length, 0);
        assert.ok(input.value);
        for (const extra of [{ isComposing: true }, { keyCode: 229 }, { shiftKey: true }, { ctrlKey: true }, { metaKey: true }, { altKey: true }, { repeat: true }]) {
            assert.equal(input.dispatch('keydown', { key: 'Enter', ...extra }).defaultPrevented, false);
        }
        assert.equal(f.manager.handleCallChatMessage({ call_id: OTHER_CALL_ID, conversation_id: 7, sender_id: 2, text: 'wrong' }), false);
        assert.equal(f.manager.handleCallChatMessage({ call_id: CALL_ID, conversation_id: 7, sender_id: 99, text: 'unauthorized' }), false);
        const message = { call_id: CALL_ID, conversation_id: 7, sender_id: 2, sender_name: '<script>fake-name</script>', text: input.value, timestamp: 10 };
        assert.equal(f.manager.handleCallChatMessage(message), true);
        assert.equal(f.manager.handleCallChatMessage(message), false);
        const row = f.manager.elements.chatList.children[0];
        assert.equal(row.children[0].textContent, 'Thành viên 2');
        assert.equal(row.children[1].textContent, '<img src=x onerror=alert(1)>');
        assert.equal(row.querySelectorAll('img').length, 0);
        assert.equal(row.querySelectorAll('script').length, 0);
    } finally { await f.manager.dispose(); }
});

test('native isolated modal has named controls, focus trap/return and UI teardown removes listeners and streams', async () => {
    const f = fixture({ dom: true });
    await start(f);
    assert.equal(f.overlay.open, true);
    assert.equal(f.overlay.getAttribute('aria-hidden'), 'false');
    assert.equal(f.manager.elements.mic.getAttribute('aria-label'), 'Tắt micro');
    assert.equal(f.manager.elements.camera.getAttribute('aria-label'), 'Tắt camera');
    f.manager.toggleChat(true);
    assert.equal(f.manager.elements.chatPanel.hidden, false);
    assert.equal(f.manager.elements.chatToggle.getAttribute('aria-expanded'), 'true');
    f.manager.toggleChat(false);
    const visible = f.overlay.querySelectorAll('button, textarea').filter(node => !node.disabled && !node.hidden && !node.closest('[hidden]'));
    visible.at(-1).focus();
    assert.equal(f.overlay.dispatch('keydown', { key: 'Tab' }).defaultPrevented, true);
    assert.equal(f.document.activeElement, visible[0]);
    const elements = [f.overlay, ...f.overlay.querySelectorAll('button, textarea')];
    await f.manager.dispose();
    assert.equal(f.overlay.open, false);
    assert.equal(f.document.activeElement, f.trigger);
    assert.equal(f.manager.currentCall, null);
    assert.equal(f.manager.remotePeers.size, 0);
    assert.equal(f.manager.tiles.size, 0);
    assert.equal(f.timers.size, 0);
    assert.ok(elements.every(node => node.listenerCount() === 0));
    assert.ok(f.local.getTracks().every(track => track.stopped));
});

test('leaving is acknowledged, not optimistic, and pending leave keeps exclusive gate busy', async () => {
    const leave = deferred();
    const f = fixture({ request: (event, data) => event === 'group_call_leave' ? leave.promise :
        { success: true, call_id: data.call_id, ...(event === 'group_call_start' ? { state: room() } : {}) } });
    await start(f);
    const ending = f.manager.endCall();
    assert.equal(f.manager.currentCall, null);
    assert.equal(f.manager.isBusy, true);
    assert.equal(await f.manager.startCall(), false);
    leave.resolve({ success: false, call_id: CALL_ID });
    assert.equal(await ending, false);
    assert.equal(f.manager.isBusy, false);
    assert.ok(f.toasts.some(text => text.includes('Chưa xác nhận rời cuộc gọi')));
    assert.ok(f.local.getTracks().every(track => track.stopped));
    await f.manager.dispose();
});

test('flat server ACK creates authorized peers and uses incumbent offerer, not user-id ordering', async () => {
    const f = fixture({ ownId: 4, request: (event, data) => {
        if (event !== 'group_call_start') return { success: true, call_id: data.call_id };
        const state = room({ ownId: 4 });
        for (const pair of state.pairs) if (pair.user_ids.includes(4)) pair.offerer_user_id = 4;
        return { success: true, ...state };
    } });
    try {
        await start(f);
        assert.equal(f.manager.currentCall.serverJoined, true);
        assert.equal(f.manager.remotePeers.size, 3);
        assert.equal(f.peers.reduce((count, pc) => count + pc.offers, 0), 3);
        assert.equal(f.emitted.filter(item => item.event === 'media_status').length, 2);
        assert.equal(f.manager.isCallActive, false);
    } finally { await f.manager.dispose(); }
});

test('per-kind snapshot revisions do not confuse stream and camera counters', async () => {
    const f = fixture();
    try {
        await start(f);
        const state = room({ revision: 2 });
        Object.assign(state.participants[1], { mic_enabled: false, cam_enabled: false, is_sharing: true,
            media_revision: 20, media_revisions: { mic: 20, cam: 2 } });
        delete state.participants[1].stream_revision;
        await f.manager.handleState(state);
        const media = f.manager.mediaFor(f.manager.currentCall, 2);
        assert.equal(media.revisions.mic, 20);
        assert.equal(media.revisions.cam, 2);
        assert.equal(media.revisions.stream, 0);
        assert.equal(f.manager.handleStreamStatus({ call_id: CALL_ID, conversation_id: 7, sender_id: 2, is_streaming: true, revision: 1 }), true);
        assert.equal(f.manager.handleMediaStatus({ call_id: CALL_ID, conversation_id: 7, sender_id: 2, type: 'cam', enabled: true, revision: 3 }), true);
        const next = room({ revision: 3 });
        Object.assign(next.participants[1], { is_sharing: false, stream_revision: 2, media_revision: 20,
            media_revisions: { mic: 20, cam: 3 } });
        await f.manager.handleState(next);
        assert.equal(media.sharing, false);
        assert.equal(media.revisions.stream, 2);
        assert.equal(f.manager.handleStreamStatus({ call_id: CALL_ID, conversation_id: 7, sender_id: 2, is_streaming: true, revision: 1 }), false);
    } finally { await f.manager.dispose(); }
});

test('retired peer revisions never return and a new socket generation cancels pending capture', async () => {
    const f = fixture();
    await start(f);
    await f.manager.handleState(room({ revision: 2, pairRevision: 2 }));
    await idle(f.manager);
    const current = f.manager.remotePeers.get(2);
    assert.equal(await f.manager.handleState(room({ revision: 3, pairRevision: 1 })), false);
    assert.equal(f.manager.remotePeers.get(2), current);
    await f.manager.dispose();
    const capture = deferred();
    const pending = fixture({ capture });
    const starting = pending.manager.startCall();
    for (let i = 0; i < 5; ++i) await Promise.resolve();
    pending.app.socket = { ...pending.app.socket };
    capture.resolve(pending.local);
    assert.equal(await starting, false);
    assert.equal(pending.manager.currentCall, null);
    assert.ok(pending.local.getTracks().every(track => track.stopped));
    await pending.manager.dispose();
});

test('server-ended state is terminal and future signals/invites cannot reopen its call', async () => {
    const f = fixture();
    await start(f);
    assert.equal(await f.manager.handleState(room({ revision: 2, status: 'ended' })), true);
    assert.equal(f.manager.currentCall, null);
    assert.equal(f.requests.some(item => item.event === 'group_call_leave'), false);
    assert.equal(await f.manager.handleSignal(signal(2, 'ice', { candidate: 'late' })), false);
    assert.equal(f.manager.handleInvited({ call_id: CALL_ID, conversation_id: 7, invite_id: 'late_invite', sender_id: 2 }), false);
    assert.equal(f.manager.earlySignals.size, 0);
    await f.manager.dispose();
});
