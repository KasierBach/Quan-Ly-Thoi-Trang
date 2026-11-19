import CallState from './CallState.js';
import { createNode } from '../utils/helpers.js';

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
            this.elements.remoteVideo?.play()?.catch(() => this.notify('Nhấn phát video để nghe cuộc gọi nếu trình duyệt chặn tự phát'));
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
        if (!this.isCurrent(call) || !call.signalReady || !call.localDescriptionReady) return;
        while (call.localIce.length && this.isCurrent(call)) {
            if (!this.socket?.emit('ice_candidate', { ...this.scope(call), candidate: call.localIce.shift() })) break;
        }
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
        if (!this.mediaDevices?.getDisplayMedia) { this.notify('Trình duyệt không hỗ trợ chia sẻ màn hình'); return false; }
        call.screenOperation = true;
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
            if (this.isCurrent(call) && error.name !== 'NotAllowedError') this.notify(error.message);
            return false;
        } finally { call.screenOperation = false; }
    }
    async stopScreenShare() {
        const call = this.currentCall;
        if (!call || !this.isSharingScreen || call.screenOperation) return false;
        call.screenOperation = true;
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
        finally { call.screenOperation = false; }
    }
    watchStream() {
        this.notify('Xem livestream/nhóm chưa được hỗ trợ. Chia sẻ màn hình chỉ trong cuộc gọi một-một.');
        return false;
    }
    handleStreamRequest() { return this.watchStream(); }
    handleStreamStatus(data) {
        if (!this.matches(data) || !this.currentCall.accepted) return;
        if (this.elements.remoteNameTag) this.elements.remoteNameTag.textContent =
            this.currentCall.peerName + (data.is_streaming ? ' (Chia sẻ màn hình)' : '');
    }

    broadcastMediaStatus() {
        const call = this.currentCall;
        if (!call?.accepted || !this.localStream) return;
        for (const [kind, type] of [['audio', 'mic'], ['video', 'cam']]) {
            const track = this.localStream.getTracks().find(item => item.kind === kind);
            if (track) this.socket?.emit('media_status', { ...this.scope(call), type, enabled: track.enabled });
        }
    }
    handleMediaStatus(data) {
        if (!this.matches(data) || !this.currentCall.accepted || typeof data.enabled !== 'boolean') return;
        const participant = document.getElementById('remoteParticipant');
        if (data.type === 'mic') {
            participant?.querySelector('.participant-status')?.classList.toggle('muted', !data.enabled);
            const icon = participant?.querySelector('.participant-status i');
            if (icon) icon.className = data.enabled ? 'fas fa-microphone' : 'fas fa-microphone-slash';
        } else if (data.type === 'cam') {
            const video = participant?.querySelector('video');
            const placeholder = participant?.querySelector('.participant-placeholder');
            if (video) video.style.display = data.enabled ? 'block' : 'none';
            if (placeholder) placeholder.style.display = data.enabled ? 'none' : 'flex';
        }
    }

    async sendCallChatMessage() {
        const call = this.currentCall;
        const input = document.getElementById('callChatInput');
        const text = input?.value.trim();
        if (!this.isCallActive || !call?.accepted || call.sendingChat || !text) return false;
        call.sendingChat = true;
        const timestamp = Date.now();
        try {
            if (!await this.requestSignal(call, 'call_chat_message', { text, timestamp })) return false;
            if (input.value.trim() === text) input.value = '';
            this.addCallChatMessage({ sender_name: this.app.userName, text, timestamp, own: true });
            return true;
        } catch (error) { if (this.isCurrent(call)) this.notify(error.message); return false; }
        finally { call.sendingChat = false; }
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
        this.closeOverlay();
        document.getElementById('remoteParticipant')?.remove();
        document.getElementById('callChatMessages')?.replaceChildren();
        this.toggleCallChat(false);
    }
    dispose() { this.endCall(); this.disposed = true; }

    initUI() {
        if (this.uiInitialized) return;
        this.uiInitialized = true;
        const ids = {
            btnShare: 'btnShareScreen', btnEnd: 'btnEndCall', localVideo: 'localVideo', remoteVideo: 'remoteVideo',
            overlay: 'callOverlay', view: 'activeCallView', status: 'callStatus', incomingModal: 'incomingCallModal',
            incomingName: 'incomingName', incomingAvatar: 'incomingAvatar', channelName: 'callChannelName',
            callerInfo: 'callerInfo', remoteNameTag: 'remoteNameTag', participantStrip: 'participantStrip',
            btnAnswer: 'btnAcceptCall', btnReject: 'btnRejectCall', btnMic: 'btnToggleMic', btnCam: 'btnToggleCam',
            btnGridView: 'btnGridView'
        };
        for (const [key, id] of Object.entries(ids)) this.elements[key] = document.getElementById(id);
        if (this.elements.btnAnswer) this.elements.btnAnswer.onclick = () => this.acceptCall();
        if (this.elements.btnReject) this.elements.btnReject.onclick = () => this.rejectCall();
        if (this.elements.btnEnd) this.elements.btnEnd.onclick = () => this.endCall();
        if (this.elements.btnShare) this.elements.btnShare.onclick = () => this.toggleScreenShare();
        if (this.elements.btnGridView) this.elements.btnGridView.onclick = () => this.toggleGridView();
        for (const [key, kind] of [['btnMic', 'audio'], ['btnCam', 'video']]) {
            if (this.elements[key]) this.elements[key].onclick = () => {
                if (!this.currentCall?.accepted) return;
                const track = this.localStream?.getTracks().find(item => item.kind === kind);
                if (!track) return;
                track.enabled = !track.enabled;
                this.elements[key].classList.toggle('active', !track.enabled);
                const icon = this.elements[key].querySelector('i');
                if (icon) icon.className = kind === 'audio' ?
                    (track.enabled ? 'fas fa-microphone' : 'fas fa-microphone-slash') :
                    (track.enabled ? 'fas fa-video' : 'fas fa-video-slash');
                document.getElementById('localMicStatus')?.classList.toggle('muted', !this.localStream.getAudioTracks()[0]?.enabled);
                this.broadcastMediaStatus();
            };
        }
        const local = document.getElementById('localParticipant');
        if (local) local.onclick = () => this.focusStream(this.screenStream || this.localStream, 'Bạn', true);
        document.getElementById('btnToggleChat')?.addEventListener('click', () => this.toggleCallChat());
        document.getElementById('btnCloseCallChat')?.addEventListener('click', () => this.toggleCallChat(false));
        document.getElementById('btnSendCallChat')?.addEventListener('click', () => this.sendCallChatMessage());
        document.getElementById('callChatInput')?.addEventListener('keydown', event => {
            if (event.key === 'Enter') { event.preventDefault(); this.sendCallChatMessage(); }
        });
    }
    toggleCallChat(force = null) {
        const panel = document.getElementById('callChatPanel');
        if (!panel) return;
        const open = force ?? !panel.classList.contains('active');
        panel.classList.toggle('active', open);
        this.elements.view?.classList.toggle('chat-open', open);
        document.getElementById('btnToggleChat')?.classList.toggle('active', open);
        if (open) document.getElementById('callChatInput')?.focus();
    }
    toggleGridView() {
        this.isGridView = !this.isGridView;
        this.elements.view?.classList.toggle('grid-mode', this.isGridView);
        this.elements.btnGridView?.classList.toggle('active', this.isGridView);
    }
    focusStream(stream, name, local = false) {
        const video = this.elements.remoteVideo;
        if (!video || !stream) return;
        if (this.isGridView) this.toggleGridView();
        video.srcObject = stream;
        video.muted = local;
        const hasVideo = stream.getVideoTracks().some(track => track.enabled && track.readyState !== 'ended');
        video.style.display = hasVideo ? 'block' : 'none';
        const placeholder = document.getElementById('remotePlaceholder');
        if (placeholder) placeholder.style.display = hasVideo ? 'none' : 'flex';
        if (this.elements.remoteNameTag) this.elements.remoteNameTag.textContent = name;
        video.controls = !local;
        if (!local) video.muted = false;
        video.play()?.catch(() => this.notify('Nhấn phát video để nghe cuộc gọi nếu trình duyệt chặn tự phát'));
    }
    updatePrimaryVideo() {
        if (this.remoteStream) this.focusStream(this.remoteStream, this.currentCall?.peerName || 'Người dùng');
        else if (this.screenStream || this.localStream) this.focusStream(this.screenStream || this.localStream, 'Bạn', true);
    }
    addRemoteParticipant() {
        const strip = this.elements.participantStrip;
        if (!strip || !this.remoteStream) return;
        document.getElementById('remoteParticipant')?.remove();
        const item = createNode('div', 'participant-item');
        item.id = 'remoteParticipant';
        const video = createNode('video');
        video.autoplay = true;
        video.playsInline = true;
        video.muted = true; // Primary video is the only remote audio sink.
        video.srcObject = this.remoteStream;
        const placeholder = createNode('div', 'participant-placeholder');
        placeholder.appendChild(createNode('i', 'fas fa-user'));
        const hasVideo = this.remoteStream.getVideoTracks().some(track => track.enabled);
        video.style.display = hasVideo ? 'block' : 'none';
        placeholder.style.display = hasVideo ? 'none' : 'flex';
        const status = createNode('div', 'participant-status');
        status.appendChild(createNode('i', 'fas fa-microphone'));
        item.append(video, placeholder, createNode('div', 'participant-name', this.currentCall?.peerName), status);
        item.onclick = () => this.focusStream(this.remoteStream, this.currentCall?.peerName || 'Người dùng');
        strip.appendChild(item);
    }
    addRemoteParticipantPlaceholder(text) {
        const strip = this.elements.participantStrip;
        if (!strip) return;
        document.getElementById('remoteParticipant')?.remove();
        const item = createNode('div', 'participant-item connecting');
        item.id = 'remoteParticipant';
        const placeholder = createNode('div', 'participant-placeholder');
        placeholder.appendChild(createNode('i', 'fas fa-user'));
        item.append(placeholder, createNode('div', 'participant-name', text));
        strip.appendChild(item);
    }
    showOverlay() { this.elements.overlay?.classList.add('active'); }
    closeOverlay() {
        this.elements.overlay?.classList.remove('active');
        if (this.elements.view) { this.elements.view.style.display = 'none'; this.elements.view.classList.remove('active'); }
    }
    setStatus(text, visible = true) {
        if (this.elements.status) { this.elements.status.textContent = text; this.elements.status.style.display = visible ? 'flex' : 'none'; }
    }
    showIncomingModal(data) { this.showRing(data.sender_name || 'Người dùng', true); }
    showOutgoingModal(name) { this.showRing(name, false); }
    showRing(name, incoming) {
        if (this.elements.incomingName) this.elements.incomingName.textContent = name;
        if (this.elements.incomingAvatar) this.elements.incomingAvatar.textContent = String(name)[0] || '?';
        const title = this.elements.incomingModal?.querySelector('p');
        if (title) title.textContent = incoming ? 'Cuộc gọi đến...' : 'Đang gọi...';
        if (this.elements.btnAnswer) this.elements.btnAnswer.style.display = incoming ? 'inline-flex' : 'none';
        if (this.elements.incomingModal) { this.elements.incomingModal.classList.add('active'); this.elements.incomingModal.style.display = 'block'; }
        if (this.elements.view) this.elements.view.style.display = 'none';
        this.setStatus('', false);
    }
    hideIncomingModal() {
        this.elements.incomingModal?.classList.remove('active');
        if (this.elements.incomingModal) this.elements.incomingModal.style.display = 'none';
    }
    showActiveView() {
        if (this.elements.view) { this.elements.view.style.display = 'flex'; this.elements.view.classList.add('active'); }
        if (this.elements.channelName) this.elements.channelName.textContent = this.currentCall?.peerName || 'Cuộc gọi riêng tư';
        if (this.elements.callerInfo) this.elements.callerInfo.textContent = 'Cuộc gọi một-một';
    }
}
