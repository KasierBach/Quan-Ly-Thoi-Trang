import CallState from './CallState.js';
import { createNode, shouldSendOnEnter } from '../utils/helpers.js';

const MAX_PEERS = 3;
const MAX_EARLY_CALLS = 4;
const MAX_QUEUED_SIGNALS = 128;
const MAX_CHAT_MESSAGES = 200;
const positiveId = value => /^\d+$/.test(String(value)) && Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : null;
const validRevision = value => Number.isSafeInteger(value) && value > 0;
const validPairId = value => typeof value === 'string' && /^[A-Za-z0-9_:-]{1,128}$/.test(value);
const stopStream = stream => stream?.getTracks().forEach(track => track.stop());
const liveTrack = track => track && track.readyState !== 'ended';

/** One server-authorized edge. Its SDP, ICE and sender changes share one queue. */
class PeerSession {
    constructor(userId, pair, pc, makeStream) {
        this.userId = userId;
        this.pair_id = pair.pair_id;
        this.peer_revision = pair.peer_revision;
        this.offerer_user_id = pair.offerer_user_id;
        this.pc = pc;
        this.remoteStream = makeStream();
        this.audioStream = makeStream();
        this.videoStream = makeStream();
        this.queuedIce = [];
        this.localIce = [];
        this.iceKeys = new Set();
        this.localIceKeys = new Set();
        this.queue = Promise.resolve();
        this.listeners = [];
        this.connected = false;
        this.closed = false;
        this.failed = false;
        this.descriptionReady = false;
        this.signalReady = false;
        this.awaitingAnswer = false;
        this.offerStarted = false;
        this.audioBlocked = false;
    }
}

/** Small, private group mesh. This class never owns or edits the direct-call UI. */
export class MeshCallManager {
    constructor(app, dependencies = {}) {
        this.app = app;
        this.state = new CallState();
        this.remotePeers = new Map();
        this.localStream = null;
        this.screenStream = null;
        this.isSharingScreen = false;
        this.isCallActive = false;
        this.disposed = false;
        this.earlySignals = new Map();
        this.earlyStates = new Map();
        this.terminalCalls = new Set();
        this.pendingLeaves = new Map();
        this.elements = {};
        this.tiles = new Map();
        this.uiListeners = [];
        this.mediaDevices = dependencies.mediaDevices ?? globalThis.navigator?.mediaDevices;
        this.makePeer = dependencies.makePeer ?? (config => new globalThis.RTCPeerConnection(config));
        this.makeStream = dependencies.makeStream ?? (() => new globalThis.MediaStream());
        this.newCallId = dependencies.newCallId ?? (() => globalThis.crypto.randomUUID());
        this.setTimer = dependencies.setTimer ?? ((...args) => globalThis.setTimeout(...args));
        this.clearTimer = dependencies.clearTimer ?? (timer => globalThis.clearTimeout(timer));
        this.now = dependencies.now ?? (() => Date.now());
        this.document = dependencies.document ?? globalThis.document;
        this.isDirectCallBusy = dependencies.isDirectCallBusy ?? (() => !!app.callManager?.currentCall);
        this.config = { iceServers: dependencies.iceServers ?? app.rtcIceServers ?? [] };
    }

    get socket() { return this.app.socket; }
    get currentCall() { return this.state.current; }
    get isBusy() { return !!this.currentCall || this.pendingLeaves.size > 0; }
    scope(call) { return { call_id: call.call_id, conversation_id: call.conversation_id }; }
    key(data) { return `${Number(data.conversation_id)}:${data.call_id}`; }
    notify(message) { this.app.ui?.showToast(String(message)); }
    matches(data) { return !this.disposed && this.state.matches(data); }

    isCurrent(call) {
        if (this.disposed || !this.state.isCurrent(call)) return false;
        if (call.socket !== this.socket) { this.endCall(true); return false; }
        if (String(this.app.currentConversationId) !== String(call.selectedConversationId) ||
            (call.selectionRevision !== undefined && this.app.selectionRevision !== call.selectionRevision)) {
            // Also protects captures when an adapter's conversation-switch cleanup is delayed.
            this.endCall();
            return false;
        }
        return true;
    }

    isPeerCurrent(call, peer) {
        return this.isCurrent(call) && !peer.closed && this.remotePeers.get(peer.userId) === peer;
    }

    rememberTerminal(data) {
        if (!CallState.validSignal(data)) return;
        const key = this.key(data);
        this.terminalCalls.add(key);
        this.earlySignals.delete(key);
        this.earlyStates.delete(key);
        if (this.terminalCalls.size > 64) this.terminalCalls.delete(this.terminalCalls.values().next().value);
    }

    beginCall(data, phase) {
        const call = this.state.begin(data, phase);
        if (!call) return null;
        Object.assign(call, {
            selectedConversationId: this.app.currentConversationId, selectionRevision: this.app.selectionRevision, socket: this.socket,
            accepted: false, serverJoined: false, requestAttempted: false, revision: -1,
            participants: new Map(), pairs: new Map(), peerRevisions: new Map(), media: new Map(), mediaRevision: 0,
            streamRevision: 0, mediaQueue: Promise.resolve(), mediaOperation: false,
            sendingChat: false, chatMessages: [], chatKeys: new Set()
        });
        return call;
    }

    deadline(call, milliseconds, message) {
        this.clearTimer(call.timer);
        call.timer = this.setTimer(() => {
            if (!this.isCurrent(call)) return;
            this.notify(message);
            this.endCall();
        }, milliseconds);
    }

    ack(result, call) {
        if (!result || result.success !== true) {
            throw new Error(typeof result?.error === 'string' ? result.error : result?.message || 'Máy chủ chưa chấp nhận thao tác cuộc gọi');
        }
        if ((result.call_id != null && result.call_id !== call.call_id) ||
            (result.conversation_id != null && Number(result.conversation_id) !== call.conversation_id)) {
            throw new Error('Xác nhận cuộc gọi không khớp');
        }
        return result;
    }

    async request(call, event, payload = {}) {
        if (!this.isCurrent(call)) return null;
        if (!this.socket?.connected || typeof this.socket.request !== 'function') throw new Error('Kết nối chat đã bị ngắt');
        const result = this.ack(await this.socket.request(event, { ...this.scope(call), ...payload }), call);
        if (!this.isCurrent(call)) return null;
        return result;
    }

    fail(call, error) {
        if (!this.isCurrent(call)) return false;
        this.lastError = String(error?.message || 'Không thể thực hiện cuộc gọi nhóm');
        this.notify(this.lastError);
        this.endCall();
        return false;
    }

    async startCall(isVideo = true) {
        if (this.disposed || this.isBusy || this.isDirectCallBusy()) return false;
        const conversationId = positiveId(this.app.currentConversationId);
        const ownId = positiveId(this.app.userId);
        const people = this.app.participants;
        if (this.app.currentConversationType !== 'group' || !conversationId || !ownId || !this.socket?.connected) {
            this.notify('Chọn cuộc trò chuyện nhóm và kết nối chat để gọi');
            return false;
        }
        if (!Array.isArray(people) || people.length < 2 || people.length > 4) {
            this.notify('Cuộc gọi nhóm hiện hỗ trợ nhóm có từ 2 đến 4 thành viên. Hãy chọn nhóm nhỏ hơn.');
            return false;
        }
        const ids = people.map(person => positiveId(person.id));
        if (ids.includes(null) || new Set(ids).size !== ids.length || !ids.includes(ownId)) {
            this.notify('Danh sách thành viên chưa sẵn sàng. Hãy chọn lại cuộc trò chuyện nhóm.');
            return false;
        }
        let call;
        try {
            call = this.beginCall({ call_id: this.newCallId(), conversation_id: conversationId, isVideo: !!isVideo }, 'preparing');
            if (!call) return false;
            for (const person of people) call.participants.set(Number(person.id), {
                user_id: Number(person.id), name: String(person.nickname || person.name || 'Thành viên'), status: 'invited'
            });
            this.openOverlay();
            this.render(call);
            this.deadline(call, 30000, 'Cuộc gọi nhóm đã hết thời gian chờ. Vui lòng thử lại.');
            call.requestAttempted = true;
            const result = await this.request(call, 'group_call_start', {
                request_id: call.call_id, invite_user_ids: ids.filter(id => id !== ownId).sort((a, b) => a - b), isVideo: call.isVideo
            });
            if (!result) return false;
            call.accepted = true; // Participation ACK, never proof of a connected peer.
            const snapshot = result.state || (this.validState(result) ? result : null);
            if (snapshot) await this.handleState(snapshot);
            if (!await this.captureLocal(call)) return false;
            call.phase = 'connecting';
            this.reconcilePeers(call);
            this.broadcastMediaStatus(call);
            this.render(call);
            return this.isCurrent(call);
        } catch (error) { return call ? this.fail(call, error) : false; }
    }

    handleInvited(data) {
        if (!CallState.validSignal(data) || typeof data.invite_id !== 'string' || !data.invite_id || data.invite_id.length > 128 ||
            !positiveId(this.app.userId) || String(data.sender_id) === String(this.app.userId) ||
            this.terminalCalls.has(this.key(data)) || this.disposed) return false;
        if (this.matches(data)) return false;
        if (this.isBusy || this.isDirectCallBusy()) {
            this.rememberTerminal(data);
            this.leaveScope(data);
            return false;
        }
        const call = this.beginCall({ ...this.scope({ ...data, conversation_id: Number(data.conversation_id) }),
            invite_id: data.invite_id, isVideo: data.isVideo === true }, 'invited');
        if (!call) return false;
        call.requestAttempted = true;
        call.participants.set(Number(this.app.userId), { user_id: Number(this.app.userId), name: this.app.userName || 'Bạn', status: 'invited' });
        const senderId = positiveId(data.sender_id);
        if (senderId) call.participants.set(senderId, { user_id: senderId, name: String(data.sender_name || 'Thành viên'), status: 'joined' });
        this.openOverlay();
        this.deadline(call, 45000, 'Lời mời gọi nhóm đã hết hạn');
        const early = this.earlyStates.get(this.key(call));
        this.earlyStates.delete(this.key(call));
        if (early) this.handleState(early);
        this.render(call);
        return this.isCurrent(call);
    }

    async acceptCall() {
        const call = this.currentCall;
        if (!call || call.phase !== 'invited' || !this.isCurrent(call)) return false;
        if (this.isDirectCallBusy()) { this.endCall(); return false; }
        call.phase = 'accepting'; // Lock before media permission and double-clicks.
        this.deadline(call, 30000, 'Không thể tham gia cuộc gọi nhóm. Vui lòng thử lại.');
        this.render(call);
        try {
            if (!await this.captureLocal(call)) return false;
            const result = await this.request(call, 'group_call_join', { invite_id: call.invite_id });
            if (!result) return false;
            call.accepted = true;
            call.phase = 'connecting';
            const snapshot = result.state || (this.validState(result) ? result : null);
            if (snapshot) await this.handleState(snapshot);
            this.reconcilePeers(call);
            this.broadcastMediaStatus(call);
            this.render(call);
            return this.isCurrent(call);
        } catch (error) { return this.fail(call, error); }
    }

    async captureLocal(call) {
        if (call.mediaPromise) return call.mediaPromise;
        if (!this.mediaDevices?.getUserMedia) throw new Error('Trình duyệt không hỗ trợ camera hoặc micro');
        call.mediaPromise = (async () => {
            const stream = await this.mediaDevices.getUserMedia({ audio: true, video: call.isVideo });
            if (!this.isCurrent(call)) { stopStream(stream); return false; }
            this.localStream = stream;
            call.outgoingVideoTrack = stream.getVideoTracks().find(liveTrack) || null;
            for (const track of stream.getTracks()) {
                const refresh = () => { if (this.isCurrent(call)) { this.broadcastMediaStatus(call); this.render(call); } };
                if (track.addEventListener) {
                    track.addEventListener('ended', refresh);
                    (call.trackListeners ||= []).push(() => track.removeEventListener('ended', refresh));
                }
            }
            this.render(call);
            return true;
        })();
        return call.mediaPromise;
    }

    validState(data) {
        return CallState.validSignal(data) && Number.isSafeInteger(data.revision) && data.revision >= 0 &&
            ['waiting', 'active', 'ended'].includes(data.status) && Array.isArray(data.participants) && data.participants.length <= 4 &&
            Array.isArray(data.pairs) && data.pairs.length <= 6;
    }

    async handleState(data) {
        if (!this.validState(data) || this.disposed || this.terminalCalls.has(this.key(data))) return false;
        if (!this.matches(data)) {
            if (data.status === 'ended') this.rememberTerminal(data);
            else if (!this.currentCall) {
                const previous = this.earlyStates.get(this.key(data));
                if (!previous || previous.revision < data.revision) this.earlyStates.set(this.key(data), data);
                if (this.earlyStates.size > MAX_EARLY_CALLS) this.earlyStates.delete(this.earlyStates.keys().next().value);
            }
            return false;
        }
        const call = this.currentCall;
        if (!this.isCurrent(call) || data.revision <= call.revision) return false;
        if (data.status === 'ended') { await this.endCall(true); return true; }
        const people = new Map();
        for (const person of data.participants) {
            const id = positiveId(person.user_id);
            if (!id || people.has(id) || !['joined', 'invited'].includes(person.status)) return false;
            people.set(id, { ...person, user_id: id, name: String(person.name || 'Thành viên') });
        }
        const own = people.get(Number(this.app.userId));
        if (!own) { await this.endCall(true); return true; }
        const pairs = new Map();
        for (const pair of data.pairs) {
            if (!validPairId(pair.pair_id) || !validRevision(pair.peer_revision) || !Array.isArray(pair.user_ids) || pair.user_ids.length !== 2) return false;
            const ids = pair.user_ids.map(positiveId);
            const offerer = positiveId(pair.offerer_user_id);
            if (ids.includes(null) || ids[0] === ids[1] || !ids.includes(offerer) || ids.some(id => people.get(id)?.status !== 'joined')) return false;
            if (!ids.includes(Number(this.app.userId))) continue;
            const remoteId = ids.find(id => id !== Number(this.app.userId));
            const previous = call.peerRevisions.get(remoteId);
            if (pairs.has(remoteId) || (previous && pair.peer_revision < previous.peer_revision) ||
                (previous && pair.peer_revision === previous.peer_revision && pair.pair_id !== previous.pair_id)) return false;
            pairs.set(remoteId, { ...pair, user_ids: ids, offerer_user_id: offerer });
        }
        if (pairs.size > MAX_PEERS) return false;
        for (const [id, pair] of pairs) call.peerRevisions.set(id, { pair_id: pair.pair_id, peer_revision: pair.peer_revision });
        call.revision = data.revision;
        call.roomStatus = data.status;
        call.serverJoined = own.status === 'joined';
        call.participants = people;
        call.pairs = pairs;
        for (const person of people.values()) this.applyMediaSnapshot(call, person);
        if (call.accepted && !call.serverJoined) { await this.endCall(true); return true; }
        this.reconcilePeers(call);
        this.render(call);
        return true;
    }

    reconcilePeers(call) {
        if (!this.isCurrent(call)) return;
        for (const [id, peer] of this.remotePeers) {
            const pair = call.pairs.get(id);
            if (!pair || pair.pair_id !== peer.pair_id || pair.peer_revision !== peer.peer_revision || !call.serverJoined) {
                this.closePeer(peer);
                this.remotePeers.delete(id);
            }
        }
        this.pruneEarlySignals(call);
        if (!call.accepted || !call.serverJoined || !this.localStream) return;
        for (const [id, pair] of call.pairs) {
            if (this.remotePeers.has(id) || this.remotePeers.size >= MAX_PEERS) continue;
            const peer = this.createPeer(call, id, pair);
            if (!peer) continue;
            this.drainEarlySignals(call, peer);
            if (peer.offerer_user_id === Number(this.app.userId)) this.offerPeer(call, peer);
        }
        this.updateConnected(call);
    }

    createPeer(call, id, pair) {
        let pc;
        try {
            pc = this.makePeer(this.config);
            if (!this.isCurrent(call)) { pc.close(); return null; }
            const peer = new PeerSession(id, pair, pc, this.makeStream);
            this.remotePeers.set(id, peer);
            for (const track of this.localStream.getAudioTracks().filter(liveTrack)) peer.audioSender = pc.addTrack(track, this.localStream);
            const video = call.outgoingVideoTrack;
            if (liveTrack(video)) peer.videoSender = pc.addTrack(video, this.screenStream || this.localStream);
            else if (pc.addTransceiver) peer.videoSender = pc.addTransceiver('video', { direction: 'sendrecv' }).sender;
            if (!peer.videoSender) throw new Error('Trình duyệt không hỗ trợ chia sẻ màn hình trong cuộc gọi thoại');
            pc.onicecandidate = event => {
                if (!this.isPeerCurrent(call, peer) || !event.candidate?.candidate) return;
                const candidate = event.candidate.toJSON ? event.candidate.toJSON() : event.candidate;
                const key = JSON.stringify(candidate);
                if (peer.localIceKeys.has(key) || peer.localIce.length >= MAX_QUEUED_SIGNALS || peer.localIceKeys.size >= 256) return;
                peer.localIceKeys.add(key);
                peer.localIce.push(candidate);
                this.flushLocalIce(call, peer);
            };
            pc.ontrack = event => this.handleTrack(call, peer, event);
            pc.onconnectionstatechange = () => {
                if (!this.isPeerCurrent(call, peer)) return;
                peer.connected = pc.connectionState === 'connected';
                if (peer.connected) this.clearTimer(peer.timer);
                else if (['failed', 'closed'].includes(pc.connectionState)) this.failPeer(call, peer, new Error('Kết nối thất bại'));
                else if (pc.connectionState === 'disconnected') this.peerDeadline(call, peer, 10000);
                this.updateConnected(call);
                this.render(call);
            };
            this.peerDeadline(call, peer, 25000);
            this.ensurePeerAudio(call, peer);
            return peer;
        } catch (error) {
            const peer = this.remotePeers.get(id);
            if (peer) this.failPeer(call, peer, error);
            else { pc?.close(); this.notify('Không thể tạo kết nối với thành viên nhóm'); }
            return null;
        }
    }

    peerDeadline(call, peer, milliseconds) {
        this.clearTimer(peer.timer);
        peer.timer = this.setTimer(() => {
            if (this.isPeerCurrent(call, peer) && !peer.connected) {
                this.failPeer(call, peer, new Error('Hết thời gian chờ kết nối'));
            }
        }, milliseconds);
    }

    queuePeer(call, peer, operation) {
        const task = peer.queue.then(async () => {
            if (!this.isPeerCurrent(call, peer)) return false;
            return operation();
        }).catch(error => {
            if (this.isPeerCurrent(call, peer)) this.failPeer(call, peer, error);
            return false;
        });
        peer.queue = task;
        return task;
    }

    async signalPeer(call, peer, type, payload) {
        if (!this.isPeerCurrent(call, peer)) return false;
        const result = await this.request(call, 'group_call_signal', {
            target_user_id: peer.userId, pair_id: peer.pair_id, peer_revision: peer.peer_revision, type, payload
        });
        return !!result && this.isPeerCurrent(call, peer);
    }

    offerPeer(call, peer) {
        if (peer.offerStarted) return peer.queue;
        peer.offerStarted = true;
        return this.queuePeer(call, peer, async () => {
            const offer = await peer.pc.createOffer();
            if (!this.isPeerCurrent(call, peer)) return false;
            await peer.pc.setLocalDescription(offer);
            if (!this.isPeerCurrent(call, peer)) return false;
            peer.descriptionReady = true;
            peer.awaitingAnswer = true;
            if (!await this.signalPeer(call, peer, 'offer', peer.pc.localDescription || offer)) return false;
            peer.signalReady = true;
            if (peer.pendingAnswer) {
                const pending = peer.pendingAnswer;
                peer.pendingAnswer = null;
                await this.applyAnswer(call, peer, pending);
            }
            if (!peer.awaitingAnswer) this.flushLocalIce(call, peer);
            return this.isPeerCurrent(call, peer);
        });
    }

    validSignal(data) {
        if (!CallState.validSignal(data) || !validPairId(data.pair_id) || !validRevision(data.peer_revision) ||
            !positiveId(data.sender_id) || Number(data.target_user_id) !== Number(this.app.userId) ||
            Number(data.sender_id) === Number(this.app.userId) || !['offer', 'answer', 'ice'].includes(data.type)) return false;
        if (data.type === 'ice') return typeof data.payload?.candidate === 'string' && data.payload.candidate.length > 0 && data.payload.candidate.length <= 8192;
        return data.payload?.type === data.type && typeof data.payload.sdp === 'string' && data.payload.sdp.length > 0 && data.payload.sdp.length <= 65536;
    }

    handleSignal(data) {
        if (!this.validSignal(data) || this.disposed || this.terminalCalls.has(this.key(data))) return Promise.resolve(false);
        if (!this.matches(data)) {
            if (!this.currentCall && !this.isDirectCallBusy()) this.queueEarlySignal(data);
            return Promise.resolve(false);
        }
        const call = this.currentCall;
        if (!this.isCurrent(call)) return Promise.resolve(false);
        const id = Number(data.sender_id);
        const pair = call.pairs.get(id);
        const peer = this.remotePeers.get(id);
        if (!pair || !peer) {
            // Signals never authorize a peer; a matching accepted pair in room state does.
            if (pair && (data.peer_revision < pair.peer_revision ||
                (data.peer_revision === pair.peer_revision && pair.pair_id !== data.pair_id))) return Promise.resolve(false);
            this.queueEarlySignal(data);
            return Promise.resolve(false);
        }
        if (peer.pair_id !== data.pair_id || peer.peer_revision !== data.peer_revision) return Promise.resolve(false);
        return this.processSignal(call, peer, data);
    }

    signalKey(data) { return `${Number(data.sender_id)}:${data.pair_id}:${data.peer_revision}`; }
    queueEarlySignal(data) {
        const callKey = this.key(data);
        const calls = this.earlySignals.get(callKey) || new Map();
        const key = this.signalKey(data);
        const queue = calls.get(key) || [];
        if (calls.size >= 8 && !calls.has(key)) return;
        if ([...calls.values()].reduce((count, items) => count + items.length, 0) >= 256 || queue.length >= MAX_QUEUED_SIGNALS) return;
        const duplicate = JSON.stringify(data.payload);
        if (!queue.some(item => item.type === data.type && JSON.stringify(item.payload) === duplicate)) queue.push(data);
        calls.set(key, queue);
        this.earlySignals.set(callKey, calls);
        if (this.earlySignals.size > MAX_EARLY_CALLS) this.earlySignals.delete(this.earlySignals.keys().next().value);
    }

    pruneEarlySignals(call) {
        const queues = this.earlySignals.get(this.key(call));
        if (!queues) return;
        for (const [key, queue] of queues) {
            const signal = queue[0];
            const pair = signal && call.pairs.get(Number(signal.sender_id));
            // Future room state can arrive after its signal; old revisions cannot survive it.
            if (pair && (signal.peer_revision < pair.peer_revision ||
                (signal.peer_revision === pair.peer_revision && signal.pair_id !== pair.pair_id))) queues.delete(key);
            else if (call.revision >= 0 && !call.participants.has(Number(signal?.sender_id))) queues.delete(key);
        }
        if (!queues.size) this.earlySignals.delete(this.key(call));
    }

    drainEarlySignals(call, peer) {
        const queues = this.earlySignals.get(this.key(call));
        const key = this.signalKey({ sender_id: peer.userId, pair_id: peer.pair_id, peer_revision: peer.peer_revision });
        const queued = queues?.get(key) || [];
        queues?.delete(key);
        if (queues && !queues.size) this.earlySignals.delete(this.key(call));
        for (const data of queued) this.processSignal(call, peer, data);
    }

    processSignal(call, peer, data) {
        if (data.type === 'ice') {
            const key = JSON.stringify(data.payload);
            if (peer.iceKeys.has(key) || peer.iceKeys.size >= 256 || peer.queuedIce.length >= MAX_QUEUED_SIGNALS) return Promise.resolve(false);
            peer.iceKeys.add(key);
            peer.queuedIce.push(data.payload);
            return this.queuePeer(call, peer, () => this.drainIce(call, peer));
        }
        return this.queuePeer(call, peer, async () => {
            if (data.type === 'answer') {
                if (peer.offerer_user_id !== Number(this.app.userId)) return false;
                if (!peer.descriptionReady) { peer.pendingAnswer ||= data.payload; return false; }
                return this.applyAnswer(call, peer, data.payload);
            }
            if (peer.offerer_user_id === Number(this.app.userId) || peer.remoteOffer || peer.pc.signalingState !== 'stable') return false;
            peer.remoteOffer = data.payload.sdp;
            await peer.pc.setRemoteDescription(data.payload);
            if (!this.isPeerCurrent(call, peer)) return false;
            await this.drainIce(call, peer);
            if (!this.isPeerCurrent(call, peer)) return false;
            const answer = await peer.pc.createAnswer();
            if (!this.isPeerCurrent(call, peer)) return false;
            await peer.pc.setLocalDescription(answer);
            if (!this.isPeerCurrent(call, peer)) return false;
            peer.descriptionReady = true;
            if (!await this.signalPeer(call, peer, 'answer', peer.pc.localDescription || answer)) return false;
            peer.signalReady = true;
            this.flushLocalIce(call, peer);
            return true;
        });
    }

    async applyAnswer(call, peer, answer) {
        if (!peer.awaitingAnswer || peer.pc.signalingState !== 'have-local-offer') return false;
        await peer.pc.setRemoteDescription(answer);
        if (!this.isPeerCurrent(call, peer)) return false;
        peer.awaitingAnswer = false;
        await this.drainIce(call, peer);
        this.flushLocalIce(call, peer);
        return this.isPeerCurrent(call, peer);
    }

    async drainIce(call, peer) {
        if (!peer.pc.remoteDescription) return false;
        while (this.isPeerCurrent(call, peer) && peer.queuedIce.length) {
            const candidate = peer.queuedIce.shift();
            try { await peer.pc.addIceCandidate(candidate); }
            catch {
                if (this.isPeerCurrent(call, peer)) this.feedback('Một đường kết nối không khả dụng; đang thử các đường kết nối còn lại.');
            }
        }
        return this.isPeerCurrent(call, peer);
    }

    flushLocalIce(call, peer) {
        if (!this.isPeerCurrent(call, peer) || !peer.signalReady || !peer.descriptionReady || peer.awaitingAnswer || peer.flushingIce) return;
        peer.flushingIce = true;
        peer.iceFlush = (async () => {
            while (this.isPeerCurrent(call, peer) && peer.localIce.length) {
                if (!await this.signalPeer(call, peer, 'ice', peer.localIce.shift())) return false;
            }
            return this.isPeerCurrent(call, peer);
        })().catch(error => {
            if (this.isPeerCurrent(call, peer)) this.failPeer(call, peer, error);
            return false;
        }).finally(() => {
            peer.flushingIce = false;
            peer.iceFlush = null;
            if (this.isPeerCurrent(call, peer) && peer.localIce.length) this.flushLocalIce(call, peer);
        });
    }

    handleTrack(call, peer, event) {
        if (!this.isPeerCurrent(call, peer)) return;
        const tracks = event.streams?.flatMap(stream => stream.getTracks()) || [event.track];
        for (const track of tracks.filter(Boolean)) {
            if (peer.remoteStream.getTracks().some(existing => existing.id === track.id)) continue;
            peer.remoteStream.addTrack(track);
            (track.kind === 'audio' ? peer.audioStream : peer.videoStream).addTrack(track);
            const refresh = () => { if (this.isPeerCurrent(call, peer)) this.render(call); };
            for (const type of ['ended', 'mute', 'unmute']) {
                track.addEventListener?.(type, refresh);
                peer.listeners.push(() => track.removeEventListener?.(type, refresh));
            }
        }
        this.ensurePeerAudio(call, peer);
        this.playMedia(peer.audio, call, peer);
        this.render(call);
    }

    updateConnected(call) {
        if (!this.isCurrent(call)) return;
        const connected = [...this.remotePeers.values()].some(peer => !peer.closed && peer.connected);
        this.isCallActive = call.accepted && call.serverJoined && connected;
        if (this.isCallActive) {
            call.phase = 'connected';
            this.clearTimer(call.timer);
        } else if (call.accepted && this.localStream) call.phase = 'connecting';
    }

    failPeer(call, peer, error) {
        if (!this.isPeerCurrent(call, peer)) return false;
        peer.failed = true;
        this.closePeer(peer);
        const name = call.participants.get(peer.userId)?.name || 'Thành viên';
        this.feedback(`Không thể kết nối với ${name}. Các thành viên khác vẫn có thể tiếp tục cuộc gọi.`);
        this.lastPeerError = String(error?.message || 'Kết nối thất bại');
        this.updateConnected(call);
        this.render(call);
        return false;
    }

    mediaFor(call, userId) {
        if (!call.media.has(userId)) call.media.set(userId, { mic: true, cam: call.isVideo, sharing: false, revisions: {} });
        return call.media.get(userId);
    }

    applyMediaSnapshot(call, person) {
        const media = this.mediaFor(call, person.user_id);
        for (const [type, key] of [['mic', 'mic_enabled'], ['cam', 'cam_enabled']]) {
            const revision = person.media_revisions?.[type] ?? person.media_revision;
            if (typeof person[key] === 'boolean' && Number.isSafeInteger(revision) && revision >= 0 && revision >= (media.revisions[type] ?? -1)) {
                media[type] = person[key];
                media.revisions[type] = revision;
            }
        }
        const streamRevision = person.stream_revision;
        if (typeof person.is_sharing === 'boolean') {
            if (Number.isSafeInteger(streamRevision) && streamRevision >= 0 && streamRevision >= (media.revisions.stream ?? -1)) {
                media.sharing = person.is_sharing;
                media.revisions.stream = streamRevision;
            } else if (streamRevision == null && media.revisions.stream === undefined) {
                // Legacy flat snapshot has no stream counter. Never compare it with the unrelated media counter.
                media.sharing = person.is_sharing;
            }
        }
    }

    handleMediaStatus(data) {
        if (!this.matches(data) || typeof data.enabled !== 'boolean' || !['mic', 'cam'].includes(data.type) || !validRevision(data.revision)) return false;
        const call = this.currentCall;
        const id = positiveId(data.sender_id ?? data.user_id);
        if (!this.isCurrent(call) || !call.accepted || !id || id === Number(this.app.userId) || call.participants.get(id)?.status !== 'joined') return false;
        const media = this.mediaFor(call, id);
        if (data.revision <= (media.revisions[data.type] ?? -1)) return false;
        media[data.type] = data.enabled;
        media.revisions[data.type] = data.revision;
        this.render(call);
        return true;
    }

    handleStreamStatus(data) {
        if (!this.matches(data) || typeof data.is_streaming !== 'boolean' || !validRevision(data.revision)) return false;
        const call = this.currentCall;
        const id = positiveId(data.sender_id ?? data.user_id);
        if (!this.isCurrent(call) || !call.accepted || !id || id === Number(this.app.userId) || call.participants.get(id)?.status !== 'joined') return false;
        const media = this.mediaFor(call, id);
        if (data.revision <= (media.revisions.stream ?? -1)) return false;
        media.sharing = data.is_streaming;
        media.revisions.stream = data.revision;
        this.render(call);
        return true;
    }

    broadcastMediaStatus(call = this.currentCall) {
        if (!this.isCurrent(call) || !call.accepted || !call.serverJoined || !this.localStream) return false;
        const revision = ++call.mediaRevision;
        for (const [kind, type] of [['audio', 'mic'], ['video', 'cam']]) {
            const track = this.localStream.getTracks().find(item => item.kind === kind && liveTrack(item));
            this.socket?.emit('media_status', { ...this.scope(call), type, enabled: !!track?.enabled, revision });
        }
        return true;
    }

    toggleMic() { return this.toggleTrack('audio'); }
    toggleCamera() { return this.toggleTrack('video'); }
    toggleTrack(kind) {
        const call = this.currentCall;
        if (!this.isCurrent(call) || !call.accepted || !call.serverJoined) return false;
        const tracks = this.localStream?.getTracks().filter(track => track.kind === kind && liveTrack(track)) || [];
        if (!tracks.length) return false;
        const enabled = !tracks.some(track => track.enabled);
        for (const track of tracks) track.enabled = enabled;
        this.broadcastMediaStatus(call);
        this.render(call);
        return true;
    }

    serializeMedia(call, operation) {
        const task = call.mediaQueue.then(async () => {
            if (!this.isCurrent(call) || !call.accepted || !call.serverJoined) return false;
            call.mediaOperation = true;
            this.render(call);
            try { return await operation(); }
            catch (error) {
                if (this.isCurrent(call)) this.feedback(String(error?.message || 'Không thể chia sẻ màn hình. Vui lòng thử lại.'));
                return false;
            } finally {
                call.mediaOperation = false;
                if (this.isCurrent(call)) this.render(call);
            }
        });
        call.mediaQueue = task;
        return task;
    }

    startScreenShare() {
        const call = this.currentCall;
        if (!this.isCurrent(call)) return Promise.resolve(false);
        return this.serializeMedia(call, async () => {
            if (this.isSharingScreen || !this.mediaDevices?.getDisplayMedia) return false;
            const stream = await this.mediaDevices.getDisplayMedia({ video: true, audio: false });
            if (!this.isCurrent(call)) { stopStream(stream); return false; }
            const track = stream.getVideoTracks().find(liveTrack);
            if (!track) { stopStream(stream); throw new Error('Không có màn hình để chia sẻ'); }
            this.screenStream = stream;
            call.outgoingVideoTrack = track; // New accepted peers immediately get the current track.
            await this.replaceVideoForPeers(call, track);
            if (!this.isCurrent(call)) { stopStream(stream); return false; }
            this.isSharingScreen = true;
            track.onended = () => { if (this.isCurrent(call)) this.stopScreenShare(); };
            this.socket?.emit('stream_status', { ...this.scope(call), is_streaming: true, revision: ++call.streamRevision });
            this.render(call);
            return true;
        });
    }

    stopScreenShare() {
        const call = this.currentCall;
        if (!this.isCurrent(call)) return Promise.resolve(false);
        return this.serializeMedia(call, async () => {
            if (!this.isSharingScreen || !this.screenStream) return false;
            const stream = this.screenStream;
            const camera = this.localStream?.getVideoTracks().find(liveTrack) || null;
            call.outgoingVideoTrack = camera;
            this.screenStream = null;
            await this.replaceVideoForPeers(call, camera);
            stream.getTracks().forEach(track => { track.onended = null; track.stop(); });
            if (!this.isCurrent(call)) return false;
            this.isSharingScreen = false;
            this.socket?.emit('stream_status', { ...this.scope(call), is_streaming: false, revision: ++call.streamRevision });
            this.render(call);
            return true;
        });
    }

    async replaceVideoForPeers(call, track) {
        // No SDP rewrite or renegotiation. Each edge serializes replaceTrack with its SDP/ICE.
        await Promise.all([...this.remotePeers.values()].map(peer => this.queuePeer(call, peer, async () => {
            if (!peer.videoSender?.replaceTrack) throw new Error('Trình duyệt không hỗ trợ thay đổi nguồn video');
            await peer.videoSender.replaceTrack(track);
            return this.isPeerCurrent(call, peer);
        })));
    }

    async sendCallChatMessage(text = null) {
        const call = this.currentCall;
        const input = this.elements.chatInput;
        text = text == null ? input?.value.trim() : String(text).trim();
        if (!this.isCurrent(call) || !call.accepted || !call.serverJoined || call.sendingChat || !text || text.length > 1000) return false;
        call.sendingChat = true;
        this.renderControls(call);
        const timestamp = this.now();
        try {
            if (!await this.request(call, 'call_chat_message', { text, timestamp })) return false;
            if (input?.value.trim() === text) input.value = '';
            this.addChatMessage(call, { sender_id: Number(this.app.userId), text, timestamp, own: true });
            return true;
        } catch {
            if (this.isCurrent(call)) this.feedback('Không thể gửi tin nhắn trong cuộc gọi. Vui lòng thử lại.');
            return false;
        } finally {
            call.sendingChat = false;
            if (this.isCurrent(call)) this.renderControls(call);
        }
    }

    handleCallChatMessage(data) {
        if (!this.matches(data) || typeof data.text !== 'string' || !data.text.trim() || data.text.length > 1000) return false;
        const call = this.currentCall;
        const id = positiveId(data.sender_id);
        if (!this.isCurrent(call) || !call.accepted || !call.serverJoined || !id || id === Number(this.app.userId) || call.participants.get(id)?.status !== 'joined') return false;
        return this.addChatMessage(call, data);
    }

    addChatMessage(call, data) {
        if (!this.isCurrent(call)) return false;
        const key = data.message_id != null ? String(data.message_id) : `${data.sender_id}:${data.timestamp}:${data.text}`;
        if (call.chatKeys.has(key)) return false;
        call.chatKeys.add(key);
        call.chatMessages.push({ ...data, key });
        if (call.chatMessages.length > MAX_CHAT_MESSAGES) call.chatKeys.delete(call.chatMessages.shift().key);
        this.renderChat(call);
        return true;
    }

    leaveScope(data) {
        const call = { ...data, conversation_id: Number(data.conversation_id) };
        if (!CallState.validSignal(call) || !this.socket?.connected || typeof this.socket.request !== 'function') return Promise.resolve(false);
        const key = this.key(call);
        if (this.pendingLeaves.has(key)) return this.pendingLeaves.get(key).promise;
        const operation = {};
        operation.promise = new Promise(resolve => {
            const finish = value => {
                if (operation.finished) return;
                operation.finished = true;
                this.clearTimer(operation.timer);
                if (this.pendingLeaves.get(key) === operation) this.pendingLeaves.delete(key);
                resolve(value);
            };
            operation.finish = finish;
            operation.timer = this.setTimer(() => finish(false), 8000);
            Promise.resolve().then(() => this.socket.request('group_call_leave', this.scope(call)))
                .then(result => { this.ack(result, call); finish(true); }, () => finish(false))
                .catch(() => finish(false));
        });
        this.pendingLeaves.set(key, operation);
        return operation.promise;
    }

    async endCall(isRemote = false) {
        const call = this.state.end(); // Invalidate first; pending permissions and SDP cannot revive it.
        if (!call) return false;
        this.rememberTerminal(call);
        this.clearTimer(call.timer);
        for (const remove of call.trackListeners || []) remove();
        for (const peer of this.remotePeers.values()) this.closePeer(peer);
        this.remotePeers.clear();
        const tracks = new Set([this.localStream, this.screenStream].flatMap(stream => stream?.getTracks() || []));
        for (const track of tracks) { track.onended = null; track.stop(); }
        this.localStream = null;
        this.screenStream = null;
        this.isSharingScreen = false;
        this.isCallActive = false;
        this.earlySignals.clear();
        this.earlyStates.clear();
        for (const tile of this.tiles.values()) { tile.video.pause?.(); tile.video.srcObject = null; }
        this.tiles.clear();
        this.elements.grid?.replaceChildren();
        this.elements.chatList?.replaceChildren();
        if (this.elements.chatInput) this.elements.chatInput.value = '';
        this.toggleChat(false);
        this.feedback('');
        this.closeOverlay();
        if (isRemote || !call.requestAttempted) return true;
        const left = await this.leaveScope(call);
        if (!left && !this.disposed && !this.currentCall && this.socket?.connected) this.notify('Chưa xác nhận rời cuộc gọi. Hãy kiểm tra kết nối chat trước khi gọi lại.');
        return left;
    }

    handleSocketDisconnected() {
        for (const operation of [...this.pendingLeaves.values()]) operation.finish(false);
        this.earlySignals.clear();
        this.earlyStates.clear();
        return this.endCall(true);
    }

    dispose() {
        const result = this.endCall();
        this.disposed = true;
        for (const remove of this.uiListeners.splice(0)) remove();
        for (const operation of [...this.pendingLeaves.values()]) operation.finish(false);
        this.earlySignals.clear();
        this.earlyStates.clear();
        return result;
    }

    closePeer(peer) {
        peer.closed = true;
        peer.connected = false;
        this.clearTimer(peer.timer);
        for (const remove of peer.listeners.splice(0)) remove();
        peer.pc.onicecandidate = null;
        peer.pc.ontrack = null;
        peer.pc.onconnectionstatechange = null;
        peer.pc.close();
        peer.queuedIce.length = 0;
        peer.localIce.length = 0;
        peer.pendingAnswer = null;
        peer.remoteStream.getTracks().forEach(track => track.stop());
        peer.audio?.pause?.();
        if (peer.audio) { peer.audio.srcObject = null; peer.audio.remove(); }
    }

    initUI() {
        if (this.disposed || this.uiListeners.length || !this.document) return false;
        const ids = {
            overlay: 'meshCallOverlay', title: 'meshCallTitle', status: 'meshCallStatus', grid: 'meshCallGrid',
            accept: 'meshCallAccept', reject: 'meshCallReject', inviteActions: 'meshCallInviteActions',
            mic: 'meshCallMic', camera: 'meshCallCamera', share: 'meshCallShare', end: 'meshCallEnd',
            chatToggle: 'meshCallChatToggle', chatPanel: 'meshCallChatPanel', chatClose: 'meshCallChatClose',
            chatList: 'meshCallChatList', chatInput: 'meshCallChatInput', chatSend: 'meshCallChatSend',
            feedback: 'meshCallFeedback', playAudio: 'meshCallPlayAudio', audioSinks: 'meshCallAudioSinks'
        };
        for (const [name, id] of Object.entries(ids)) this.elements[name] = this.document.getElementById(id);
        if (!this.elements.overlay) return false;
        const listen = (target, type, fn) => {
            if (!target) return;
            target.addEventListener(type, fn);
            this.uiListeners.push(() => target.removeEventListener(type, fn));
        };
        const run = operation => { this.resumeAudio(); Promise.resolve().then(operation).catch(() => this.feedback('Không thể thực hiện thao tác. Vui lòng thử lại.')); };
        listen(this.elements.accept, 'click', () => run(() => this.acceptCall()));
        listen(this.elements.reject, 'click', () => run(() => this.endCall()));
        listen(this.elements.end, 'click', () => run(() => this.endCall()));
        listen(this.elements.mic, 'click', () => run(() => this.toggleMic()));
        listen(this.elements.camera, 'click', () => run(() => this.toggleCamera()));
        listen(this.elements.share, 'click', () => run(() => this.isSharingScreen ? this.stopScreenShare() : this.startScreenShare()));
        listen(this.elements.chatToggle, 'click', () => this.toggleChat(!this.chatOpen));
        listen(this.elements.chatClose, 'click', () => this.toggleChat(false));
        listen(this.elements.playAudio, 'click', () => this.resumeAudio());
        listen(this.elements.chatSend, 'click', () => run(() => this.sendCallChatMessage()));
        listen(this.elements.chatInput, 'input', () => this.renderControls(this.currentCall));
        listen(this.elements.chatInput, 'keydown', event => {
            if (shouldSendOnEnter(event)) { event.preventDefault(); run(() => this.sendCallChatMessage()); }
        });
        listen(this.elements.overlay, 'cancel', event => { event.preventDefault(); run(() => this.endCall()); });
        listen(this.elements.overlay, 'close', () => { if (this.currentCall) this.endCall(); });
        listen(this.elements.overlay, 'keydown', event => this.trapFocus(event));
        this.renderControls(null);
        return true;
    }

    openOverlay() {
        if (!this.elements.overlay) this.initUI();
        const overlay = this.elements.overlay;
        if (!overlay || this.overlayOpen) return;
        this.returnFocus = this.document.activeElement;
        this.overlayOpen = true;
        overlay.setAttribute('aria-hidden', 'false');
        if (typeof overlay.showModal === 'function') overlay.showModal();
        else overlay.setAttribute('open', '');
        (this.currentCall?.phase === 'invited' ? this.elements.accept : this.elements.end)?.focus();
    }

    closeOverlay() {
        const overlay = this.elements.overlay;
        if (overlay) {
            overlay.setAttribute('aria-hidden', 'true');
            if (typeof overlay.close === 'function' && overlay.open) overlay.close();
            else overlay.removeAttribute('open');
        }
        this.overlayOpen = false;
        this.renderControls(null);
        if (this.returnFocus?.isConnected) this.returnFocus.focus();
        this.returnFocus = null;
    }

    trapFocus(event) {
        if (event.key !== 'Tab' || !this.overlayOpen) return;
        const buttons = [...this.elements.overlay.querySelectorAll('button, textarea')]
            .filter(node => !node.disabled && !node.hidden && !node.closest('[hidden]'));
        if (!buttons.length) return;
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (event.shiftKey && this.document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && this.document.activeElement === last) { event.preventDefault(); first.focus(); }
    }

    feedback(text) {
        if (!this.elements.feedback) return;
        this.elements.feedback.textContent = String(text);
        this.elements.feedback.hidden = !text;
    }

    makeTile(id) {
        const root = createNode('article', 'mesh-call-tile');
        const video = createNode('video', 'mesh-call-tile-video');
        video.muted = true;
        video.autoplay = true;
        video.playsInline = true;
        video.setAttribute('aria-hidden', 'true');
        const placeholder = createNode('div', 'mesh-call-placeholder');
        const avatar = createNode('span', 'mesh-call-avatar');
        avatar.setAttribute('aria-hidden', 'true');
        const placeholderText = createNode('span', 'mesh-call-placeholder-text');
        placeholder.append(avatar, placeholderText);
        const caption = createNode('div', 'mesh-call-tile-caption');
        const name = createNode('span', 'mesh-call-tile-name');
        const status = createNode('span', 'mesh-call-tile-state');
        caption.append(name, status);
        root.append(video, placeholder, caption);
        root.dataset.userId = String(id);
        this.elements.grid.appendChild(root);
        const tile = { root, video, placeholder, avatar, placeholderText, name, status };
        this.tiles.set(id, tile);
        return tile;
    }

    render(call) {
        if (!this.isCurrent(call)) return;
        this.updateConnected(call);
        if (this.elements.title) this.elements.title.textContent = call.isVideo ? 'Cuộc gọi video nhóm' : 'Cuộc gọi thoại nhóm';
        if (this.elements.status) {
            const allConnected = call.pairs.size > 0 && [...call.pairs.keys()].every(id => this.remotePeers.get(id)?.connected);
            this.elements.status.textContent = call.phase === 'invited' ? 'Bạn được mời tham gia cuộc gọi nhóm' :
                ['preparing', 'accepting'].includes(call.phase) ? 'Đang chuẩn bị micro và camera…' :
                    !call.pairs.size ? 'Đang chờ thành viên tham gia…' : allConnected ? 'Đã kết nối' : 'Đang kết nối với các thành viên…';
        }
        if (this.elements.inviteActions) this.elements.inviteActions.hidden = call.phase !== 'invited';
        if (this.elements.grid) {
            for (const [id, tile] of this.tiles) if (!call.participants.has(id)) { tile.video.pause?.(); tile.video.srcObject = null; tile.root.remove(); this.tiles.delete(id); }
            for (const person of call.participants.values()) this.renderTile(call, person);
        }
        this.renderControls(call);
    }

    renderTile(call, person) {
        const id = person.user_id;
        const own = id === Number(this.app.userId);
        const peer = this.remotePeers.get(id);
        const tile = this.tiles.get(id) || this.makeTile(id);
        const media = own ? {
            mic: this.localStream?.getAudioTracks().some(track => liveTrack(track) && track.enabled) || false,
            cam: this.localStream?.getVideoTracks().some(track => liveTrack(track) && track.enabled) || false,
            sharing: this.isSharingScreen
        } : this.mediaFor(call, id);
        const stream = own ? this.screenStream || this.localStream : peer?.videoStream;
        const connected = own ? call.accepted && call.serverJoined : !!peer?.connected;
        const hasVideo = connected && (media.sharing || media.cam) && stream?.getVideoTracks().some(track => liveTrack(track) && !track.muted && track.enabled);
        if (tile.video.srcObject !== (stream || null)) {
            tile.video.srcObject = stream || null;
            if (stream) this.playMedia(tile.video, call);
        }
        tile.video.hidden = !hasVideo;
        tile.placeholder.hidden = !!hasVideo;
        tile.name.textContent = `${person.name}${own ? ' (Bạn)' : ''}`;
        tile.name.title = tile.name.textContent;
        tile.avatar.textContent = Array.from(person.name.trim())[0]?.toLocaleUpperCase('vi') || '?';
        tile.root.dataset.sharing = String(media.sharing);
        tile.placeholderText.textContent = person.status === 'invited' ? 'Chưa tham gia' : peer?.failed ? 'Không thể kết nối' :
            !connected ? 'Đang kết nối…' : media.sharing ? 'Đang tải màn hình…' : call.isVideo ? 'Camera đang tắt' : 'Cuộc gọi thoại';
        tile.status.textContent = person.status === 'invited' ? 'Đang chờ trả lời' : peer?.failed ? 'Kết nối thất bại' :
            !connected ? 'Đang kết nối' : `${media.mic ? 'Micro bật' : 'Micro tắt'}${media.sharing ? ' · Chia sẻ màn hình' : ''}`;
    }

    renderControls(call) {
        const active = !!call && this.state.isCurrent(call) && call.accepted && call.serverJoined && !!this.localStream;
        const mic = this.localStream?.getAudioTracks().find(liveTrack);
        const camera = this.localStream?.getVideoTracks().find(liveTrack);
        for (const [key, enabled, label] of [
            ['mic', !!mic?.enabled, mic?.enabled ? 'Tắt micro' : 'Bật micro'],
            ['camera', !!camera?.enabled, camera?.enabled ? 'Tắt camera' : 'Bật camera'],
            ['share', this.isSharingScreen, this.isSharingScreen ? 'Dừng chia sẻ' : 'Chia sẻ màn hình']
        ]) {
            const button = this.elements[key];
            if (!button) continue;
            button.disabled = !active || (key === 'mic' && !mic) || (key === 'camera' && !camera) || (key === 'share' && (!this.mediaDevices?.getDisplayMedia || call?.mediaOperation));
            button.setAttribute('aria-pressed', String(enabled));
            button.setAttribute('aria-label', label);
            button.title = key === 'camera' && call && !call.isVideo ? 'Cuộc gọi thoại không sử dụng camera' : label;
            const span = button.querySelector('.mesh-call-control-label');
            if (span) span.textContent = label;
        }
        if (this.elements.accept) this.elements.accept.disabled = !call || call.phase !== 'invited';
        if (this.elements.reject) this.elements.reject.disabled = !call || call.phase !== 'invited';
        if (this.elements.end) this.elements.end.disabled = !call;
        if (this.elements.chatToggle) this.elements.chatToggle.disabled = !active;
        if (this.elements.chatInput) this.elements.chatInput.disabled = !active || call?.sendingChat;
        if (this.elements.chatSend) this.elements.chatSend.disabled = !active || call?.sendingChat || !this.elements.chatInput?.value.trim();
        if (this.elements.chatPanel) this.elements.chatPanel.setAttribute('aria-busy', String(!!call?.sendingChat));
        if (this.elements.playAudio) this.elements.playAudio.hidden = ![...this.remotePeers.values()].some(peer => peer.audioBlocked && !peer.closed);
    }

    toggleChat(open) {
        const call = this.currentCall;
        this.chatOpen = !!open && !!call?.accepted && call.serverJoined;
        if (this.elements.chatPanel) this.elements.chatPanel.hidden = !this.chatOpen;
        this.elements.chatToggle?.setAttribute('aria-expanded', String(this.chatOpen));
        if (this.chatOpen) { this.renderChat(call); this.elements.chatInput?.focus(); }
        else if (this.overlayOpen && this.elements.chatToggle && !this.elements.chatToggle.disabled) this.elements.chatToggle.focus();
    }

    renderChat(call) {
        const list = this.elements.chatList;
        if (!list || !this.isCurrent(call)) return;
        list.replaceChildren();
        if (!call.chatMessages.length) list.appendChild(createNode('p', 'mesh-call-chat-empty', 'Chưa có tin nhắn trong cuộc gọi.'));
        for (const message of call.chatMessages) {
            const row = createNode('div', 'mesh-call-chat-message');
            const name = call.participants.get(Number(message.sender_id))?.name || 'Thành viên';
            row.append(createNode('span', 'mesh-call-message-sender', `${name}${message.own ? ' (Bạn)' : ''}`),
                createNode('span', 'mesh-call-message-text', message.text));
            if (message.timestamp != null && this.app.ui?.formatTime) row.appendChild(createNode('span', 'mesh-call-message-time', this.app.ui.formatTime(message.timestamp)));
            list.appendChild(row);
        }
        list.scrollTop = list.scrollHeight;
    }

    ensurePeerAudio(call, peer) {
        if (!this.elements.audioSinks || peer.audio || !this.isPeerCurrent(call, peer)) return;
        const audio = createNode('audio');
        audio.autoplay = true;
        audio.muted = false;
        audio.srcObject = peer.audioStream;
        audio.dataset.userId = String(peer.userId);
        this.elements.audioSinks.appendChild(audio);
        peer.audio = audio;
    }

    playMedia(element, call, peer = null) {
        if (!element?.play || !this.isCurrent(call)) return;
        try {
            Promise.resolve(element.play()).then(() => {
                if (peer && this.isPeerCurrent(call, peer)) { peer.audioBlocked = false; this.renderControls(call); }
            }, () => {
                if (peer && this.isPeerCurrent(call, peer)) {
                    peer.audioBlocked = true;
                    this.feedback('Chọn “Nghe âm thanh” để trình duyệt phát tiếng của cuộc gọi.');
                    this.renderControls(call);
                }
            });
        } catch {
            if (peer && this.isPeerCurrent(call, peer)) { peer.audioBlocked = true; this.renderControls(call); }
        }
    }

    resumeAudio() {
        const call = this.currentCall;
        if (!this.isCurrent(call)) return;
        for (const peer of this.remotePeers.values()) if (peer.audioBlocked) this.playMedia(peer.audio, call, peer);
    }
}

export default MeshCallManager;
