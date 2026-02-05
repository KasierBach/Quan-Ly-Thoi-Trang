/**
 * Call Manager
 * Handles WebRTC Voice and Video Calls
 */
export class CallManager {
    constructor(app) {
        this.app = app;
        this.socket = app.socket;
        this.localStream = null;
        this.remoteStream = null;
        this.peerConnection = null;
        this.config = {
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:stun1.l.google.com:19302' }
            ]
        };

        this.isCallActive = false;
        this.isSharingScreen = false;
        this.screenStream = null;
        this.remoteStream = null;
        this.iceCandidateQueue = [];
        this.pendingCall = null; // Data of incoming call
        this.elements = {};
    }

    initUI() {
        this.isGridView = false; // Grid view mode state

        this.elements = {
            btnToggleCam: document.getElementById('btnToggleCam'),
            btnShare: document.getElementById('btnShareScreen'),
            btnEnd: document.getElementById('btnEndCall'),
            localVideo: document.getElementById('localVideo'),
            remoteVideo: document.getElementById('remoteVideo'),
            overlay: document.getElementById('callOverlay'),
            view: document.getElementById('activeCallView'),
            status: document.getElementById('callStatus'),

            incomingModal: document.getElementById('incomingCallModal'),
            incomingName: document.getElementById('incomingName'),
            incomingAvatar: document.getElementById('incomingAvatar'),

            // Discord elements
            header: document.querySelector('.call-header'),
            channelName: document.getElementById('callChannelName'),
            callerInfo: document.getElementById('callerInfo'),
            remoteNameTag: document.getElementById('remoteNameTag'),

            // Layout elements
            mainContent: document.querySelector('.call-main-content'),
            primaryStream: document.getElementById('primaryStream'),
            participantStrip: document.getElementById('participantStrip'),

            // Buttons
            btnAnswer: document.getElementById('btnAcceptCall'),
            btnReject: document.getElementById('btnRejectCall'),
            btnMic: document.getElementById('btnToggleMic'),
            btnCam: document.getElementById('btnToggleCam'),
            btnGridView: document.getElementById('btnGridView')
        };

        this.bindEvents();
        this.checkPersistentCall();
    }

    checkPersistentCall() {
        const stateStr = localStorage.getItem('active_call_state');
        if (!stateStr) return;

        try {
            const state = JSON.parse(stateStr);
            const now = Date.now();

            // Only resume if the call was "active" in the last 15 seconds (page refresh)
            if (now - state.timestamp < 15000) {
                console.log('Persistent call detected, resuming...', state);
                this.resumeCall(state);
            } else {
                console.log('Call state expired, clearing');
                this.clearCallState();
            }
        } catch (e) {
            console.error('Error parsing call state:', e);
            this.clearCallState();
        }
    }

    startKeepAlive() {
        if (this.keepAliveInterval) clearInterval(this.keepAliveInterval);
        this.keepAliveInterval = setInterval(() => this.keepAlivePersistentCall(), 5000);
    }

    stopKeepAlive() {
        if (this.keepAliveInterval) {
            clearInterval(this.keepAliveInterval);
            this.keepAliveInterval = null;
        }
    }

    bindEvents() {
        if (this.elements.btnAnswer) this.elements.btnAnswer.onclick = () => this.acceptCall();
        if (this.elements.btnReject) this.elements.btnReject.onclick = () => this.rejectCall();
        if (this.elements.btnEnd) this.elements.btnEnd.onclick = () => this.endCall();

        if (this.elements.btnMic) {
            this.elements.btnMic.onclick = () => {
                const stream = this.localStream || this.screenStream;
                if (stream) {
                    const track = stream.getAudioTracks()[0];
                    if (track) {
                        track.enabled = !track.enabled;
                        this.elements.btnMic.classList.toggle('btn-danger', !track.enabled);
                        this.elements.btnMic.classList.toggle('active', !track.enabled);
                        console.log('Mic enabled:', track.enabled);
                    }
                }
            };
        }

        if (this.elements.btnCam) {
            this.elements.btnCam.onclick = () => {
                if (this.localStream) {
                    const track = this.localStream.getVideoTracks()[0];
                    if (track) {
                        track.enabled = !track.enabled;
                        this.elements.btnCam.classList.toggle('btn-danger', !track.enabled);
                        this.elements.btnCam.classList.toggle('active', !track.enabled);
                        console.log('Cam enabled:', track.enabled);
                    }
                }
            };
        }

        if (this.elements.btnShare) {
            this.elements.btnShare.onclick = () => this.toggleScreenShare();
        }

        // Grid View Toggle
        if (this.elements.btnGridView) {
            this.elements.btnGridView.onclick = () => this.toggleGridView();
        }
    }

    toggleGridView() {
        this.isGridView = !this.isGridView;

        if (this.elements.view) {
            this.elements.view.classList.toggle('grid-mode', this.isGridView);
        }

        if (this.elements.btnGridView) {
            this.elements.btnGridView.classList.toggle('active', this.isGridView);
        }

        console.log('Grid view:', this.isGridView);
    }

    addRemoteParticipant() {
        console.log('Adding remote participant to strip...');

        // Find participant strip if not already cached
        const strip = this.elements.participantStrip || document.getElementById('participantStrip');
        if (!strip) {
            console.warn('Participant strip not found!');
            return;
        }

        // Check if already present
        const existingItem = document.getElementById('remoteParticipant');
        if (existingItem) {
            // If it's a placeholder (has 'connecting' class), remove it and continue to create real one
            if (existingItem.classList.contains('connecting')) {
                console.log('Replacing placeholder with real remote participant');
                existingItem.remove();
            } else {
                console.log('Remote participant exists, updating state');
                const video = existingItem.querySelector('video');
                let placeholder = existingItem.querySelector('.participant-placeholder');

                // Ensure placeholder exists (legacy update)
                if (!placeholder) {
                    placeholder = document.createElement('div');
                    placeholder.className = 'participant-placeholder';
                    placeholder.innerHTML = '<i class="fas fa-user"></i>';
                    placeholder.style.cssText = 'display:flex; align-items:center; justify-content:center; width:100%; height:100%; background:#334155; color:#94a3b8; font-size:2rem;';
                    if (video) existingItem.insertBefore(placeholder, existingItem.querySelector('.participant-name'));
                }

                if (video && this.remoteStream) {
                    if (hasVideo) {
                        video.srcObject = this.remoteStream;
                        video.style.display = 'block';
                        if (placeholder) placeholder.style.display = 'none';
                        video.play().catch(e => console.warn('Remote video autoplay blocked:', e));
                    } else {
                        video.style.display = 'none';
                        if (placeholder) placeholder.style.display = 'flex';
                    }

                    // Re-attach listeners? Actually track listeners persist on track object.
                    // But if stream changed, we need new listeners.
                    // Ideally we should remove old ones but for simplicity we rely on garbage collection of old stream/tracks
                }
                return;
            }
        }

        const remoteName = this.pendingCall?.sender_name || 'Remote User';

        const item = document.createElement('div');
        item.className = 'participant-item';
        item.id = 'remoteParticipant';
        const hasVideo = this.remoteStream && this.remoteStream.getVideoTracks().some(t => t.enabled);
        item.innerHTML = `
            <video autoplay playsinline style="${hasVideo ? '' : 'display:none'}"></video>
            <div class="participant-placeholder" style="${hasVideo ? 'display:none' : 'display:flex; align-items:center; justify-content:center; width:100%; height:100%; background:#334155; color:#94a3b8; font-size:2rem;'}">
                <i class="fas fa-user"></i>
            </div>
            <div class="participant-name">${remoteName}</div>
            <div class="participant-status">
                <i class="fas fa-microphone"></i>
            </div>
        `;

        // Set video source to remote stream
        const video = item.querySelector('video');
        if (video && this.remoteStream) {
            video.srcObject = this.remoteStream;
            if (hasVideo) video.play().catch(e => console.warn('Remote video autoplay blocked:', e));

            // Listen for track mute/unmute to toggle avatar
            this.remoteStream.getVideoTracks().forEach(track => {
                track.onmute = () => {
                    video.style.display = 'none';
                    const ph = item.querySelector('.participant-placeholder');
                    if (ph) ph.style.display = 'flex';
                };
                track.onunmute = () => {
                    video.style.display = 'block';
                    const ph = item.querySelector('.participant-placeholder');
                    if (ph) ph.style.display = 'none';
                };
            });
        }

        // Click to focus on this participant (switch to focus mode and set as primary)
        item.onclick = () => {
            if (this.isGridView) {
                this.toggleGridView(); // Switch to focus mode
            }
        };

        strip.appendChild(item);
        console.log('Remote participant added successfully');
    }

    removeRemoteParticipant() {
        const el = document.getElementById('remoteParticipant');
        if (el) el.remove();
    }

    addRemoteParticipantPlaceholder(statusText = 'Connecting...') {
        const strip = this.elements.participantStrip || document.getElementById('participantStrip');
        if (!strip) return;

        // Remove existing placeholder if any
        const existing = document.getElementById('remoteParticipant');
        if (existing) existing.remove();

        const item = document.createElement('div');
        item.className = 'participant-item connecting';
        item.id = 'remoteParticipant';
        item.innerHTML = `
            <div class="participant-placeholder">
                <i class="fas fa-user"></i>
            </div>
            <div class="participant-name">${statusText}</div>
        `;

        strip.appendChild(item);
    }

    // --- Outgoing Call ---
    async startCall(video = true) {
        console.log(`Starting ${video ? 'Video' : 'Voice'} call for conversation:`, this.app.currentConversationId);
        if (this.isCallActive) {
            console.warn('Call already active, ignoring startCall');
            return;
        }

        if (!this.app.currentConversationId) {
            alert('Please select a conversation first');
            return;
        }

        this.showOverlay();
        this.showOverlay();
        // Show Outgoing Modal instead of Active View immediately, with peer name from header or default
        const headerName = document.getElementById('chatHeaderName')?.textContent;
        this.showOutgoingModal(headerName || 'User');

        // Add remote participant placeholder immediately
        this.addRemoteParticipantPlaceholder('Waiting for answer...');

        try {
            await this.getMedia(video);
            await this.createPeerConnection();
            this.addLocalTracks();

            const offer = await this.peerConnection.createOffer();
            await this.peerConnection.setLocalDescription(offer);

            // Send Offer
            this.socket.emit('call_user', {
                conversation_id: this.app.currentConversationId,
                sender_id: this.app.userId,
                session_id: this.app.sessionId,
                sender_name: this.app.userName || 'User',
                offer: offer,
                isVideo: video
            });

            this.saveCallState(this.app.currentConversationId, video);
            console.log('Call offer sent successfully');

        } catch (e) {
            console.error('Start Call Error:', e);
            this.endCall();
            alert('Could not start call: ' + e.message);
        }
    }

    // --- Incoming Call ---
    async handleIncomingCall(data) {
        console.log('Incoming call signal received:', data);

        // Only reject if it's EXACTLY the same session AND same user ID (self-echo)
        if (data.sender_id == this.app.userId && data.session_id == this.app.sessionId) {
            console.log('Ignoring self-echo call signal');
            return;
        }

        // Handle targeted signaling (e.g. for Watch flow)
        if (data.target_user_id && data.target_user_id != this.app.userId) {
            console.log('Ignoring signal targeted at another user:', data.target_user_id);
            return;
        }

        // Handle reconnection/renegotiation (e.g. adding screen share or F5 resume)
        if (data.isResume) {
            console.log('Processing resume/renegotiation offer (isResume). Active:', this.isCallActive);
            this.cancelResumeTimeout(); // Cancel any pending resume timeout

            // If we are NOT in a call, but this is a resume offer, we should probably accept it silently
            // if we have a matching persistent state.
            if (!this.isCallActive) {
                console.log('Silent reconnection from peer (isResume=true, isCallActive=false)');
                this.pendingCall = data;
                await this.acceptCall();
                return;
            }

            // Allow renegotiation even if stable (ACTUALLY, stable is the ONLY state we should accept valid offers in, unless we are in glare)
            if (this.peerConnection && this.peerConnection.signalingState !== 'stable' && this.peerConnection.signalingState !== 'have-local-offer' && this.peerConnection.signalingState !== 'have-remote-offer') {
                // If we are closed or something weird
                console.warn('Renegotiation offered but state is:', this.peerConnection.signalingState);
                // We might still want to proceed if we can reset, but for now let's just log
            }

            // REMOVED the "if stable return" check because that was the BUG.
            // We WANT to accept offers when stable.

            try {
                await this.peerConnection.setRemoteDescription(new RTCSessionDescription(data.offer));
                const answer = await this.peerConnection.createAnswer();
                await this.peerConnection.setLocalDescription(answer);
                this.socket.emit('answer_call', {
                    conversation_id: data.conversation_id,
                    sender_id: this.app.userId,
                    session_id: this.app.sessionId,
                    answer: answer
                });
                return;
            } catch (e) {
                console.error('Error during renegotiation:', e);
                return;
            }
        }

        if (this.isCallActive) {
            console.log('Already in a call, rejecting incoming call from:', data.sender_id);
            this.socket.emit('reject_call', {
                conversation_id: data.conversation_id,
                session_id: this.app.sessionId
            });
            return;
        }

        console.log('Showing incoming call modal for:', data.sender_name, 'isResume:', data.isResume);
        this.pendingCall = data;
        this.showOverlay();
        this.showIncomingModal(data);
    }

    async acceptCall() {
        if (!this.pendingCall) return;

        this.hideIncomingModal();
        this.showActiveView();
        this.elements.status.textContent = 'Connecting...';

        try {
            // Get media matching the call type (video or audio-only)
            const video = this.pendingCall.isVideo;
            await this.getMedia(video);

            await this.createPeerConnection();
            this.addLocalTracks();

            await this.peerConnection.setRemoteDescription(new RTCSessionDescription(this.pendingCall.offer));

            const answer = await this.peerConnection.createAnswer();
            await this.peerConnection.setLocalDescription(answer);

            this.socket.emit('answer_call', {
                conversation_id: this.pendingCall.conversation_id,
                sender_id: this.app.userId,
                session_id: this.app.sessionId,
                answer: answer
            });

            this.saveCallState(this.pendingCall.conversation_id, video);
            await this.processQueuedCandidates();

        } catch (e) {
            console.error(e);
            this.endCall();
        }
    }

    // --- Screen Share ---
    async toggleScreenShare() {
        if (!this.isCallActive || !this.peerConnection) return;

        if (this.isSharingScreen) {
            await this.stopScreenShare();
        } else {
            await this.startScreenShare();
        }
    }

    async startScreenShare() {
        try {
            this.screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
            const screenTrack = this.screenStream.getVideoTracks()[0];

            // Replace track in RTCPeerConnection
            const senders = this.peerConnection.getSenders();
            const videoSender = senders.find(s => s.track && s.track.kind === 'video');

            if (videoSender) {
                console.log('Replacing existing video track with screen track');
                await videoSender.replaceTrack(screenTrack);
            } else {
                console.log('No video sender found, adding screen track to peer connection');
                this.peerConnection.addTrack(screenTrack, this.screenStream);
            }

            // Always renegotiate to ensure remote peer gets the new track
            console.log('Renegotiating to sync screen share with remote peer');
            const offer = await this.peerConnection.createOffer();
            await this.peerConnection.setLocalDescription(offer);
            this.socket.emit('call_user', {
                conversation_id: this.app.currentConversationId,
                sender_id: this.app.userId,
                session_id: this.app.sessionId,
                sender_name: this.app.userName || 'User',
                offer: offer,
                isVideo: true,
                isResume: true // Use resume-like logic to update remote
            });

            // Update local UI
            this.elements.localVideo.srcObject = this.screenStream;
            this.elements.btnShare.classList.add('sharing');
            this.isSharingScreen = true;
            this.updatePrimaryVideo();

            // Broadcast stream status
            this.socket.emit('stream_status', {
                conversation_id: this.app.currentConversationId,
                user_id: this.app.userId,
                is_streaming: true
            });

            // Handle user clicking "Stop Sharing" in browser UI
            screenTrack.onended = () => this.stopScreenShare();

        } catch (e) {
            console.error('Screen Share Error:', e);
            if (e.name !== 'NotAllowedError') {
                alert('Could not start screen share: ' + e.message);
            }
        }
    }

    async stopScreenShare() {
        if (!this.isSharingScreen) return;

        try {
            if (this.screenStream) {
                this.screenStream.getTracks().forEach(t => t.stop());
            }

            const videoTrack = this.localStream.getVideoTracks()[0];
            const senders = this.peerConnection.getSenders();
            const videoSender = senders.find(s => s.track && s.track.kind === 'video');

            if (videoSender && videoTrack) {
                await videoSender.replaceTrack(videoTrack);
            }

            // Restore local UI
            this.elements.localVideo.srcObject = this.localStream;
            this.elements.btnShare.classList.remove('sharing');
            this.isSharingScreen = false;
            this.screenStream = null;
            this.updatePrimaryVideo();

            // Broadcast stream status
            this.socket.emit('stream_status', {
                conversation_id: this.app.currentConversationId,
                user_id: this.app.userId,
                is_streaming: false
            });

        } catch (e) {
            console.error('Stop Screen Share Error:', e);
        }
    }

    rejectCall() {
        if (this.pendingCall) {
            this.socket.emit('reject_call', {
                conversation_id: this.pendingCall.conversation_id,
                session_id: this.app.sessionId
            });
        }
        this.closeOverlay();
    }

    // --- Watch Stream ---
    async watchStream(streamerId, conversationId) {
        console.log(`Requesting to watch stream from user ${streamerId} in conversation ${conversationId}`);
        if (this.isCallActive) {
            alert('You are already in a call or watching a stream');
            return;
        }

        this.app.currentConversationId = conversationId;
        this.showOverlay();
        this.showActiveView();
        if (this.elements.status) this.elements.status.textContent = 'Joining Stream...';

        // Update header info for Watch mode
        this.setHeaderInfo('General', `Watching ${streamerId}'s stream`);
        if (this.elements.remoteNameTag) this.elements.remoteNameTag.textContent = streamerId;

        // Request the streamer to send us a WebRTC offer
        this.socket.emit('request_stream', {
            conversation_id: conversationId,
            target_user_id: streamerId,
            viewer_id: this.app.userId,
            viewer_name: this.app.userName
        });
    }

    async handleStreamRequest(data) {
        console.log(`User ${data.viewer_name} (${data.viewer_id}) requested to watch your stream`);
        if (!this.isSharingScreen || !this.peerConnection) return;

        try {
            // We need to send an offer specifically to the viewer
            // Our current signaling broadcasts to the conversation.
            // We'll add a 'target_user_id' so others ignore it.
            const offer = await this.peerConnection.createOffer();
            await this.peerConnection.setLocalDescription(offer);

            this.socket.emit('call_user', {
                conversation_id: data.conversation_id,
                target_user_id: data.viewer_id, // New field for targeted signaling
                sender_id: this.app.userId,
                session_id: this.app.sessionId,
                sender_name: this.app.userName || 'User',
                offer: offer,
                isVideo: true,
                isResume: true // This ensures the viewer doesn't see a "Ring" modal
            });
            console.log('Sent targeted stream offer to viewer:', data.viewer_id);
        } catch (e) {
            console.error('Error handling stream request:', e);
        }
    }

    // --- Signaling Handlers ---
    async handleCallAnswered(data) {
        if (this.isProcessingAnswer) return;

        if (this.peerConnection && (this.peerConnection.signalingState === 'have-local-offer' || this.peerConnection.signalingState === 'have-remote-pranswer')) {
            this.isProcessingAnswer = true;
            try {
                await this.peerConnection.setRemoteDescription(new RTCSessionDescription(data.answer));
                this.elements.status.textContent = 'Connected';
                await this.processQueuedCandidates();
            } catch (e) {
                console.error('Error handling answer:', e);
            } finally {
                this.isProcessingAnswer = false;
            }
        } else {
            console.warn('Ignoring answer: signalingState is', this.peerConnection?.signalingState);
        }
    }

    async handleIceCandidate(data) {
        if (data.candidate) {
            this.keepAlivePersistentCall();
            if (this.peerConnection && this.peerConnection.remoteDescription) {
                try {
                    await this.peerConnection.addIceCandidate(new RTCIceCandidate(data.candidate));
                } catch (e) {
                    console.error('Error adding ice candidate:', e);
                }
            } else {
                console.log('Queuing ICE candidate (PC or RemoteDesc not ready)');
                this.iceCandidateQueue.push(data.candidate);
            }
        }
    }

    async processQueuedCandidates() {
        if (this.iceCandidateQueue.length > 0) {
            console.log(`Processing ${this.iceCandidateQueue.length} queued candidates`);
            while (this.iceCandidateQueue.length > 0) {
                const candidate = this.iceCandidateQueue.shift();
                await this.peerConnection.addIceCandidate(new RTCIceCandidate(candidate))
                    .catch(e => console.error('Error applying queued candidate:', e));
            }
        }
    }

    handleCallEnded() {
        this.endCall(true); // Is remote
    }

    handleCallRejected() {
        alert('Call declined');
        this.endCall();
    }

    async handleCallResume(data) {
        if (!this.isCallActive || !this.peerConnection) return;

        console.log('Received call_resume signal, re-initiating offer...');
        try {
            const offer = await this.peerConnection.createOffer({ iceRestart: true });
            await this.peerConnection.setLocalDescription(offer);

            this.socket.emit('call_user', {
                conversation_id: data.conversation_id,
                sender_id: this.app.userId,
                session_id: this.app.sessionId,
                sender_name: this.app.userName || 'User',
                offer: offer,
                isVideo: !!this.localStream.getVideoTracks().length,
                isResume: true
            });
        } catch (e) {
            console.error('Error during call resume handshake:', e);
        }
    }

    // --- Core WebRTC ---
    async getMedia(video) {
        try {
            this.localStream = await navigator.mediaDevices.getUserMedia({ video: video, audio: true });
            this.elements.localVideo.srcObject = this.localStream;
            this.updatePrimaryVideo();
        } catch (e) {
            console.error('Media Error:', e);
            throw new Error('Camera/Microphone access denied');
        }
    }

    async createPeerConnection() {
        this.peerConnection = new RTCPeerConnection(this.config);

        this.peerConnection.onicecandidate = (event) => {
            if (event.candidate) {
                this.socket.emit('ice_candidate', {
                    conversation_id: this.app.currentConversationId || (this.pendingCall ? this.pendingCall.conversation_id : null),
                    candidate: event.candidate,
                    sender_id: this.app.userId,
                    session_id: this.app.sessionId
                });
            }
        };

        this.peerConnection.ontrack = async (event) => {
            console.log('Received remote track:', event.track.kind, 'ID:', event.track.id);
            if (!this.remoteStream) this.remoteStream = new MediaStream();

            if (event.streams && event.streams[0]) {
                event.streams[0].getTracks().forEach(t => this.remoteStream.addTrack(t));
            } else {
                this.remoteStream.addTrack(event.track);
            }

            this.updatePrimaryVideo();
            this.addRemoteParticipant(); // Add to participant strip for grid view

            try {
                await this.elements.remoteVideo.play();
                console.log('Remote video playing successfully');
                if (this.elements.status) this.elements.status.style.display = 'none';
            } catch (e) {
                console.warn('Autoplay prevented:', e);
                // Simple auto-fallback
                this.elements.remoteVideo.muted = true;
                this.elements.remoteVideo.play();
            }
        };

        this.peerConnection.onconnectionstatechange = () => {
            console.log('PeerConnection State:', this.peerConnection.connectionState);
            const state = this.peerConnection.connectionState;

            if (state === 'connected') {
                // Connection established - hide status
                if (this.elements.status) {
                    this.elements.status.style.display = 'none';
                }

                // Switch from Modal to Active View
                this.hideIncomingModal();
                this.showActiveView();

                this.cancelResumeTimeout();
            } else if (state === 'connecting') {
                if (this.elements.status) {
                    this.elements.status.textContent = 'Connecting...';
                    this.elements.status.style.display = 'flex';
                }
            } else if (state === 'failed') {
                if (this.elements.status) {
                    this.elements.status.textContent = 'Connection Failed';
                    this.elements.status.style.display = 'flex';
                }
            } else if (state === 'disconnected') {
                if (this.elements.status) {
                    this.elements.status.textContent = 'Reconnecting...';
                    this.elements.status.style.display = 'flex';
                }
            }
        };

        this.isCallActive = true;
        this.startKeepAlive();

        // Process any queued candidates if we were the receiver
        await this.processQueuedCandidates();
    }

    addLocalTracks() {
        this.localStream.getTracks().forEach(track => {
            this.peerConnection.addTrack(track, this.localStream);
        });
    }

    endCall(isRemote = false) {
        this.stopKeepAlive();

        if (!isRemote && (this.app.currentConversationId || this.pendingCall)) {
            // Notify other side
            const cid = this.app.currentConversationId || this.pendingCall?.conversation_id;
            if (cid) this.socket.emit('end_call', {
                conversation_id: cid,
                session_id: this.app.sessionId
            });
        }

        if (this.peerConnection) {
            this.peerConnection.close();
            this.peerConnection = null;
        }
        if (this.localStream) {
            this.localStream.getTracks().forEach(t => t.stop());
            this.localStream = null;
        }
        if (this.screenStream) {
            this.screenStream.getTracks().forEach(t => t.stop());
            this.screenStream = null;
            this.elements.btnShare?.classList.remove('sharing');
        }

        this.elements.localVideo.srcObject = null;
        this.elements.remoteVideo.srcObject = null;
        this.closeOverlay();
        this.isCallActive = false;
        this.pendingCall = null;
        this.clearCallState();

        // Broadcast stop stream status if we were sharing
        if (this.isSharingScreen) {
            this.socket.emit('stream_status', {
                conversation_id: this.app.currentConversationId,
                user_id: this.app.userId,
                is_streaming: false
            });
            this.isSharingScreen = false;
        }
    }

    // --- UI Helpers ---
    showOverlay() {
        this.elements.overlay.classList.add('active');
    }
    closeOverlay() {
        if (this.elements.overlay) this.elements.overlay.classList.remove('active');
        if (this.elements.view) this.elements.view.style.display = 'none';
    }

    setHeaderInfo(channel, info) {
        if (this.elements.channelName) this.elements.channelName.textContent = channel;
        if (this.elements.callerInfo) this.elements.callerInfo.textContent = info;
    }
    showIncomingModal(data) {
        console.log('showIncomingModal called for:', data.sender_name);

        // Setup Modal content for INCOMING
        if (this.elements.incomingName) this.elements.incomingName.textContent = data.sender_name || 'Unknown';
        if (this.elements.incomingAvatar) this.elements.incomingAvatar.textContent = (data.sender_name ? data.sender_name[0] : '?');

        const title = this.elements.incomingModal.querySelector('p');
        if (title) title.textContent = 'Incoming Call...';

        if (this.elements.btnAnswer) this.elements.btnAnswer.style.display = 'inline-flex';

        // Show modal
        if (this.elements.incomingModal) {
            this.elements.incomingModal.classList.add('active');
            this.elements.incomingModal.style.display = 'block';
        }

        // FORCE HIDE active view to prevent "background call" effect
        if (this.elements.view) {
            this.elements.view.style.display = 'none';
            this.elements.view.classList.remove('active');
        }
        if (this.elements.status) this.elements.status.style.display = 'none';
    }

    showOutgoingModal(peerName) {
        console.log('showOutgoingModal called for:', peerName);

        // Setup Modal content for OUTGOING
        if (this.elements.incomingName) this.elements.incomingName.textContent = peerName || 'User';
        if (this.elements.incomingAvatar) this.elements.incomingAvatar.textContent = (peerName ? peerName[0] : '?');

        const title = this.elements.incomingModal.querySelector('p');
        if (title) title.textContent = 'Calling...';

        // Hide Accept button for outgoing
        if (this.elements.btnAnswer) this.elements.btnAnswer.style.display = 'none';

        // Show modal
        if (this.elements.incomingModal) {
            this.elements.incomingModal.classList.add('active');
            this.elements.incomingModal.style.display = 'block';
        }

        // FORCE HIDE active view
        if (this.elements.view) {
            this.elements.view.style.display = 'none';
            this.elements.view.classList.remove('active');
        }
    }

    hideIncomingModal() {
        if (this.elements.incomingModal) {
            this.elements.incomingModal.classList.remove('active');
            this.elements.incomingModal.style.display = 'none';
        }
    }
    showActiveView() {
        if (this.elements.view) {
            this.elements.view.style.display = 'flex';
            this.elements.view.classList.add('active');

            // Trigger resize to fix video layout glitches (force flex recalculation)
            setTimeout(() => {
                window.dispatchEvent(new Event('resize'));
            }, 50);
        }
    }

    // --- State Management ---
    saveCallState(conversationId, isVideo) {
        const state = {
            conversation_id: conversationId,
            isVideo: isVideo,
            timestamp: Date.now()
        };
        localStorage.setItem('active_call_state', JSON.stringify(state));
    }

    clearCallState() {
        localStorage.removeItem('active_call_state');
    }

    keepAlivePersistentCall() {
        if (!this.isCallActive) return;
        const stateStr = localStorage.getItem('active_call_state');
        if (stateStr) {
            try {
                const state = JSON.parse(stateStr);
                state.timestamp = Date.now();
                localStorage.setItem('active_call_state', JSON.stringify(state));
            } catch (e) { }
        }
    }

    async resumeCall(state) {
        console.log('Requesting call resume from peer:', state);

        // Show UI first
        this.app.currentConversationId = state.conversation_id;
        this.showOverlay();
        this.showActiveView();

        if (this.elements.status) {
            this.elements.status.style.display = 'block';
            this.elements.status.textContent = 'Reconnecting...';
        }

        // Set up timeout - if no response in 8 seconds, try to restart call ourselves
        this.resumeTimeout = setTimeout(async () => {
            console.log('Resume timeout - attempting to restart call');
            if (this.elements.status) {
                this.elements.status.textContent = 'Restarting call...';
            }

            try {
                // Try to restart the call ourselves
                await this.getMedia(state.isVideo);
                await this.createPeerConnection();
                this.addLocalTracks();

                const offer = await this.peerConnection.createOffer();
                await this.peerConnection.setLocalDescription(offer);

                this.socket.emit('call_user', {
                    conversation_id: state.conversation_id,
                    sender_id: this.app.userId,
                    session_id: this.app.sessionId,
                    sender_name: this.app.userName || 'User',
                    offer: offer,
                    isVideo: state.isVideo,
                    isResume: true
                });

                this.saveCallState(state.conversation_id, state.isVideo);
                console.log('Call restarted successfully');
            } catch (e) {
                console.error('Failed to restart call:', e);
                if (this.elements.status) {
                    this.elements.status.textContent = 'Connection failed. Please try again.';
                }
                // Close after 3 seconds
                setTimeout(() => this.closeOverlay(), 3000);
                this.clearCallState();
            }
        }, 8000);

        // Notify peer that we refreshed and want them to re-offer
        this.socket.emit('call_resume', {
            conversation_id: state.conversation_id,
            sender_id: this.app.userId,
            session_id: this.app.sessionId
        });
    }

    cancelResumeTimeout() {
        if (this.resumeTimeout) {
            clearTimeout(this.resumeTimeout);
            this.resumeTimeout = null;
        }
    }

    // --- UI State Management ---
    updatePrimaryVideo() {
        if (!this.elements.remoteVideo) return;

        // Check if we have a valid remote video track that is not muted/disabled
        const hasRemoteVideo = this.remoteStream && this.remoteStream.getVideoTracks().some(t => t.enabled);
        const hasRemoteAudio = this.remoteStream && this.remoteStream.getAudioTracks().length > 0;

        if (hasRemoteVideo) {
            console.log('Showing remote video in primary view');
            this.elements.remoteVideo.srcObject = this.remoteStream;
            this.elements.remoteVideo.style.display = 'block';
            if (document.getElementById('remotePlaceholder')) document.getElementById('remotePlaceholder').style.display = 'none';

            if (this.elements.remoteNameTag) {
                this.elements.remoteNameTag.textContent = this.pendingCall?.sender_name || 'Remote User';
            }
        } else if (hasRemoteAudio && !this.isSharingScreen) {
            // Logic: If Audio Only AND I am NOT sharing screen -> Show Placeholder
            // BUT user asked to see "2 stream". If I am sharing screen, I might still want to see Remote Avatar?
            // Discord behavior: Clicking remote user shows them.
            // For now, let's prioritize Remote Audio Placeholder over "Nothing" (but under Screen Share?)
            // Actually, if I am sharing screen, I see my screen. This is fine. Use visual toggle in strip to see remote.
            // BUT if I am NOT sharing screen (Receiving only), I want to see placeholder instead of "you".

            console.log('Showing remote audio placeholder in primary view');
            this.elements.remoteVideo.style.display = 'none';
            if (document.getElementById('remotePlaceholder')) document.getElementById('remotePlaceholder').style.display = 'flex';

            if (this.elements.remoteNameTag) {
                this.elements.remoteNameTag.textContent = (this.pendingCall?.sender_name || 'Remote User') + ' (Audio Only)';
            }
        } else if (this.isSharingScreen && this.screenStream) {
            console.log('Mirroring local screen share to primary view');
            this.elements.remoteVideo.srcObject = this.screenStream;
            this.elements.remoteVideo.style.display = 'block';
            if (document.getElementById('remotePlaceholder')) document.getElementById('remotePlaceholder').style.display = 'none';

            if (this.elements.remoteNameTag) {
                this.elements.remoteNameTag.textContent = 'You (Screen Sharing)';
            }
        } else if (this.localStream && this.localStream.getVideoTracks().length > 0) {
            console.log('Mirroring local camera to primary view');
            this.elements.remoteVideo.srcObject = this.localStream;
            this.elements.remoteVideo.style.display = 'block';
            if (document.getElementById('remotePlaceholder')) document.getElementById('remotePlaceholder').style.display = 'none';

            if (this.elements.remoteNameTag) {
                this.elements.remoteNameTag.textContent = 'You';
            }
        } else {
            console.log('No video available, showing placeholder');
            this.elements.remoteVideo.srcObject = null;
            this.elements.remoteVideo.style.display = 'none';
            // Show placeholder if we have remote connection but no video?
            // If hasRemoteAudio (handled above).
            // Fallback
            if (document.getElementById('remotePlaceholder') && hasRemoteAudio) {
                document.getElementById('remotePlaceholder').style.display = 'flex';
            }

            if (this.elements.remoteNameTag) {
                this.elements.remoteNameTag.textContent = hasRemoteAudio ? (this.pendingCall?.sender_name || 'Remote User') : 'No Video';
            }
        }
    }
}
