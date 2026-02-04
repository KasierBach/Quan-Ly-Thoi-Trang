/**
 * Chat Socket Handler
 * Manages Socket.IO events.
 */
class ChatSocket {
    constructor(sessionId, app) {
        this.sessionId = sessionId;
        this.app = app;
        this.socket = this.initSocket();
        this.registerEvents();
    }

    initSocket() {
        if (typeof io === 'undefined') return null;
        return io({
            query: { session_id: this.sessionId }
        });
    }

    registerEvents() {
        if (!this.socket) return;

        this.socket.on('new_message', (data) => {
            this.app.handleNewMessage(data);
        });

        this.socket.on('reaction_update', (data) => {
            // data contains: message_id, emoji, user_id, action
            this.app.api.getHistory(this.app.sessionId, this.app.currentConversationId).then(res => {
                const msg = res.messages.find(m => String(m.id) === String(data.message_id));
                if (msg) {
                    this.app.ui.updateMessageReactions(data.message_id, msg.reactions);
                }
            });
        });

        this.socket.on('message_recalled', (data) => {
            if (this.app.currentConversationId) this.app.loadHistory();
        });

        this.socket.on('message_pinned', (data) => {
            if (data.conversation_id === this.app.currentConversationId) {
                this.app.loadPinnedMessages(data.conversation_id);
                const msgGroup = document.querySelector(`.message-group[data-message-id="${data.message_id}"]`);
                if (msgGroup) {
                    msgGroup.classList.add('pinned');
                    msgGroup.dataset.pinned = 'true';
                }
            }
        });

        this.socket.on('message_unpinned', (data) => {
            if (data.conversation_id === this.app.currentConversationId) {
                this.app.loadPinnedMessages(data.conversation_id);
                const msgGroup = document.querySelector(`.message-group[data-message-id="${data.message_id}"]`);
                if (msgGroup) {
                    msgGroup.classList.remove('pinned');
                    msgGroup.dataset.pinned = 'false';
                }
            }
        });

        this.socket.on('typing', (data) => {
            // isMe check: 
            // - For logged in users: matches user_id
            // - For guests: matches session_id AND is NOT from admin
            const isMe = (data.user_id && data.user_id === this.app.userId) ||
                (data.session_id === this.app.sessionId && !data.is_admin);
            if (isMe) return;

            const currentCid = String(this.app.currentConversationId);
            const incomingCid = String(data.conversation_id);
            const isRelevant = (data.conversation_id && incomingCid === currentCid) ||
                (data.session_id === this.app.sessionId) ||
                (this.app.isAdmin && data.session_id === currentCid);

            if (isRelevant) {
                const typingIndicator = document.getElementById('typingIndicator');
                const typingName = document.getElementById('typingName');
                if (typingIndicator && typingName) {
                    typingName.textContent = `${data.user_name || 'Ai đó'} đang soạn tin...`;
                    typingIndicator.classList.add('active');
                    this.app.ui.scrollToBottom();
                }
            }
        });

        this.socket.on('stop_typing', (data) => {
            const currentCid = String(this.app.currentConversationId);
            const incomingCid = String(data.conversation_id);
            const isRelevant = (data.conversation_id && incomingCid === currentCid) ||
                (data.session_id === this.app.sessionId) ||
                (this.app.isAdmin && data.session_id === currentCid);

            if (isRelevant) {
                document.getElementById('typingIndicator')?.classList.remove('active');
            }
        });

        this.socket.on('messages_read', (data) => {
            if (data.conversation_id === this.app.currentConversationId) {
                // data: {conversation_id, user_id}
                this.app.handleMessagesRead(data);
            }
        });

        // Settings updates
        this.socket.on('conversation_settings_updated', (data) => {
            if (data.conversation_id === this.app.currentConversationId) {
                this.app.ui.renderSettings(data.settings);
                this.app.ui.showToast('Thông tin cuộc trò chuyện đã được cập nhật');
            }
        });

        this.socket.on('participant_settings_updated', (data) => {
            if (data.conversation_id === this.app.currentConversationId) {
                this.app.loadParticipants(this.app.currentConversationId);
                if (data.user_id === this.app.userId && data.settings.is_muted !== undefined) {
                    const muteText = document.getElementById('muteText');
                    if (muteText) muteText.textContent = data.settings.is_muted ? 'Bật thông báo' : 'Tắt thông báo';
                }
            }
        });

        // WebRTC Events
        this.socket.on('incoming_call', (data) => this.app.callManager?.handleIncomingCall(data));
        this.socket.on('call_answered', (data) => this.app.callManager?.handleCallAnswered(data));
        this.socket.on('call_rejected', (data) => this.app.callManager?.handleCallRejected(data));
        this.socket.on('call_ended', (data) => this.app.callManager?.handleCallEnded(data));
        this.socket.on('remote_ice_candidate', (data) => this.app.callManager?.handleIceCandidate(data));
        this.socket.on('call_resume', (data) => this.app.callManager?.handleCallResume(data));

        this.socket.on('stream_status', (data) => {
            // data: { conversation_id, user_id, is_streaming }
            this.app.handleStreamStatus(data);
        });

        this.socket.on('stream_request', (data) => {
            // data: { conversation_id, target_user_id, viewer_id, viewer_name }
            this.app.callManager?.handleStreamRequest(data);
        });
    }


    emit(event, data) {
        if (this.socket) {
            this.socket.emit(event, data);
        }
    }
}

export default ChatSocket;
