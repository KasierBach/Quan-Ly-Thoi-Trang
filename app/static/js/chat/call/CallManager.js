import CallState from './CallState.js';
import { createNode, shouldSendOnEnter } from '../utils/helpers.js';

/** One socket-bound peer, one immutable call scope, and cancellable async media work. */
export class CallManager {
    constructor(app, dependencies = {}) {
        this.app = app;
        this.state = new CallState();
        this.elements = {};
        this.localStream = null;
        this.remoteStream = null;
        this.screenStream = null;
        this.peerConnection = null;
        this.isCallActive = false;
        this.isSharingScreen = false;
        this.isGridView = false;
        this.pendingCall = null;
        this.terminalCalls = new Set();
        this.earlyIce = new Map();
        this.mediaDevices = dependencies.mediaDevices || globalThis.navigator?.mediaDevices;
        this.makePeer = dependencies.makePeer || (config => new RTCPeerConnection(config));
        this.makeStream = dependencies.makeStream || (() => new MediaStream());
        this.newCallId = dependencies.newCallId || (() => crypto.randomUUID());
        this.setTimer = dependencies.setTimer || ((...args) => globalThis.setTimeout(...args));
        this.clearTimer = dependencies.clearTimer || (timer => globalThis.clearTimeout(timer));
        this.now = dependencies.now || (() => globalThis.performance?.now() ?? Date.now());
        this.uiListeners = [];
        this.callUIListeners = [];
        this.participantListeners = [];
        this.mediaListeners = new Map();
        this.durationTimer = null;
        this.durationCall = null;
        this.durationStartedAt = null;
        this.focusedParticipant = 'remote';
        this.browserOperations = new Map();
        this.overlayOpen = false;
        this.audioNeedsGesture = false;
        this.config = { iceServers: dependencies.iceServers ?? app.rtcIceServers ?? [{ urls: 'stun:stun.l.google.com:19302' }] };
    }

    get socket() { return this.app.socket; }
    get currentCall() { return this.state.current; }
    isCurrent(call) { return !this.disposed && this.state.isCurrent(call); }
    matches(data) { return this.state.matches(data); }
    scope(call) { return { call_id: call.call_id, conversation_id: call.conversation_id }; }
    key(data) { return `${data.conversation_id}:${data.call_id}`; }
    notify(message) { this.app.ui?.showToast(message); }

    rememberTerminal(data) {
        if (!CallState.validSignal(data)) return;
        const key = this.key(data);
        this.terminalCalls.add(key);
        this.earlyIce.delete(key);
        if (this.terminalCalls.size > 64) this.terminalCalls.delete(this.terminalCalls.values().next().value);
    }

    beginCall(data, phase) {
        const call = this.state.begin(data, phase);
        if (!call) return null;
        Object.assign(call, {
            remoteIce: this.earlyIce.get(this.key(call)) || [], localIce: [], iceKeys: new Set(),
            accepted: false, signalReady: phase === 'validating', localDescriptionReady: false,
            remoteDescriptionReady: false, awaitingAnswer: false
        });
        this.earlyIce.clear();
        return call;
    }

    async validatePeer(call, senderId = null) {
        if (!this.app.userId || !this.socket?.connected) throw new Error('Cần đăng nhập và kết nối chat để gọi');
        const [conversation, result] = await Promise.all([
            this.app.api.getConversation(call.conversation_id), this.app.api.getParticipants(call.conversation_id)
        ]);
        if (!this.isCurrent(call)) return false;
        const participants = result.participants || [];
        const ids = new Set(participants.map(person => String(person.id)));
        if (conversation.type !== 'private' || participants.length !== 2 || ids.size !== 2 ||
            !ids.has(String(this.app.userId))) throw new Error('Chỉ hỗ trợ cuộc gọi riêng tư một-một');
        const peer = participants.find(person => String(person.id) !== String(this.app.userId));
        if (senderId != null && String(peer.id) !== String(senderId)) throw new Error('Người gọi không thuộc cuộc trò chuyện');
        call.peerId = peer.id;
        call.peerName = String(peer.nickname || peer.name || 'Người dùng');
        return true;
    }

    deadline(call, milliseconds, message) {
        this.clearTimer(call.timer);
        call.timer = this.setTimer(() => {
            if (!this.isCurrent(call)) return;
            this.notify(message);
            this.endCall();
        }, milliseconds);
    }

    async requestSignal(call, event, payload) {
        if (!this.isCurrent(call)) return null;
        const result = await this.socket.request(event, { ...this.scope(call), ...payload });
        if (result.call_id != null && result.call_id !== call.call_id) throw new Error('Xác nhận cuộc gọi không khớp');
        return this.isCurrent(call) ? result : null;
    }

    fail(call, error) {
        if (!this.isCurrent(call)) return false;
        this.lastError = String(error.message || 'Cuộc gọi không thành công');
        this.notify(this.lastError);
        this.endCall();
        return false;
    }

    async startCall(video = true) {
        if (this.disposed || this.currentCall) return false;
        const cid = this.app.currentConversationId;
        if (!/^\d+$/.test(String(cid)) || !this.app.userId) {
            this.notify('Chỉ hỗ trợ cuộc gọi riêng tư một-một cho tài khoản đã đăng nhập');
            return false;
        }
        const call = this.beginCall({ call_id: this.newCallId(), conversation_id: Number(cid), isVideo: !!video }, 'preparing');
        if (!call) return false;
        this.deadline(call, 30000, 'Cuộc gọi đã hết thời gian chờ');
        try {
            if (!await this.validatePeer(call)) return false;
            this.showOverlay();
            this.showOutgoingModal(call.peerName);
            this.addRemoteParticipantPlaceholder('Đang chờ trả lời...');
            if (!await this.getMedia(video, call)) return false;
            const peer = this.createPeerConnection(call);
            this.addLocalTracks(call, peer);
            call.awaitingAnswer = true;
            const offer = await peer.createOffer();
            if (!this.isCurrent(call)) return false;
            await peer.setLocalDescription(offer);
            if (!this.isCurrent(call)) return false;
            call.localDescriptionReady = true;
            call.phase = 'ringing';
            call.offered = true;
            const result = await this.requestSignal(call, 'call_user', {
                offer: peer.localDescription || offer, isVideo: call.isVideo, target_user_id: call.peerId
            });
            if (!result) return false;
            call.signalReady = true;
            this.flushLocalIce(call);
            await this.applyPendingAnswer(call);
            return this.isCurrent(call);
        } catch (error) { return this.fail(call, error); }
    }

    async handleIncomingCall(data) {
        if (!CallState.validSignal(data) || data.offer?.type !== 'offer' || typeof data.offer.sdp !== 'string' ||
            String(data.sender_id) === String(this.app.userId) || this.terminalCalls.has(this.key(data)) || this.disposed) return false;
        if (data.isResume === true) {
            // Renegotiation may never open a new call or silently reacquire a microphone.
            if (!this.matches(data) || !this.currentCall.accepted || !this.peerConnection) return false;
            const call = this.currentCall;
            if (call.processingOffer) return false;
            call.processingOffer = true;
            try {
                const peer = this.peerConnection;
                if (peer.signalingState !== 'stable' || call.awaitingAnswer) throw new Error('Đàm phán cuộc gọi bị xung đột');
                call.remoteDescriptionReady = false;
                await peer.setRemoteDescription(data.offer);
                if (!this.isCurrent(call)) return false;
                call.remoteDescriptionReady = true;
                await this.processQueuedCandidates(call);
                const answer = await peer.createAnswer();
                if (!this.isCurrent(call)) return false;
                await peer.setLocalDescription(answer);
                if (!this.isCurrent(call)) return false;
                await this.requestSignal(call, 'answer_call', { answer: peer.localDescription || answer });
                this.broadcastMediaStatus();
                return this.isCurrent(call);
            } catch (error) { return this.fail(call, error); }
            finally { call.processingOffer = false; }
        }
        if (this.currentCall) {
            if (this.matches(data)) return false; // Duplicate ring, not a second session.
            this.socket?.emit('reject_call', { call_id: data.call_id, conversation_id: Number(data.conversation_id) });
            this.rememberTerminal(data);
            return false;
        }
        const call = this.beginCall(data, 'validating');
        this.pendingCall = call;
        this.deadline(call, 30000, 'Cuộc gọi đến đã hết thời gian chờ');
        try {
            if (!await this.validatePeer(call, data.sender_id)) return false;
            call.phase = 'ringing';
            this.showOverlay();
            this.showIncomingModal(data);
            return true;
        } catch (error) {
            if (this.isCurrent(call)) this.socket?.emit('reject_call', this.scope(call));
            return this.fail(call, error);
        }
    }

    async acceptCall() {
        const call = this.currentCall;
        if (!call || call !== this.pendingCall || call.phase !== 'ringing') return false;
        call.phase = 'accepting'; // Locks before the first await (double clicks cannot request two streams).
        this.hideIncomingModal();
        this.showActiveView();
        this.setStatus('Đang kết nối...');
        try {
            if (!await this.getMedia(call.isVideo, call)) return false;
            const peer = this.createPeerConnection(call);
            this.addLocalTracks(call, peer);
            await peer.setRemoteDescription(call.offer);
            if (!this.isCurrent(call)) return false;
            call.remoteDescriptionReady = true;
            await this.processQueuedCandidates(call);
            const answer = await peer.createAnswer();
            if (!this.isCurrent(call)) return false;
            await peer.setLocalDescription(answer);
            if (!this.isCurrent(call)) return false;
            call.localDescriptionReady = true;
            this.flushLocalIce(call);
            const result = await this.requestSignal(call, 'answer_call', { answer: peer.localDescription || answer });
            if (!result) return false;
            call.accepted = true;
            call.phase = 'connecting';
            this.deadline(call, 20000, 'Không thể thiết lập kết nối cuộc gọi');
            this.markConnected(call);
            return true;
        } catch (error) { return this.fail(call, error); }
    }

    rejectCall() {
        const call = this.currentCall;
        if (!call) return;
        if (call === this.pendingCall && ['ringing', 'validating'].includes(call.phase)) {
            this.socket?.emit('reject_call', this.scope(call));
            this.endCall(true);
        } else this.endCall();
    }

    async getMedia(video, call = this.currentCall) {
        if (!this.mediaDevices?.getUserMedia) throw new Error('Trình duyệt không hỗ trợ camera/microphone');
        const stream = await this.mediaDevices.getUserMedia({ video: !!video, audio: true });
        if (!this.isCurrent(call)) { stream.getTracks().forEach(track => track.stop()); return false; }
        this.localStream = stream;
        if (this.elements.localVideo) {
            this.elements.localVideo.srcObject = stream;
            this.elements.localVideo.muted = true;
        }
        this.updatePrimaryVideo();
        return true;
    }

    createPeerConnection(call = this.currentCall) {
        const peer = this.makePeer(this.config);
        if (!this.isCurrent(call)) { peer.close(); return null; }
        this.peerConnection = peer;
        peer.onicecandidate = event => {
            if (!this.isCurrent(call) || this.peerConnection !== peer || !event.candidate?.candidate) return;
            const candidate = event.candidate.toJSON ? event.candidate.toJSON() : event.candidate;
            if (call.localIce.length < 128) call.localIce.push(candidate);
            this.flushLocalIce(call);
        };
        peer.ontrack = event => {
            if (!this.isCurrent(call) || this.peerConnection !== peer) return;
            if (!this.remoteStream) this.remoteStream = this.makeStream();
            const tracks = event.streams?.[0]?.getTracks() || [event.track];
            for (const track of tracks) {
                if (!this.remoteStream.getTracks().some(existing => existing.id === track.id)) this.remoteStream.addTrack(track);
            }
            this.updatePrimaryVideo();
            this.addRemoteParticipant();
        };
        peer.onconnectionstatechange = () => {
            if (!this.isCurrent(call) || this.peerConnection !== peer) return;
            if (peer.connectionState === 'connected') this.markConnected(call);
            else if (['failed', 'closed'].includes(peer.connectionState)) this.fail(call, new Error('Kết nối cuộc gọi thất bại'));
            else if (peer.connectionState === 'disconnected') {
                this.isCallActive = false;
                this.setStatus('Kết nối bị gián đoạn...');
                this.deadline(call, 10000, 'Cuộc gọi đã mất kết nối');
            } else if (peer.connectionState === 'connecting') this.setStatus('Đang kết nối...');
        };
        return peer;
    }

    addLocalTracks(call, peer) {
        for (const track of this.localStream.getTracks()) {
            const sender = peer.addTrack(track, this.localStream);
            if (track.kind === 'video') call.videoSender = sender;
        }
        // Negotiate a video lane even for voice calls so screen share can replace a null track.
        if (!call.videoSender && peer.addTransceiver) call.videoSender = peer.addTransceiver('video', { direction: 'sendrecv' }).sender;
    }

    flushLocalIce(call) {
        if (!this.isCurrent(call) || !call.signalReady || !call.localDescriptionReady || call.awaitingAnswer || call.flushingIce) return;
        call.flushingIce = true;
        call.iceFlush = (async () => {
            while (call.localIce.length && this.isCurrent(call)) {
                if (!await this.requestSignal(call, 'ice_candidate', { candidate: call.localIce.shift() })) return false;
            }
            return this.isCurrent(call);
        })().catch(error => {
            if (this.isCurrent(call)) this.fail(call, error);
            return false;
        }).finally(() => {
            call.flushingIce = false;
            call.iceFlush = null;
            if (this.isCurrent(call) && call.localIce.length) this.flushLocalIce(call);
        });
    }

    async handleIceCandidate(data) {
        if (!CallState.validSignal(data) || typeof data.candidate?.candidate !== 'string' || !data.candidate.candidate ||
            this.terminalCalls.has(this.key(data))) return;
        if (!this.matches(data)) {
            // Early ICE can precede its ring in tests/reordered delivery, but can never create a call.
            if (!this.currentCall && !this.disposed) {
                const key = this.key(data);
                const queue = this.earlyIce.get(key) || [];
                if (queue.length < 128) queue.push(data.candidate);
                this.earlyIce.set(key, queue);
                if (this.earlyIce.size > 8) this.earlyIce.delete(this.earlyIce.keys().next().value);
            }
            return;
        }
        const call = this.currentCall;
        const key = JSON.stringify(data.candidate);
        if (call.iceKeys.has(key) || call.remoteIce.length >= 128) return;
        call.iceKeys.add(key);
        call.remoteIce.push(data.candidate);
        await this.processQueuedCandidates(call);
    }

    async processQueuedCandidates(call = this.currentCall) {
        const peer = this.peerConnection;
        if (!this.isCurrent(call) || !peer?.remoteDescription || !call.remoteDescriptionReady || call.drainingIce) return;
        call.drainingIce = true;
        try {
            while (this.isCurrent(call) && this.peerConnection === peer && call.remoteDescriptionReady && call.remoteIce.length) {
                const candidate = call.remoteIce.shift();
                try { await peer.addIceCandidate(candidate); }
                catch (error) { if (this.isCurrent(call)) this.notify(`ICE không khả dụng: ${error.message}`); }
            }
        } finally { call.drainingIce = false; }
    }

    async handleCallAnswered(data) {
        if (!this.matches(data) || data.answer?.type !== 'answer' || !this.currentCall.awaitingAnswer) return false;
        const call = this.currentCall;
        if (!call.pendingAnswer) call.pendingAnswer = data.answer;
        return this.applyPendingAnswer(call);
    }

    async applyPendingAnswer(call) {
        const peer = this.peerConnection;
        if (!this.isCurrent(call) || !call.pendingAnswer || !call.localDescriptionReady || call.applyingAnswer ||
            peer?.signalingState !== 'have-local-offer') return false;
        call.applyingAnswer = true;
        try {
            call.remoteDescriptionReady = false;
            await peer.setRemoteDescription(call.pendingAnswer);
            if (!this.isCurrent(call)) return false;
            call.pendingAnswer = null;
            call.awaitingAnswer = false;
            call.accepted = true;
            call.signalReady = true; // An authenticated answer also proves the server registered this call.
            call.remoteDescriptionReady = true;
            call.phase = 'connecting';
            this.hideIncomingModal();
            this.showActiveView();
            this.setStatus('Đang kết nối...');
            this.flushLocalIce(call);
            await this.processQueuedCandidates(call);
            this.deadline(call, 20000, 'Không thể thiết lập kết nối cuộc gọi');
            this.markConnected(call);
            return true;
        } catch (error) { return this.fail(call, error); }
        finally { call.applyingAnswer = false; }
    }

    markConnected(call) {
        if (!this.isCurrent(call) || !call.accepted || this.peerConnection?.connectionState !== 'connected') return;
        this.clearTimer(call.timer);
        call.phase = 'active';
        this.isCallActive = true;
        this.hideIncomingModal();
        this.showActiveView();
        this.setStatus('Đã kết nối', false);
        this.startDuration(call);
        this.updateMediaUI();
        this.broadcastMediaStatus();
    }

    handleCallEnded(data) {
        const current = this.matches(data);
        this.rememberTerminal(data);
        if (current) this.endCall(true);
    }
    handleCallRejected(data) {
        const current = this.matches(data);
        this.rememberTerminal(data);
        if (current) { this.notify('Cuộc gọi đã bị từ chối'); this.endCall(true); }
    }
    handleSignalError(data) {
        const call = this.currentCall;
        if (call?.call_id === data.call_id) this.fail(call, new Error(data.message || 'Máy chủ từ chối cuộc gọi'));
    }
    handleSocketDisconnected() {
        if (this.currentCall) this.notify('Cuộc gọi kết thúc do mất kết nối chat');
        this.endCall(true);
    }
    handleSocketConnected() { this.app.updateCallAvailability?.(); }

    async handleCallResume(data) {
        if (!this.matches(data) || !this.currentCall.accepted) return false;
        return this.renegotiate(this.currentCall, { iceRestart: true });
    }
    async renegotiate(call, options = {}) {
        const peer = this.peerConnection;
        if (!this.isCurrent(call) || !call.accepted || call.awaitingAnswer || call.processingOffer ||
            call.negotiating || peer?.signalingState !== 'stable') return false;
        call.negotiating = true;
        call.awaitingAnswer = true;
        call.localDescriptionReady = false;
        try {
            const offer = await peer.createOffer(options);
            if (!this.isCurrent(call)) return false;
            await peer.setLocalDescription(offer);
            if (!this.isCurrent(call)) return false;
            call.localDescriptionReady = true;
            const result = await this.requestSignal(call, 'call_user', {
                offer: peer.localDescription || offer, isVideo: call.isVideo || this.isSharingScreen, isResume: true
            });
            if (!result) return false;
            this.flushLocalIce(call);
            await this.applyPendingAnswer(call);
            return true;
        } catch (error) { return this.fail(call, error); }
        finally { call.negotiating = false; }
    }

    async toggleScreenShare() {
        return this.isSharingScreen ? this.stopScreenShare() : this.startScreenShare();
    }
    async startScreenShare() {
        const call = this.currentCall;
        if (!this.isCallActive || !call?.accepted || call.screenOperation || this.isSharingScreen) return false;
        if (!this.mediaDevices?.getDisplayMedia) { this.setUIFeedback('Trình duyệt không hỗ trợ chia sẻ màn hình'); return false; }
        call.screenOperation = true;
        this.updateMediaUI();
        let stream;
        try {
            stream = await this.mediaDevices.getDisplayMedia({ video: true, audio: false });
            if (!this.isCurrent(call)) { stream.getTracks().forEach(track => track.stop()); return false; }
            const track = stream.getVideoTracks()[0];
            if (!track || !call.videoSender) throw new Error('Không thể chia sẻ màn hình trong cuộc gọi này');
            await call.videoSender.replaceTrack(track);
            if (!this.isCurrent(call)) { stream.getTracks().forEach(item => item.stop()); return false; }
            this.screenStream = stream;
            this.isSharingScreen = true;
            track.onended = () => { if (this.isCurrent(call)) this.stopScreenShare(); };
            this.elements.btnShare?.classList.add('sharing');
            if (this.elements.localVideo) this.elements.localVideo.srcObject = stream;
            this.updatePrimaryVideo();
            this.socket.emit('stream_status', { ...this.scope(call), is_streaming: true });
            return true;
        } catch (error) {
            stream?.getTracks().forEach(track => track.stop());
            if (this.isCurrent(call)) this.reportUIError(error.name === 'NotAllowedError' ?
                'Chưa chia sẻ màn hình. Hãy thử lại và cho phép chia sẻ' : 'Không thể chia sẻ màn hình', error);
            return false;
        } finally {
            call.screenOperation = false;
            if (this.isCurrent(call)) this.updateMediaUI();
        }
    }
    async stopScreenShare() {
        const call = this.currentCall;
        if (!call || !this.isSharingScreen || call.screenOperation) return false;
        call.screenOperation = true;
        this.updateMediaUI();
        const stream = this.screenStream;
        try {
            await call.videoSender.replaceTrack(this.localStream?.getVideoTracks()[0] || null);
            if (!this.isCurrent(call)) return false;
            stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
            this.screenStream = null;
            this.isSharingScreen = false;
            this.elements.btnShare?.classList.remove('sharing');
            if (this.elements.localVideo) this.elements.localVideo.srcObject = this.localStream;
            this.updatePrimaryVideo();
            this.socket.emit('stream_status', { ...this.scope(call), is_streaming: false });
            return true;
        } catch (error) { return this.fail(call, error); }
        finally {
            call.screenOperation = false;
            if (this.isCurrent(call)) this.updateMediaUI();
        }
    }
    watchStream() {
        this.notify('Xem livestream/nhóm chưa được hỗ trợ. Chia sẻ màn hình chỉ trong cuộc gọi một-một.');
        return false;
    }
    handleStreamRequest() { return this.watchStream(); }
    handleStreamStatus(data) {
        if (!this.matches(data) || !this.currentCall.accepted || typeof data.is_streaming !== 'boolean') return;
        this.currentCall.remoteSharingScreen = data.is_streaming;
        this.updateMediaUI();
    }

    broadcastMediaStatus() {
        const call = this.currentCall;
        if (!call?.accepted || !this.localStream) return;
        call.mediaRevision = (call.mediaRevision || 0) + 1;
        for (const [kind, type] of [['audio', 'mic'], ['video', 'cam']]) {
            const track = this.localStream.getTracks().find(item => item.kind === kind);
            if (track) this.socket?.emit('media_status', { ...this.scope(call), type, enabled: track.enabled, revision: call.mediaRevision });
        }
    }
    handleMediaStatus(data) {
        if (!this.matches(data) || !this.currentCall.accepted || typeof data.enabled !== 'boolean' ||
            !['mic', 'cam'].includes(data.type)) return;
        const call = this.currentCall;
        const revision = Number.isSafeInteger(data.revision) && data.revision > 0 ? data.revision : null;
        call.remoteMediaRevisions ||= {};
        const previous = call.remoteMediaRevisions[data.type];
        if (revision === null && previous !== undefined) return;
        if (revision !== null && revision <= (previous ?? -1)) return;
        if (revision !== null) call.remoteMediaRevisions[data.type] = revision;
        call.remoteMedia = { ...call.remoteMedia, [data.type]: data.enabled };
        this.updateMediaUI();
    }

    async sendCallChatMessage() {
        const call = this.currentCall;
        const input = document.getElementById('callChatInput');
        const text = input?.value.trim();
        if (!this.isCallActive || !call?.accepted || call.sendingChat || !text) return false;
        call.sendingChat = true;
        this.updateChatUI();
        const timestamp = Date.now();
        try {
            if (!await this.requestSignal(call, 'call_chat_message', { text, timestamp })) return false;
            if (input.value.trim() === text) input.value = '';
            this.addCallChatMessage({ sender_name: this.app.userName, text, timestamp, own: true });
            return true;
        } catch (error) { if (this.isCurrent(call)) this.reportUIError('Không thể gửi tin nhắn trong cuộc gọi', error); return false; }
        finally {
            call.sendingChat = false;
            if (this.isCurrent(call)) this.updateChatUI();
        }
    }
    handleCallChatMessage(data) {
        if (!this.matches(data) || !this.currentCall.accepted || String(data.sender_id) === String(this.app.userId)) return;
        this.addCallChatMessage(data);
    }
    addCallChatMessage(message) {
        const container = document.getElementById('callChatMessages');
        if (!container) return;
        container.querySelector('.call-chat-empty')?.remove();
        const row = createNode('div', `call-chat-message${message.own ? ' own' : ''}`);
        row.append(createNode('span', 'sender', message.sender_name), createNode('span', 'text', message.text),
            createNode('span', 'time', this.app.ui.formatTime(message.timestamp || Date.now())));
        container.appendChild(row);
        container.scrollTop = container.scrollHeight;
    }

    endCall(isRemote = false) {
        const call = this.state.end(); // Invalidate before any callbacks, sends, or track cleanup.
        if (call) {
            this.clearTimer(call.timer);
            this.rememberTerminal(call);
            if (!isRemote && (call.offered || call === this.pendingCall)) this.socket?.emit('end_call', this.scope(call));
            call.remoteIce.length = 0;
            call.localIce.length = 0;
        }
        this.stopDuration();
        this.removeListeners(this.callUIListeners);
        for (const remove of this.mediaListeners.values()) remove();
        this.mediaListeners.clear();
        this.browserOperations.clear();
        const ownedVideo = this.elements.remoteVideo;
        this.removeRemoteParticipant();
        this.releaseRemoteAudio();
        for (const video of [this.elements.localVideo, ownedVideo]) video?.pause?.();
        const peer = this.peerConnection;
        this.peerConnection = null;
        if (peer) {
            peer.onicecandidate = null;
            peer.ontrack = null;
            peer.onconnectionstatechange = null;
            peer.close();
        }
        for (const stream of new Set([this.localStream, this.remoteStream, this.screenStream])) {
            stream?.getTracks().forEach(track => {
                track.onended = null;
                track.onmute = null;
                track.onunmute = null;
                track.stop();
            });
        }
        this.localStream = null;
        this.remoteStream = null;
        this.screenStream = null;
        this.pendingCall = null;
        this.isCallActive = false;
        this.isSharingScreen = false;
        this.earlyIce.clear();
        if (this.elements.localVideo) this.elements.localVideo.srcObject = null;
        if (this.elements.remoteVideo) this.elements.remoteVideo.srcObject = null;
        this.elements.btnShare?.classList.remove('sharing');
        this.hideIncomingModal();
        this.toggleCallChat(false, false);
        this.isGridView = false;
        this.focusedParticipant = 'remote';
        this.audioNeedsGesture = false;
        this.elements.view?.classList.remove('grid-mode', 'chat-open');
        document.getElementById('callChatMessages')?.replaceChildren();
        const input = this.elements.chatInput || document.getElementById('callChatInput');
        if (input) input.value = '';
        this.setUIFeedback('');
        this.setStatus('', false);
        this.updateMediaUI();
        this.closeOverlay();
    }
    dispose() {
        this.endCall();
        this.disposed = true;
        this.removeListeners(this.uiListeners);
        this.uiInitialized = false;
    }

    initUI() {
        if (this.uiInitialized || this.disposed) return;
        this.uiInitialized = true;
        const ids = {
            btnShare: 'btnShareScreen', btnEnd: 'btnEndCall', localVideo: 'localVideo', remoteVideo: 'remoteVideo',
            overlay: 'callOverlay', view: 'activeCallView', status: 'callStatus', incomingModal: 'incomingCallModal',
            incomingName: 'incomingName', incomingAvatar: 'incomingAvatar', incomingType: 'incomingCallType',
            channelName: 'callChannelName', callerInfo: 'callerInfo', remoteNameTag: 'remoteNameTag',
            participantStrip: 'participantStrip', localParticipant: 'localParticipant', localMicStatus: 'localMicStatus',
            localPlaceholder: 'localPlaceholder', localMediaState: 'localMediaState',
            remotePlaceholder: 'remotePlaceholder', remoteMediaState: 'remoteMediaState',
            btnAnswer: 'btnAcceptCall', btnReject: 'btnRejectCall', btnMic: 'btnToggleMic', btnCam: 'btnToggleCam',
            btnGridView: 'btnGridView', btnChat: 'btnToggleChat', btnCloseChat: 'btnCloseCallChat',
            btnSendChat: 'btnSendCallChat', chatInput: 'callChatInput', chatPanel: 'callChatPanel',
            btnFullscreen: 'btnFullscreen', btnPiP: 'btnPiP', btnPlayAudio: 'btnPlayCallAudio',
            duration: 'callDuration', feedback: 'callUIFeedback', liveIndicator: 'liveIndicator', qualityBadge: 'qualityBadge'
        };
        for (const [key, id] of Object.entries(ids)) this.elements[key] = document.getElementById(id);
        const actions = {
            btnAnswer: () => this.acceptCall(), btnReject: () => this.rejectCall(), btnEnd: () => this.endCall(),
            btnShare: () => this.toggleScreenShare(), btnGridView: () => this.toggleGridView(),
            btnMic: () => this.toggleMedia('audio'), btnCam: () => this.toggleMedia('video'),
            btnChat: () => this.toggleCallChat(), btnCloseChat: () => this.toggleCallChat(false),
            btnSendChat: () => this.sendCallChatMessage(), btnFullscreen: () => this.toggleFullscreen(),
            btnPiP: () => this.togglePictureInPicture(), btnPlayAudio: () => this.playRemoteAudio()
        };
        for (const [key, action] of Object.entries(actions)) this.listen(this.elements[key], 'click', action);
        this.listen(this.elements.chatInput, 'keydown', event => {
            if (shouldSendOnEnter(event)) { event.preventDefault(); this.sendCallChatMessage(); }
        });
        this.listen(this.elements.chatInput, 'input', () => this.updateChatUI());
        const local = this.elements.localParticipant;
        if (local) {
            local.setAttribute('role', 'button');
            local.setAttribute('aria-controls', 'primaryStream');
            const focus = () => this.focusStream(this.screenStream || this.localStream, 'Bạn', true);
            this.listen(local, 'click', focus);
            this.listen(local, 'keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); focus(); }
            });
        }
        this.elements.btnGridView?.setAttribute('aria-controls', 'participantStrip');
        this.elements.btnChat?.setAttribute('aria-controls', 'callChatPanel');
        this.elements.btnFullscreen?.setAttribute('aria-controls', 'callOverlay');
        this.elements.overlay?.setAttribute('aria-hidden', 'true');
        this.elements.chatPanel?.setAttribute('aria-hidden', 'true');
        for (const id of ['btnPopout', 'btnMoreOptions']) {
            const button = document.getElementById(id);
            if (button) {
                this.setControl(button, 'Chức năng chưa được hỗ trợ', { disabled: true, state: 'unavailable' });
                button.hidden = true;
            }
        }
        if (this.elements.duration) {
            this.elements.duration.setAttribute('role', 'timer');
            this.elements.duration.setAttribute('aria-live', 'off');
        }
        this.stopDuration();
        this.updateMediaUI();
    }

    listen(target, type, handler, group = this.uiListeners) {
        if (!target?.addEventListener) return;
        target.addEventListener(type, handler);
        group.push(() => target.removeEventListener?.(type, handler));
    }
    removeListeners(group) { for (const remove of group.splice(0)) remove(); }
    setControl(button, label, { pressed, disabled = false, busy = false, state = '', description = '', icon } = {}) {
        if (!button) return;
        button.type = 'button';
        button.disabled = disabled;
        button.setAttribute?.('aria-label', label);
        button.setAttribute?.('aria-disabled', String(disabled));
        button.setAttribute?.('aria-busy', String(busy));
        if (pressed !== undefined) button.setAttribute?.('aria-pressed', String(pressed));
        if (description) button.setAttribute?.('aria-description', description);
        else button.removeAttribute?.('aria-description');
        if (button.dataset) button.dataset.state = state;
        button.title = description ? `${label} — ${description}` : label;
        const text = button.querySelector?.('.control-label');
        if (text) text.textContent = label;
        const symbol = button.querySelector?.('i');
        if (symbol) {
            if (icon) symbol.className = icon;
            symbol.setAttribute('aria-hidden', 'true');
        }
    }
    setUIFeedback(text) {
        if (this.elements.feedback) {
            this.elements.feedback.textContent = text;
            this.elements.feedback.hidden = !text;
        }
    }
    reportUIError(action, error) {
        this.lastUIError = error;
        const detail = error?.message || error?.name;
        const message = detail ? `${action}: ${detail}` : action;
        this.setUIFeedback(message);
        this.notify(message);
    }
    liveTrack(stream, kind) { return stream?.getTracks().find(track => track.kind === kind && track.readyState !== 'ended'); }
    hasVideo(stream) { return stream?.getVideoTracks().some(track => track.enabled && !track.muted && track.readyState !== 'ended') || false; }
    remoteHasVideo() {
        const call = this.currentCall;
        return this.hasVideo(this.remoteStream) && !!(call?.remoteSharingScreen ||
            (call?.isVideo && call.remoteMedia?.cam !== false));
    }
    mediaText(local = false) {
        const call = this.currentCall;
        if (!call) return 'Chưa có cuộc gọi';
        const sharing = local ? this.isSharingScreen : call.remoteSharingScreen;
        const stream = local ? this.screenStream || this.localStream : this.remoteStream;
        const visible = local ? this.hasVideo(stream) : this.remoteHasVideo();
        if (sharing) return visible ? 'Đang chia sẻ màn hình' : 'Đang chờ hình ảnh màn hình';
        if (!call.isVideo) return 'Cuộc gọi thoại';
        if (local && !this.localStream) return 'Đang chờ camera';
        if (!local && !this.remoteStream) return 'Đang chờ người tham gia';
        if (!local && call.remoteMedia?.cam === false) return 'Camera đã tắt';
        if (visible) return 'Camera đang bật';
        const track = this.liveTrack(stream, 'video');
        return track?.enabled && track.muted ? 'Video đang tạm dừng' : 'Camera đã tắt';
    }
    updateMediaUI() {
        const call = this.currentCall;
        this.syncMediaListeners();
        const mic = this.liveTrack(this.localStream, 'audio');
        const cam = this.liveTrack(this.localStream, 'video');
        const micOn = !!mic?.enabled;
        const camOn = !!cam?.enabled;
        this.setControl(this.elements.btnMic, micOn ? 'Tắt micro' : 'Bật micro', {
            pressed: micOn, disabled: !call?.accepted || !mic, state: micOn ? 'on' : 'off',
            description: !mic ? 'Micro chưa sẵn sàng' : mic.muted ? 'Micro đang tạm dừng' : micOn ? 'Nhấn để tắt micro' : 'Nhấn để bật micro',
            icon: micOn ? 'fas fa-microphone' : 'fas fa-microphone-slash'
        });
        this.setControl(this.elements.btnCam, camOn ? 'Tắt camera' : 'Bật camera', {
            pressed: camOn, disabled: !call?.accepted || !cam, state: camOn ? 'on' : 'off',
            description: !cam ? (call?.isVideo ? 'Camera chưa sẵn sàng' : 'Cuộc gọi thoại không dùng camera') :
                this.isSharingScreen ? 'Màn hình đang được gửi thay cho camera' : camOn ? 'Nhấn để tắt camera' : 'Nhấn để bật camera',
            icon: camOn ? 'fas fa-video' : 'fas fa-video-slash'
        });
        this.elements.btnMic?.classList.toggle('active', !micOn);
        this.elements.btnCam?.classList.toggle('active', !camOn);
        const canShare = !!this.mediaDevices?.getDisplayMedia;
        this.setControl(this.elements.btnShare, this.isSharingScreen ? 'Dừng chia sẻ' : 'Chia sẻ màn hình', {
            pressed: this.isSharingScreen, disabled: !this.isCallActive || !call?.accepted || !canShare || !!call.screenOperation,
            busy: !!call?.screenOperation, state: call?.screenOperation ? 'pending' : this.isSharingScreen ? 'on' : 'off',
            description: !canShare ? 'Trình duyệt không hỗ trợ chia sẻ màn hình' : call?.screenOperation ? 'Đang xử lý chia sẻ màn hình' : ''
        });
        this.elements.btnShare?.classList.toggle('sharing', this.isSharingScreen);
        this.setMicStatus(this.elements.localMicStatus, !!mic?.enabled && !mic.muted, !mic ? 'Micro chưa sẵn sàng' :
            mic.muted ? 'Micro đang tạm dừng' : micOn ? 'Micro đang bật' : 'Micro đã tắt');
        const localStream = this.screenStream || this.localStream;
        this.presentVideo(this.elements.localVideo, localStream, this.hasVideo(localStream));
        this.presentPlaceholder(this.elements.localPlaceholder, !this.hasVideo(localStream));
        if (this.elements.localMediaState) this.elements.localMediaState.textContent = this.mediaText(true);
        if (this.elements.localParticipant) {
            const local = this.elements.localParticipant;
            local.tabIndex = localStream ? 0 : -1;
            local.setAttribute('aria-disabled', String(!localStream));
            local.setAttribute('aria-label', `Xem Bạn — ${this.mediaText(true)}`);
            local.setAttribute('aria-pressed', String(!this.isGridView && this.focusedParticipant === 'local'));
        }
        if (call?.accepted || this.remoteStream) this.addRemoteParticipant();
        const localFocus = this.focusedParticipant === 'local';
        const primaryStream = localFocus ? localStream : this.remoteStream;
        const primaryVideo = localFocus ? this.hasVideo(localStream) : this.remoteHasVideo();
        this.presentVideo(this.elements.remoteVideo, primaryStream, primaryVideo);
        this.presentPlaceholder(this.elements.remotePlaceholder, !primaryVideo);
        if (this.elements.remoteMediaState) this.elements.remoteMediaState.textContent = this.mediaText(localFocus);
        if (this.elements.remoteNameTag) this.elements.remoteNameTag.textContent = localFocus ?
            (this.isSharingScreen ? 'Màn hình của bạn' : 'Bạn') :
            `${call?.peerName || 'Người tham gia'}${call?.remoteSharingScreen ? ' · Màn hình' : ''}`;
        this.bindRemoteAudio();
        this.setControl(this.elements.btnGridView, this.isGridView ? 'Xem tập trung' : 'Xem dạng lưới', {
            pressed: this.isGridView, disabled: !call?.accepted, state: this.isGridView ? 'grid' : 'focus',
            description: this.isGridView ? 'Hai người tham gia đang hiển thị trong lưới' : 'Nhấn để xem cả hai người tham gia'
        });
        this.elements.btnGridView?.classList.toggle('active', this.isGridView);
        this.updateChatUI();
        this.updateBrowserControls();
        this.updateHeader();
    }
    setMicStatus(element, enabled, text) {
        if (!element) return;
        element.classList.toggle('muted', !enabled);
        element.setAttribute('aria-label', text);
        element.title = text;
        const icon = element.querySelector('i');
        if (icon) { icon.className = enabled ? 'fas fa-microphone' : 'fas fa-microphone-slash'; icon.setAttribute('aria-hidden', 'true'); }
    }
    syncMediaListeners() {
        const call = this.currentCall;
        const targets = new Map();
        for (const stream of new Set([this.localStream, this.remoteStream, this.screenStream])) {
            if (!stream) continue;
            targets.set(stream, ['addtrack', 'removetrack']);
            for (const track of stream.getTracks()) targets.set(track, ['mute', 'unmute', 'ended']);
        }
        for (const [target, remove] of this.mediaListeners) {
            if (!targets.has(target) || !call) { remove(); this.mediaListeners.delete(target); }
        }
        if (!call) return;
        for (const [target, events] of targets) {
            if (this.mediaListeners.has(target) || !target.addEventListener) continue;
            const listeners = [];
            for (const type of events) this.listen(target, type, () => {
                if (this.isCurrent(call)) this.updateMediaUI();
            }, listeners);
            this.mediaListeners.set(target, () => this.removeListeners(listeners));
        }
    }
    presentPlaceholder(element, visible) {
        if (!element) return;
        element.hidden = !visible;
        element.style.display = visible ? 'flex' : 'none';
    }
    presentVideo(video, stream, visible) {
        if (!video) return;
        const changed = video.srcObject !== stream;
        video.muted = true; // Exactly one separate remote audio sink survives primary/local/grid switches.
        video.controls = false;
        video.tabIndex = -1;
        video.setAttribute?.('aria-hidden', 'true');
        video.style.display = visible ? 'block' : 'none';
        if (changed) {
            video.srcObject = stream;
            const call = this.currentCall;
            if (stream && video.play) {
                try {
                    video.play()?.catch(error => {
                        if (this.isCurrent(call) && video.srcObject === stream) this.reportUIError('Không thể phát video', error);
                    });
                } catch (error) { if (this.isCurrent(call)) this.reportUIError('Không thể phát video', error); }
            }
        }
    }
    bindRemoteAudio() {
        const call = this.currentCall;
        if (!call || !this.remoteStream || !this.liveTrack(this.remoteStream, 'audio')) return;
        let audio = this.elements.remoteAudio;
        if (!audio) {
            if (!this.elements.overlay?.appendChild) return;
            audio = createNode('audio');
            audio.id = 'callRemoteAudio';
            audio.autoplay = true;
            audio.hidden = true;
            audio.setAttribute('aria-hidden', 'true');
            this.elements.overlay.appendChild(audio);
            this.elements.remoteAudio = audio;
        }
        const signature = this.remoteStream.getAudioTracks().map(track => track.id).join(',');
        if (audio.srcObject !== this.remoteStream || this.remoteAudioSignature !== signature) {
            audio.srcObject = this.remoteStream;
            audio.muted = false;
            this.remoteAudioSignature = signature;
            this.playRemoteAudio(call);
        }
    }
    async playRemoteAudio(call = this.currentCall) {
        const audio = this.elements.remoteAudio;
        if (!this.isCurrent(call) || !audio?.srcObject || this.audioPlay) return false;
        const operation = { call, audio };
        this.audioPlay = operation;
        this.updateBrowserControls();
        try {
            await audio.play();
            if (!this.isCurrent(call) || this.elements.remoteAudio !== audio) return false;
            this.audioNeedsGesture = false;
            if (this.elements.feedback?.textContent.startsWith('Âm thanh chưa phát.')) this.setUIFeedback('');
            return true;
        } catch (error) {
            if (this.isCurrent(call) && this.elements.remoteAudio === audio) {
                this.audioNeedsGesture = true;
                this.reportUIError('Âm thanh chưa phát. Nhấn “Bật âm thanh” để thử lại', error);
            }
            return false;
        } finally {
            if (this.audioPlay === operation) { this.audioPlay = null; this.updateBrowserControls(); }
        }
    }
    releaseRemoteAudio() {
        this.audioPlay = null;
        const audio = this.elements.remoteAudio;
        if (audio) { audio.pause(); audio.srcObject = null; audio.remove(); }
        this.elements.remoteAudio = null;
        this.remoteAudioSignature = null;
    }
    toggleMedia(kind) {
        const track = this.liveTrack(this.localStream, kind);
        if (!this.currentCall?.accepted || !track) return false;
        track.enabled = !track.enabled;
        this.updateMediaUI();
        this.broadcastMediaStatus();
        return true;
    }
    updateChatUI() {
        const call = this.currentCall;
        const open = this.elements.chatPanel?.classList.contains('active') || false;
        this.setControl(this.elements.btnChat, open ? 'Đóng trò chuyện' : 'Trò chuyện', {
            pressed: open, disabled: !call?.accepted, state: open ? 'open' : 'closed'
        });
        this.elements.btnChat?.setAttribute('aria-expanded', String(open));
        this.elements.btnChat?.classList.toggle('active', open);
        this.setControl(this.elements.btnCloseChat, 'Đóng trò chuyện');
        this.setControl(this.elements.btnSendChat, call?.sendingChat ? 'Đang gửi' : 'Gửi tin nhắn', {
            disabled: !this.isCallActive || !call?.accepted || !!call.sendingChat || !this.elements.chatInput?.value.trim(),
            busy: !!call?.sendingChat, state: call?.sendingChat ? 'pending' : 'ready'
        });
        if (this.elements.chatInput) this.elements.chatInput.disabled = !this.isCallActive || !call?.accepted;
    }
    toggleCallChat(force = null, moveFocus = true) {
        const panel = this.elements.chatPanel || document.getElementById('callChatPanel');
        if (!panel) return false;
        const open = force ?? !panel.classList.contains('active');
        if (open && !this.currentCall?.accepted) return false;
        if (open && this.isGridView) this.toggleGridView(false);
        const restoreFocus = !open && panel.contains?.(document.activeElement);
        panel.classList.toggle('active', open);
        panel.hidden = !open;
        panel.setAttribute?.('aria-hidden', String(!open));
        this.elements.view?.classList.toggle('chat-open', open);
        this.updateChatUI();
        if (moveFocus && open) (this.elements.chatInput?.disabled ? this.elements.btnCloseChat : this.elements.chatInput)?.focus();
        else if (moveFocus && restoreFocus && this.overlayOpen) this.elements.btnChat?.focus();
        return open;
    }
    toggleGridView(force = null) {
        if (force !== false && !this.currentCall?.accepted) return false;
        this.isGridView = force ?? !this.isGridView;
        if (this.isGridView) {
            const chatFocused = this.elements.chatPanel?.contains(document.activeElement);
            this.toggleCallChat(false, false);
            if (chatFocused) this.elements.btnGridView?.focus();
        }
        this.elements.view?.classList.toggle('grid-mode', this.isGridView);
        this.updateMediaUI();
        return this.isGridView;
    }
    focusStream(stream, _name, local = false) {
        if (!this.currentCall?.accepted || !stream) return false;
        this.focusedParticipant = local ? 'local' : 'remote';
        if (this.isGridView) this.toggleGridView(false);
        else this.updateMediaUI();
        return true;
    }
    updatePrimaryVideo() { this.updateMediaUI(); }
    addRemoteParticipant() {
        const strip = this.elements.participantStrip;
        if (!strip) return;
        let item = this.elements.remoteParticipant;
        if (!item) {
            item = createNode('div', 'participant-item');
            item.id = 'remoteParticipant';
            item.setAttribute('role', 'button');
            item.setAttribute('aria-controls', 'primaryStream');
            const video = createNode('video');
            video.id = 'remoteParticipantVideo';
            video.autoplay = true;
            video.playsInline = true;
            const placeholder = createNode('div', 'participant-placeholder');
            placeholder.id = 'remoteParticipantPlaceholder';
            const icon = createNode('i', 'fas fa-user');
            icon.setAttribute('aria-hidden', 'true');
            const text = createNode('span', 'participant-media-state');
            text.id = 'remoteParticipantMediaState';
            placeholder.append(icon, text);
            const status = createNode('div', 'participant-status');
            status.id = 'remoteMicStatus';
            status.appendChild(createNode('i', 'fas fa-microphone'));
            item.append(video, placeholder, createNode('div', 'participant-name'), status);
            strip.appendChild(item);
            this.elements.remoteParticipant = item;
            const focus = () => this.focusStream(this.remoteStream, this.currentCall?.peerName);
            this.listen(item, 'click', focus, this.participantListeners);
            this.listen(item, 'keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); focus(); }
            }, this.participantListeners);
        }
        const call = this.currentCall;
        const name = call?.peerName || 'Người tham gia';
        const text = this.mediaText();
        item.classList.toggle('connecting', !this.remoteStream);
        item.tabIndex = this.remoteStream ? 0 : -1;
        item.setAttribute('aria-disabled', String(!this.remoteStream));
        item.setAttribute('aria-label', `Xem ${name} — ${text}`);
        item.setAttribute('aria-pressed', String(!this.isGridView && this.focusedParticipant === 'remote'));
        item.querySelector('.participant-name').textContent = name;
        item.querySelector('.participant-media-state').textContent = text;
        this.presentVideo(item.querySelector('video'), this.remoteStream, this.remoteHasVideo());
        this.presentPlaceholder(item.querySelector('.participant-placeholder'), !this.remoteHasVideo());
        const mic = this.liveTrack(this.remoteStream, 'audio');
        const muted = call?.remoteMedia?.mic === false;
        this.setMicStatus(item.querySelector('.participant-status'), !!mic?.enabled && !mic.muted && !muted,
            muted ? 'Micro đã tắt' : !mic ? 'Đang chờ âm thanh' : mic.muted ? 'Âm thanh đang tạm dừng' : 'Đang nhận âm thanh');
    }
    addRemoteParticipantPlaceholder(text) {
        this.addRemoteParticipant();
        const item = this.elements.remoteParticipant;
        if (item && !this.remoteStream) item.querySelector('.participant-media-state').textContent = text;
    }
    removeRemoteParticipant() {
        this.removeListeners(this.participantListeners);
        const item = this.elements.remoteParticipant || document.getElementById('remoteParticipant');
        const video = item?.querySelector('video');
        if (video) { video.pause(); video.srcObject = null; }
        item?.remove();
        this.elements.remoteParticipant = null;
    }

    showOverlay() {
        const overlay = this.elements.overlay;
        if (!overlay || this.overlayOpen) return;
        this.overlayOpen = true;
        this.returnFocus = document.activeElement;
        this.savedBodyOverflow = document.body?.style.overflow;
        if (document.body) document.body.style.overflow = 'hidden';
        overlay.classList.add('active');
        overlay.hidden = false;
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-hidden', 'false');
        overlay.tabIndex = -1;
        this.listen(overlay, 'keydown', event => this.manageCallFocus(event), this.callUIListeners);
        this.listen(document, 'focusin', event => {
            if (this.overlayOpen && !overlay.contains(event.target)) this.focusCallControl();
        }, this.callUIListeners);
        this.listen(document, 'fullscreenchange', () => this.updateBrowserControls(), this.callUIListeners);
        for (const event of ['enterpictureinpicture', 'leavepictureinpicture', 'loadedmetadata', 'emptied']) {
            this.listen(this.elements.remoteVideo, event, () => this.updateBrowserControls(), this.callUIListeners);
        }
        overlay.focus({ preventScroll: true });
    }
    focusCallControl() {
        const incoming = this.elements.incomingModal?.classList.contains('active');
        const button = incoming ? (this.elements.btnAnswer?.hidden ? this.elements.btnReject : this.elements.btnAnswer) : this.elements.btnEnd;
        (button || this.elements.overlay)?.focus({ preventScroll: true });
    }
    manageCallFocus(event) {
        if (!this.overlayOpen) return;
        if (event.key === 'Escape' && this.elements.chatPanel?.classList.contains('active')) {
            event.preventDefault();
            event.stopPropagation();
            this.toggleCallChat(false);
            return;
        }
        if (event.key !== 'Tab') return;
        const overlay = this.elements.overlay;
        const focusable = Array.from(overlay.querySelectorAll('button, input, textarea, select, a[href], [tabindex]')).filter(node =>
            !node.disabled && node.tabIndex >= 0 && !node.closest('[hidden], [aria-hidden="true"]') && node.getClientRects().length);
        const active = document.activeElement;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!first) { event.preventDefault(); overlay.focus(); }
        else if (!focusable.includes(active) || (event.shiftKey ? active === first : active === last)) {
            event.preventDefault();
            (event.shiftKey ? last : first).focus();
        }
    }
    closeOverlay() {
        const open = this.overlayOpen;
        this.overlayOpen = false;
        this.removeListeners(this.callUIListeners);
        this.exitBrowserViews();
        this.elements.overlay?.classList.remove('active');
        this.elements.overlay?.setAttribute?.('aria-hidden', 'true');
        if (this.elements.view) {
            this.elements.view.style.display = 'none';
            this.elements.view.hidden = true;
            this.elements.view.classList.remove('active');
        }
        if (!open) return;
        if (document.body && this.savedBodyOverflow !== undefined) document.body.style.overflow = this.savedBodyOverflow;
        const target = this.returnFocus?.isConnected && !this.returnFocus.disabled ? this.returnFocus : document.getElementById('messageInput');
        this.returnFocus = null;
        this.savedBodyOverflow = undefined;
        if (target && !target.disabled) target.focus({ preventScroll: true });
    }
    setStatus(text, visible = true) {
        if (this.elements.status) {
            this.elements.status.textContent = text;
            this.elements.status.style.display = visible ? 'flex' : 'none';
            this.elements.status.hidden = !visible;
        }
        this.updateMediaUI();
    }
    updateHeader() {
        const call = this.currentCall;
        if (this.elements.channelName) this.elements.channelName.textContent = call?.peerName || 'Cuộc gọi riêng tư';
        if (this.elements.callerInfo) this.elements.callerInfo.textContent = call ?
            `${call.isVideo ? 'Cuộc gọi video' : 'Cuộc gọi thoại'} · Một-một` : 'Cuộc gọi một-một';
        if (this.elements.qualityBadge) this.elements.qualityBadge.hidden = true; // No measured quality data.
        if (this.elements.liveIndicator) {
            this.elements.liveIndicator.textContent = this.isCallActive ? 'Đã kết nối' : call ? 'Đang kết nối' : 'Cuộc gọi';
            this.elements.liveIndicator.dataset.state = this.isCallActive ? 'active' : call?.phase || 'idle';
        }
        if (this.elements.status?.dataset) this.elements.status.dataset.state = this.isCallActive ? 'active' : call?.phase || 'idle';
        this.setControl(this.elements.btnEnd, 'Kết thúc cuộc gọi', { disabled: !call, state: call ? 'ready' : 'idle' });
    }
    showIncomingModal(data) { this.showRing(this.currentCall?.peerName || data.sender_name || 'Người dùng', true); }
    showOutgoingModal(name) { this.showRing(name, false); }
    showRing(name, incoming) {
        if (this.elements.incomingName) this.elements.incomingName.textContent = name;
        if (this.elements.incomingAvatar) this.elements.incomingAvatar.textContent = Array.from(String(name))[0] || '?';
        const type = this.currentCall?.isVideo ? 'video' : 'thoại';
        const title = this.elements.incomingType || this.elements.incomingModal?.querySelector('p');
        if (title) title.textContent = incoming ? `Cuộc gọi ${type} đến` : `Đang gọi ${type}…`;
        this.setControl(this.elements.btnAnswer, `Nhận cuộc gọi ${type}`, { disabled: !incoming });
        this.setControl(this.elements.btnReject, incoming ? 'Từ chối cuộc gọi' : 'Hủy cuộc gọi');
        if (this.elements.btnAnswer) { this.elements.btnAnswer.style.display = incoming ? 'inline-flex' : 'none'; this.elements.btnAnswer.hidden = !incoming; }
        if (this.elements.incomingModal) {
            this.elements.incomingModal.classList.add('active');
            this.elements.incomingModal.style.display = 'block';
            this.elements.incomingModal.hidden = false;
            this.elements.incomingModal.setAttribute('aria-hidden', 'false');
        }
        if (this.elements.view) { this.elements.view.style.display = 'none'; this.elements.view.hidden = true; this.elements.view.classList.remove('active'); }
        this.elements.overlay?.setAttribute('aria-labelledby', 'incomingName');
        this.elements.overlay?.setAttribute('aria-describedby', 'incomingCallType');
        this.setStatus('', false);
        (incoming ? this.elements.btnAnswer : this.elements.btnReject)?.focus({ preventScroll: true });
    }
    hideIncomingModal() {
        this.elements.incomingModal?.classList.remove('active');
        if (this.elements.incomingModal) {
            this.elements.incomingModal.style.display = 'none';
            this.elements.incomingModal.hidden = true;
            this.elements.incomingModal.setAttribute('aria-hidden', 'true');
        }
    }
    showActiveView() {
        const opening = !this.elements.view?.classList.contains('active');
        if (this.elements.view) {
            this.elements.view.style.display = 'flex';
            this.elements.view.hidden = false;
            this.elements.view.classList.add('active');
        }
        this.elements.overlay?.setAttribute('aria-labelledby', 'callChannelName');
        this.elements.overlay?.setAttribute('aria-describedby', 'callerInfo');
        this.updateMediaUI();
        if (opening) this.elements.btnEnd?.focus({ preventScroll: true });
    }

    startDuration(call) {
        if (!this.isCurrent(call) || !this.isCallActive) return;
        if (this.durationCall !== call) {
            this.stopDuration();
            this.durationCall = call;
            this.durationStartedAt = this.now();
        }
        this.renderDuration();
        if (this.durationTimer !== null) return;
        const tick = () => {
            if (!this.isCurrent(call) || this.durationCall !== call) return;
            this.durationTimer = null;
            this.renderDuration();
            this.durationTimer = this.setTimer(tick, 1000);
        };
        this.durationTimer = this.setTimer(tick, 1000);
    }
    renderDuration() {
        const element = this.elements.duration;
        if (!element || !this.durationCall) return;
        const elapsed = Math.max(0, Math.floor((this.now() - this.durationStartedAt) / 1000));
        const seconds = String(elapsed % 60).padStart(2, '0');
        const minutes = String(Math.floor(elapsed / 60) % 60).padStart(2, '0');
        const hours = Math.floor(elapsed / 3600);
        element.textContent = hours ? `${String(hours).padStart(2, '0')}:${minutes}:${seconds}` : `${minutes}:${seconds}`;
        element.setAttribute('aria-label', `Thời lượng cuộc gọi ${element.textContent}`);
        element.hidden = false;
    }
    stopDuration() {
        this.clearTimer(this.durationTimer);
        this.durationTimer = null;
        this.durationCall = null;
        this.durationStartedAt = null;
        if (this.elements.duration) { this.elements.duration.hidden = true; this.elements.duration.textContent = '00:00'; }
    }

    ownsFullscreen() {
        const overlay = this.elements.overlay;
        const element = document.fullscreenElement;
        return !!element && !!overlay && (element === overlay || !!overlay.contains?.(element));
    }
    updateBrowserControls() {
        const fullscreen = this.ownsFullscreen();
        const canFullscreen = !!this.elements.overlay?.requestFullscreen && !!document.exitFullscreen && document.fullscreenEnabled !== false;
        this.setControl(this.elements.btnFullscreen, fullscreen ? 'Thoát toàn màn hình' : 'Toàn màn hình', {
            pressed: fullscreen, disabled: !this.currentCall?.accepted || !canFullscreen || this.browserOperations.has('fullscreen'),
            busy: this.browserOperations.has('fullscreen'), state: fullscreen ? 'on' : canFullscreen ? 'off' : 'unavailable',
            description: !canFullscreen ? 'Trình duyệt không cho phép toàn màn hình' : '',
            icon: fullscreen ? 'fas fa-compress' : 'fas fa-expand'
        });
        const video = this.elements.remoteVideo;
        const pip = !!video && document.pictureInPictureElement === video;
        const canPiP = !!document.pictureInPictureEnabled && !!video?.requestPictureInPicture && !!document.exitPictureInPicture;
        const hasVideo = this.focusedParticipant === 'local' ? this.hasVideo(this.screenStream || this.localStream) : this.remoteHasVideo();
        this.setControl(this.elements.btnPiP, pip ? 'Đóng cửa sổ nổi' : 'Cửa sổ nổi', {
            pressed: pip, disabled: !this.currentCall?.accepted || !canPiP || (!pip && (!hasVideo || video.readyState < 1)) || this.browserOperations.has('pip'),
            busy: this.browserOperations.has('pip'), state: pip ? 'on' : canPiP ? 'off' : 'unavailable',
            description: !canPiP ? 'Trình duyệt không hỗ trợ cửa sổ video nổi' : !hasVideo ? 'Cần video hoặc màn hình đang phát' : video?.readyState < 1 ? 'Đang chờ video sẵn sàng' : ''
        });
        if (this.elements.btnPiP) this.elements.btnPiP.hidden = !canPiP;
        this.setControl(this.elements.btnPlayAudio, 'Bật âm thanh', {
            disabled: !this.currentCall || !this.elements.remoteAudio || !!this.audioPlay,
            busy: !!this.audioPlay, state: this.audioNeedsGesture ? 'blocked' : 'playing'
        });
        if (this.elements.btnPlayAudio) this.elements.btnPlayAudio.hidden = !this.audioNeedsGesture;
    }
    async toggleFullscreen() {
        const call = this.currentCall;
        const overlay = this.elements.overlay;
        if (!call?.accepted || !overlay?.requestFullscreen || !document.exitFullscreen || document.fullscreenEnabled === false || this.browserOperations.has('fullscreen')) return false;
        return this.runBrowserAction('fullscreen', call, () => this.ownsFullscreen() ? document.exitFullscreen() : overlay.requestFullscreen(),
            'Không thể đổi chế độ toàn màn hình. Hãy thử lại bằng nút toàn màn hình');
    }
    async togglePictureInPicture() {
        const call = this.currentCall;
        const video = this.elements.remoteVideo;
        this.updateBrowserControls();
        if (!call?.accepted || this.elements.btnPiP?.disabled || !video?.requestPictureInPicture || !document.pictureInPictureEnabled || this.browserOperations.has('pip')) return false;
        return this.runBrowserAction('pip', call, () => document.pictureInPictureElement === video ? document.exitPictureInPicture() : video.requestPictureInPicture(),
            'Không thể mở cửa sổ video nổi. Hãy thử lại khi video đang phát');
    }
    async runBrowserAction(kind, call, action, message) {
        const operation = { call };
        this.browserOperations.set(kind, operation);
        this.updateBrowserControls();
        try {
            await action();
            if (!this.isCurrent(call)) { if (!this.currentCall) await this.exitBrowserViews(); return false; }
            this.setUIFeedback('');
            return true;
        } catch (error) {
            if (this.isCurrent(call)) this.reportUIError(message, error);
            return false;
        } finally {
            if (this.browserOperations.get(kind) === operation) { this.browserOperations.delete(kind); this.updateBrowserControls(); }
        }
    }
    async exitBrowserViews() {
        if (this.ownsFullscreen() && document.exitFullscreen) {
            try { await document.exitFullscreen(); }
            catch (error) { this.reportUIError('Không thể thoát toàn màn hình. Nhấn Esc để thoát', error); }
        }
        if (this.elements.remoteVideo && document.pictureInPictureElement === this.elements.remoteVideo && document.exitPictureInPicture) {
            try { await document.exitPictureInPicture(); }
            catch (error) { this.reportUIError('Không thể đóng cửa sổ video nổi. Hãy đóng cửa sổ đó', error); }
        }
    }
}
