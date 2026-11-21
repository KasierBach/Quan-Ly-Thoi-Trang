import { findMessage } from '../utils/helpers.js';

/** Authenticated Socket.IO connection. Disconnected mutations are never buffered. */
class ChatSocket {
    constructor(credentials, app, socketFactory = typeof io === 'function' ? io : null) {
        this.app = app;
        this.pendingRequests = new Set();
        this.socket = socketFactory ? socketFactory({
            auth: { csrf_token: app.csrfToken, auth_token: credentials.auth_token },
            autoConnect: false
        }) : null;
        this.registerEvents();
    }

    connect() { this.socket?.connect(); }
    get connected() { return this.socket?.connected === true; }

    registerEvents() {
        if (!this.socket) return;
        const on = (event, handler) => this.socket.on(event, data => {
            Promise.resolve().then(() => handler(data)).catch(error => this.app.ui.showToast(error.message));
        });
        on('connect', async () => {
            this.app.callManager?.handleSocketConnected();
            await this.app.joinCurrentConversation();
        });
        on('disconnect', () => {
            for (const cancel of this.pendingRequests) cancel(new Error('Kết nối chat đã đóng'));
            this.app.callManager?.handleSocketDisconnected();
            this.app.meshCallManager?.handleSocketDisconnected();
        });
        on('connect_error', () => this.app.ui.showToast('Không thể kết nối chat. Hãy tải lại trang để khởi tạo phiên mới.'));
        on('error', data => {
            if (data.call_id && this.app.meshCallManager?.matches(data)) this.app.meshCallManager.fail?.(this.app.meshCallManager.currentCall, new Error(data.message || 'Máy chủ từ chối cuộc gọi nhóm'));
            else if (data.call_id) this.app.callManager?.handleSignalError(data);
            else this.app.ui.showToast(data.message || 'Thao tác chat không thành công');
        });
        on('new_message', data => this.app.handleNewMessage(data));
        on('conversation_updated', () => this.app.scheduleConversationRefresh());
        on('reaction_update', data => {
            if (!this.app.isCurrentScope(data)) return;
            return this.app.reloadReactions(data.message_id);
        });
        on('message_recalled', data => {
            if (this.app.isCurrentScope(data)) return this.app.loadHistory();
        });
        for (const [event, pinned] of [['message_pinned', true], ['message_unpinned', false]]) {
            on(event, data => {
                if (!this.app.isCurrentScope(data)) return;
                this.app.loadPinnedMessages(this.app.currentConversationId);
                const record = this.app.messageRecords.get(String(data.message_id));
                if (record) record.is_pinned = pinned;
                const group = findMessage(data.message_id);
                if (group) {
                    group.classList.toggle('pinned', pinned);
                    group.dataset.pinned = String(pinned);
                }
            });
        }
        on('typing', data => {
            if (this.app.isOwnMessage(data) || !this.app.isCurrentScope(data)) return;
            const name = document.getElementById('typingName');
            if (name) name.textContent = `${data.user_name || 'Ai đó'} đang soạn tin...`;
            document.getElementById('typingIndicator')?.classList.add('active');
        });
        on('stop_typing', data => {
            if (this.app.isCurrentScope(data)) document.getElementById('typingIndicator')?.classList.remove('active');
        });
        on('messages_read', data => {
            if (this.app.isCurrentScope(data)) this.app.handleMessagesRead(data);
        });
        on('conversation_settings_updated', data => {
            if (!this.app.isCurrentScope(data)) return;
            this.app.ui.renderSettings(data.settings);
        });
        on('participant_settings_updated', data => {
            if (!this.app.isCurrentScope(data)) return;
            this.app.loadParticipants(this.app.currentConversationId);
            if (String(data.user_id) === String(this.app.userId) && data.settings.is_muted !== undefined) {
                const text = document.getElementById('muteText');
                if (text) text.textContent = data.settings.is_muted ? 'Bật thông báo' : 'Tắt thông báo';
            }
        });
        on('group_call_invited', data => this.app.meshCallManager?.handleInvited(data));
        on('group_call_state', data => this.app.meshCallManager?.handleState(data));
        on('group_call_signal', data => this.app.meshCallManager?.handleSignal(data));
        for (const [event, method] of Object.entries({
            incoming_call: 'handleIncomingCall', call_answered: 'handleCallAnswered',
            call_rejected: 'handleCallRejected', call_ended: 'handleCallEnded',
            remote_ice_candidate: 'handleIceCandidate', call_resume: 'handleCallResume'
        })) on(event, data => this.app.callManager?.[method](data));
        for (const [event, directMethod, meshMethod] of [
            ['stream_status', 'handleStreamStatus', 'handleStreamStatus'],
            ['call_chat_message', 'handleCallChatMessage', 'handleCallChatMessage'],
            ['media_status', 'handleMediaStatus', 'handleMediaStatus']
        ]) on(event, data => {
            if (this.app.meshCallManager?.matches(data)) return this.app.meshCallManager[meshMethod](data);
            return this.app.callManager?.[directMethod](data);
        });
    }

    emit(event, data) {
        if (!this.connected) return false;
        this.socket.emit(event, data);
        return true;
    }

    request(event, data, timeoutMs = 10000) {
        if (!this.connected) return Promise.reject(new Error('Chưa kết nối chat'));
        return new Promise((resolve, reject) => {
            let settled = false;
            const finish = (error, result) => {
                if (settled) return;
                settled = true;
                clearTimeout(timer);
                this.pendingRequests.delete(cancel);
                if (error) reject(error);
                else resolve(result);
            };
            const cancel = error => finish(error);
            const timer = setTimeout(() => finish(new Error('Máy chủ chat chưa xác nhận thao tác')), timeoutMs);
            this.pendingRequests.add(cancel);
            try {
                this.socket.emit(event, data, result => {
                    if (!result || result.success !== true) {
                        const error = new Error(result?.message || 'Thao tác chat không thành công');
                        error.status = result?.status;
                        finish(error);
                    } else finish(null, result);
                });
            } catch (error) { finish(error); }
        });
    }

    close() {
        for (const cancel of this.pendingRequests) cancel(new Error('Trang chat đã đóng'));
        this.socket?.disconnect();
    }
}

export default ChatSocket;
