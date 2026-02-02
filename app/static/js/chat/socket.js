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
            if (data.conversation_id === this.app.currentConversationId || data.session_id === this.app.sessionId) {
                document.getElementById('typingIndicator')?.classList.add('active');
                this.app.ui.scrollToBottom();
            }
        });

        this.socket.on('stop_typing', (data) => {
            if (data.conversation_id === this.app.currentConversationId || data.session_id === this.app.sessionId) {
                document.getElementById('typingIndicator')?.classList.remove('active');
            }
        });

        this.socket.on('messages_read', (data) => {
            if (data.conversation_id === this.app.currentConversationId) {
                // data: {conversation_id, user_id}
                this.app.handleMessagesRead(data);
            }
        });
    }

    emit(event, data) {
        if (this.socket) {
            this.socket.emit(event, data);
        }
    }
}

export default ChatSocket;
