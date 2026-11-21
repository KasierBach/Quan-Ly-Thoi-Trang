import ChatAPI from './ChatAPI.js';
import ChatUI from '../ui/ChatUI.js';
import ChatSocket from './ChatSocket.js';
import ImageViewer from '../call/StreamViewer.js';
import ChatRecorder from '../media/MediaRecorder.js';
import { createNode, findMessage, initEmojiPicker, renderStickers, renderGifs, stickerUrl, shouldSendOnEnter } from '../utils/helpers.js';
import { CallManager } from '../call/CallManager.js';
import MeshCallManager from '../call/MeshCallManager.js';

/** Page state is initialized only after server-issued credentials are available. */
export class ChatApp {
    constructor(config = {}, dependencies = {}) {
        this.userId = Number(config.userId) || null;
        this.userName = String(config.userName || 'Khách');
        this.isAdmin = config.isAdmin === true;
        this.rtcIceServers = Array.isArray(config.rtcIceServers) ? config.rtcIceServers : undefined;
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
        this.sessionId = null;
        this.currentConversationId = null;
        this.selectionRevision = 0;
        this.historyRevision = 0;
        this.searchRevision = 0;
        this.conversationRevision = 0;
        this.hasSelectedConversation = false;
        this.selectionPending = false;
        this.drafts = new Map();
        this.pendingReads = new Map();
        this.conversations = [];
        this.participants = [];
        this.messageRecords = new Map();
        this.currentReplyTo = null;
        this.currentPinnedMessageId = null;
        this.contextMenuMsgId = null;
        this.contextMenuConvId = null;
        this.selectedGroupUsers = [];
        this.currentPickerMode = 'sticker';
        this.isSending = false;
        this.closed = false;
        this.api = dependencies.api || new ChatAPI(this.csrfToken, { authenticated: !!this.userId });
        this.ui = dependencies.ui || new ChatUI(this);
        this.socketFactory = dependencies.socketFactory || ((credentials, app) => new ChatSocket(credentials, app));
        this.viewer = dependencies.viewer || new ImageViewer();
        this.recorder = dependencies.recorder || new ChatRecorder(blob => this.handleAudioRecorded(blob));
        this.callManager = dependencies.callManager || new CallManager(this);
        this.meshCallManager = dependencies.meshCallManager || new MeshCallManager(this, {
            isDirectCallBusy: () => !!this.callManager?.currentCall
        });
        this.eventController = new AbortController();
        this.ready = this.initialize();
    }

    async initialize() {
        try {
            const credentials = await this.api.ensureGuestSession();
            if (this.closed) return false;
            this.sessionId = credentials.session_id;
            this.socket = this.socketFactory(credentials, this);
            this.callManager.initUI();
            this.meshCallManager.initUI();
            this.initEventListeners();
            initEmojiPicker(this.eventController.signal);
            await this.loadConversations();
            this.socket.connect();
            this.setSendBusy(false);
            return true;
        } catch (error) {
            if (!this.closed) {
                this.ui.showConversationError(error.message, () => location.reload());
                this.ui.showToast(error.message);
            }
            return false;
        }
    }

    isNumericConversation(id = this.currentConversationId) {
        return id !== null && /^\d+$/.test(String(id));
    }
    scope(id = this.currentConversationId) {
        return this.api.scope(this.sessionId, id);
    }
    isCurrentScope(data) {
        if (!data) return false;
        if (this.isNumericConversation()) return String(data.conversation_id) === String(this.currentConversationId);
        const sid = this.currentConversationId || this.sessionId;
        return data.conversation_id == null && data.session_id === sid;
    }
    isOwnMessage(data) {
        if (data.user_id != null) return this.userId !== null && String(data.user_id) === String(this.userId);
        return !this.userId && data.sender_type === 'user' && data.session_id === this.sessionId;
    }

    async loadConversations() {
        if (this.closed) return;
        const list = document.getElementById('conversationList');
        list?.setAttribute('aria-busy', 'true');
        const revision = ++this.conversationRevision;
        try {
            const data = this.userId ? await this.api.getConversations() : { conversations: [] };
            if (this.closed || revision !== this.conversationRevision) return;
            this.conversations = data.conversations || [];
            this.refreshConversationList();
        } catch (error) {
            if (!this.closed && revision === this.conversationRevision) {
                list?.setAttribute('aria-busy', 'false');
                this.ui.showConversationError(error.message, () => this.run(() => this.loadConversations()));
            }
            throw error;
        }
    }

    scheduleConversationRefresh() {
        if (this.closed || !this.userId) return;
        ++this.conversationRevision;
        clearTimeout(this.conversationTimer);
        this.conversationTimer = setTimeout(() => this.run(() => this.loadConversations()), 100);
    }

    refreshConversationList() {
        this.ui.renderConversationList(this.conversations, this.currentConversationId,
            (id, name, online) => this.run(() => this.selectConversation(id, name, online)));
    }

    async selectConversation(id, name, online = false) {
        if (this.closed) return;
        const previous = this.currentConversationId;
        const input = document.getElementById('messageInput');
        if (this.hasSelectedConversation && input) this.drafts.set(String(previous), input.value);
        if (this.hasSelectedConversation && String(previous) !== String(id)) {
            this.updateTypingStatus(true);
            this.meshCallManager.endCall();
            if (this.socket?.connected) this.socket.emit('leave_conversation', this.scope(previous));
        }
        this.currentConversationId = id == null || id === '' ? null : id;
        this.hasSelectedConversation = true;
        this.selectionPending = true;
        if (input) input.value = this.drafts.get(String(this.currentConversationId)) || '';
        const revision = ++this.selectionRevision;
        this.cancelReply();
        this.currentConversationType = null;
        this.currentConversationRole = null;
        this.participants = [];
        this.updateCallAvailability();
        document.getElementById('typingIndicator')?.classList.remove('active');
        document.getElementById('pinnedShelf')?.classList.remove('active');
        this.ui.switchChatUI(name, online, this.currentConversationId);
        this.ui.renderSettings({ theme_color: '#2563eb', default_emoji: '👍' });
        this.setSendBusy(this.isSending);
        await this.joinCurrentConversation();
        if (revision !== this.selectionRevision || this.closed) return;
        await this.loadHistory();
        if (revision !== this.selectionRevision || this.closed) return;
        await this.loadSettings();
        if (revision !== this.selectionRevision || this.closed) return;
        await this.loadParticipants(this.currentConversationId);
        const own = this.participants.find(person => String(person.id) === String(this.userId));
        const text = document.getElementById('muteText');
        if (text) text.textContent = own?.is_muted ? 'Bật thông báo' : 'Tắt thông báo';
        if (revision !== this.selectionRevision || this.closed) return;
        await this.loadPinnedMessages(this.currentConversationId);
        if (revision === this.selectionRevision && !this.closed) {
            this.selectionPending = false;
            this.ui.activeChatContainer?.setAttribute('aria-busy', 'false');
            this.setSendBusy(this.isSending);
            this.refreshConversationList();
        }
    }

    async joinCurrentConversation() {
        if (!this.hasSelectedConversation || !this.socket?.connected || !this.sessionId) return;
        const revision = this.selectionRevision;
        await this.socket.request('join_conversation', this.scope());
        if (this.closed || revision !== this.selectionRevision) return;
        this.joinedRevision = revision;
        this.updateCallAvailability();
        await this.loadHistory();
    }

    async loadHistory() {
        if (!this.sessionId || this.closed) return;
        const selection = this.selectionRevision;
        const request = ++this.historyRevision;
        const area = document.getElementById('messagesArea');
        if (area) area.setAttribute('aria-busy', 'true');
        try {
            const data = await this.api.getHistory(this.sessionId, this.currentConversationId);
            if (this.closed || selection !== this.selectionRevision || request !== this.historyRevision) return;
            this.messageRecords.clear();
            area?.replaceChildren();
            const messages = data.messages || [];
            for (const message of messages) this.renderMessage(message);
            if (!messages.length) this.ui.showEmptyHistory();
        } catch (error) {
            if (!this.closed && selection === this.selectionRevision && request === this.historyRevision) {
                this.ui.showHistoryError(error.message, () => this.run(() => this.loadHistory()));
            }
        } finally {
            if (request === this.historyRevision) area?.setAttribute('aria-busy', 'false');
        }
    }

    renderMessage(message) {
        this.messageRecords.set(String(message.id), message);
        this.ui.appendMessage({
            type: this.isOwnMessage(message) ? 'sent' : 'received', id: message.id,
            content: message.content, time: this.ui.formatTime(message.timestamp || message.created_at),
            msgType: message.message_type, attachments: message.attachments, reactions: message.reactions,
            avatarText: String(message.sender_name || 'Khách')[0], senderName: message.sender_name,
            is_pinned: message.is_pinned,
            reply_to_id: message.reply_to_id, parent_content: message.parent_content,
            parent_sender_type: message.parent_sender_type, parent_sender_name: message.parent_sender_name,
        });
    }

    handleNewMessage(data) {
        if (this.closed) return;
        if (this.hasSelectedConversation && this.isCurrentScope(data)) {
            this.renderMessage(data);
            if (document.activeElement === document.getElementById('messageInput')) this.run(() => this.markRead());
        }
        this.scheduleConversationRefresh();
    }

    setSendBusy(busy) {
        const disabled = busy || this.selectionPending || !this.sessionId || !this.hasSelectedConversation || this.closed;
        for (const id of ['likeBtn', 'attachFileBtn', 'attachImageBtn', 'stickerBtn', 'gifBtn', 'micBtn']) {
            const button = document.getElementById(id);
            if (button) button.disabled = disabled;
        }
        const input = document.getElementById('messageInput');
        if (input) input.disabled = this.selectionPending || !this.sessionId || !this.hasSelectedConversation || this.closed;
        document.querySelector('.chat-input-area')?.setAttribute('aria-busy', String(busy));
        this.updateComposerState(busy);
    }

    updateComposerState(busy = this.isSending) {
        const input = document.getElementById('messageInput');
        const send = document.getElementById('sendBtn');
        if (send) send.disabled = busy || this.selectionPending || !this.sessionId || !this.hasSelectedConversation || this.closed ||
            !input?.value.trim() || input.value.length > 4000;
        if (input) {
            input.style.height = 'auto';
            input.style.height = `${Math.min(input.scrollHeight || 44, 132)}px`;
        }
    }

    async sendMessage(content = null, messageType = 'text') {
        if (this.isSending || this.closed || !this.hasSelectedConversation) return false;
        const input = document.getElementById('messageInput');
        content = content == null ? input?.value.trim() : content;
        if (!content || content.length > 4000) return false;
        this.isSending = true;
        this.setSendBusy(true);
        const selection = this.selectionRevision;
        const target = this.currentConversationId;
        const reply = this.currentReplyTo;
        try {
            if (!await this.ready || this.closed) return false;
            const result = this.socket?.connected ? await this.socket.request('send_message', {
                ...this.scope(target), content, message_type: messageType,
                ...(reply ? { reply_to_id: Number(reply) } : {})
            }) : await this.api.sendMessage(content, this.sessionId, target, messageType, reply);
            if (this.closed) return false;
            if (selection === this.selectionRevision) {
                this.renderMessage(result);
                if (input?.value.trim() === content && messageType === 'text') {
                    input.value = '';
                    this.drafts.delete(String(target));
                }
                this.cancelReply();
                this.updateTypingStatus(true);
            }
            await this.loadConversations();
            return true;
        } catch (error) {
            if (!this.closed) this.ui.showToast(error.message);
            return false;
        } finally {
            this.isSending = false;
            this.setSendBusy(false);
        }
    }

    async handleFileUpload(file) {
        if (!file || this.isSending || this.closed) return false;
        const selection = this.selectionRevision;
        const target = this.currentConversationId;
        this.isSending = true;
        this.setSendBusy(true);
        try {
            if (!await this.ready || this.closed) return false;
            const result = await this.api.uploadFile(file, this.sessionId, target);
            if (!this.closed && selection === this.selectionRevision) this.renderMessage(result.message);
            return true;
        } catch (error) { this.ui.showToast(error.message); return false; }
        finally { this.isSending = false; this.setSendBusy(false); }
    }

    async loadPinnedMessages(id) {
        if (!this.isNumericConversation(id)) return;
        const selection = this.selectionRevision;
        const data = await this.api.getPinnedMessages(id);
        if (this.closed || selection !== this.selectionRevision) return;
        this.currentPinnedMessageId = data.pinned?.[0]?.id || null;
        if (this.currentPinnedMessageId) this.ui.showPinnedShelf(data.pinned[0].content);
        else document.getElementById('pinnedShelf')?.classList.remove('active');
    }

    async loadParticipants(id) {
        if (!this.isNumericConversation(id)) return;
        const selection = this.selectionRevision;
        const data = await this.api.getParticipants(id);
        if (this.closed || selection !== this.selectionRevision) return;
        this.participants = data.participants || [];
        const list = document.getElementById('groupMembersList');
        const section = document.getElementById('groupMembersSection');
        list?.replaceChildren(...this.participants.map(person => {
            const item = createNode('div', 'info-item');
            item.append(createNode('i', 'fas fa-user-circle'), createNode('span', '', person.nickname || person.name));
            return item;
        }));
        if (section) section.hidden = false;
        this.updateCallAvailability();
    }

    async loadSettings() {
        if (!this.isNumericConversation()) return;
        const selection = this.selectionRevision;
        const data = await this.api.getConversation(this.currentConversationId);
        if (this.closed || selection !== this.selectionRevision) return;
        this.currentConversationType = data.type;
        this.currentConversationRole = this.conversations.find(conv => String(conv.id) === String(data.id))?.role;
        this.ui.renderSettings(data);
        this.updateCallAvailability();
    }

    updateCallAvailability() {
        const numeric = !!this.userId && this.socket?.connected && this.isNumericConversation();
        const direct = numeric && !this.meshCallManager.isBusy && this.currentConversationType === 'private' &&
            this.participants.length === 2;
        const mesh = numeric && !this.callManager.currentCall && !this.meshCallManager.isBusy &&
            this.currentConversationType === 'group' && this.participants.length >= 2 && this.participants.length <= 4;
        const canCall = direct || mesh;
        const canCustomize = this.isNumericConversation() && !!this.userId;
        for (const id of ['btnInfoTheme', 'btnInfoEmoji', 'btnInfoNickname', 'btnInfoMute', 'btnInfoMedia', 'btnInfoFiles']) {
            const button = document.getElementById(id);
            if (button) {
                button.disabled = !canCustomize;
                button.title = canCustomize ? '' : 'Tính năng này dành cho hội thoại của tài khoản đăng nhập';
            }
        }
        for (const id of ['btnCall', 'btnVideo']) {
            const button = document.getElementById(id);
            if (button) {
                button.disabled = !canCall;
                const action = id === 'btnCall' ? 'Gọi thoại' : 'Gọi video';
                button.setAttribute('aria-label', mesh ? `${action} nhóm` : action);
                button.title = canCall ? (mesh ? `${action} nhóm nhỏ` : action) :
                    'Chỉ gọi trong hội thoại riêng tư hai người hoặc nhóm từ hai đến bốn thành viên';
            }
        }
    }

    startCall(video) {
        return this.currentConversationType === 'group'
            ? this.meshCallManager.startCall(video)
            : this.callManager.startCall(video);
    }

    handleReply(id, event) {
        event?.stopPropagation();
        const message = this.messageRecords.get(String(id));
        if (!message) return;
        this.currentReplyTo = id;
        this.ui.showReplyShelf(message.sender_name || 'Người dùng', message.content || 'Tệp đính kèm');
        document.getElementById('messageInput')?.focus();
    }
    cancelReply() { this.currentReplyTo = null; this.ui.hideReplyShelf(); }
    scrollToMessage(id) { findMessage(id)?.scrollIntoView({ block: 'center', behavior: 'smooth' }); }

    updateTypingStatus(forceStop = false) {
        const input = document.getElementById('messageInput');
        if (!this.hasSelectedConversation) return;
        const typing = !forceStop && !!input?.value.trim() && document.activeElement === input;
        clearTimeout(this.typingTimer);
        if (typing !== !!this.isTyping && this.socket?.connected) {
            this.socket.emit(typing ? 'typing' : 'stop_typing', this.scope());
            this.isTyping = typing;
        }
        if (typing) this.typingTimer = setTimeout(() => this.updateTypingStatus(true), 3000);
    }
    async markRead(id = this.currentConversationId) {
        if (this.closed || !this.hasSelectedConversation || !this.isNumericConversation(id) || !this.userId || document.hidden) return;
        const key = String(id);
        if (this.pendingReads.has(key)) return this.pendingReads.get(key);
        const operation = (async () => {
            if (this.socket?.connected) await this.socket.request('mark_read', this.scope(id));
            else await this.api.markAsRead(id);
            if (this.closed) return;
            this.clearUnread(id);
            this.scheduleConversationRefresh();
        })();
        this.pendingReads.set(key, operation);
        try { return await operation; }
        finally { this.pendingReads.delete(key); }
    }

    clearUnread(id) {
        const conversation = this.conversations.find(item => String(item.id) === String(id));
        if (!conversation?.unread_count) return;
        conversation.unread_count = 0;
        ++this.conversationRevision;
        this.refreshConversationList();
    }

    handleMessagesRead(data) {
        if (String(data.user_id) === String(this.userId)) this.clearUnread(data.conversation_id);
        else if (this.isCurrentScope(data)) this.ui.renderSeenStatus(data.user_id);
    }

    showConversationOptions(id, event) {
        event.preventDefault();
        this.contextMenuConvId = id;
        this.ui.showContextMenu('convContextMenu', event);
    }

    showMsgOptions(id, event) {
        event?.preventDefault();
        event?.stopPropagation();
        if (!this.messageRecords.has(String(id))) return;
        this.contextMenuMsgId = id;
        const menu = document.getElementById('msgContextMenu');
        if (!menu) return;
        const canPin = this.isNumericConversation() && this.userId &&
            (this.currentConversationRole === 'admin' || this.conversations.find(conv => String(conv.id) === String(this.currentConversationId))?.created_by === this.userId);
        const pinned = this.messageRecords.get(String(id)).is_pinned ||
            String(this.currentPinnedMessageId) === String(id);
        document.getElementById('ctxPinBtn').hidden = !canPin || pinned;
        document.getElementById('ctxUnpinBtn').hidden = !canPin || !pinned;
        document.getElementById('ctxRecallBtn').hidden = !this.isOwnMessage(this.messageRecords.get(String(id)));
        this.ui.showContextMenu('msgContextMenu', event);
    }
    toggleReactionPopup(id, event) {
        event?.stopPropagation();
        if (!this.userId) { this.ui.showToast('Đăng nhập để thả cảm xúc'); return; }
        document.getElementById(`reactionBar-${id}`)?.classList.toggle('active');
    }
    async reloadReactions(id) {
        const selection = this.selectionRevision;
        const result = await this.api.getHistory(this.sessionId, this.currentConversationId);
        if (this.closed || selection !== this.selectionRevision) return;
        const message = result.messages?.find(item => String(item.id) === String(id));
        if (!message) return;
        this.messageRecords.set(String(id), message);
        this.ui.updateMessageReactions(id, message.reactions);
    }

    async messageAction(event, id, extra = {}) {
        try {
            await this.socket.request(event, { ...this.scope(), message_id: Number(id), ...extra });
            if (['add_reaction', 'remove_reaction'].includes(event)) await this.reloadReactions(id);
            else await Promise.all([this.loadHistory(), this.loadPinnedMessages(this.currentConversationId)]);
            return true;
        } catch (error) { this.ui.showToast(error.message); return false; }
        finally { this.ui.hideContextMenu(); }
    }
    toggleReaction(id, emoji) {
        if (!this.userId) { this.ui.showToast('Đăng nhập để thả cảm xúc'); return; }
        const own = this.messageRecords.get(String(id))?.reactions?.some(reaction =>
            String(reaction.user_id) === String(this.userId) && reaction.emoji === emoji);
        return this.messageAction(own ? 'remove_reaction' : 'add_reaction', id, { emoji });
    }
    reactMsg(emoji) { return this.toggleReaction(this.contextMenuMsgId, emoji); }
    handleRecall() { return this.messageAction('recall_message', this.contextMenuMsgId); }
    handlePin() { return this.messageAction('pin_message', this.contextMenuMsgId); }
    handleUnpin(id = this.contextMenuMsgId) { return this.messageAction('unpin_message', id); }
    handleUnpinCurrent() { return this.handleUnpin(this.currentPinnedMessageId); }
    sendSticker(url) {
        if (!stickerUrl(url)) return;
        document.getElementById('stickerPicker')?.classList.remove('active');
        return this.sendMessage(url, 'sticker');
    }

    async handleSearch(query) {
        clearTimeout(this.searchTimer);
        const request = ++this.searchRevision;
        if (!this.userId) return;
        this.searchTimer = setTimeout(() => this.run(async () => {
            const result = query.length < 2 ? await this.api.getSuggestedUsers() : await this.api.searchUsers(query);
            if (!this.closed && request === this.searchRevision) this.renderSearchResults(result.users || []);
        }), 250);
    }
    async loadSuggestedUsers() {
        if (!this.userId) return;
        const result = await this.api.getSuggestedUsers();
        if (!this.closed) this.renderSearchResults(result.users || [], 'Gợi ý người dùng');
    }
    renderSearchResults(users, title = '') {
        const list = document.getElementById('searchResults');
        if (!list) return;
        list.replaceChildren();
        if (title) list.appendChild(createNode('div', 'section-title', title));
        for (const person of users) {
            const item = createNode('button', 'search-user-item');
            item.type = 'button';
            item.dataset.userId = person.id;
            item.append(createNode('div', 'search-user-avatar', String(person.name || '?')[0]),
                createNode('div', '', person.name || 'Người dùng'));
            item.addEventListener('click', () => this.run(() => this.startDirectChat(person.id, person.name)));
            list.appendChild(item);
        }
        if (!users.length) list.appendChild(createNode('div', 'section-title', 'Không tìm thấy người dùng'));
        if (list) {
            list.classList.add('active');
            document.getElementById('sidebarSearchInput')?.setAttribute('aria-expanded', 'true');
        }
    }
    async startDirectChat(id, name) {
        const result = await this.api.startDirectChat(id);
        document.getElementById('searchResults')?.classList.remove('active');
        await this.loadConversations();
        await this.selectConversation(result.conversation.id, name || 'Người dùng');
    }
    renderGroupUsers(users) {
        const results = document.getElementById('groupMemberResults');
        const selected = document.getElementById('groupSelectedUsers');
        if (!results || !selected) return;
        results.replaceChildren(...users.filter(person => String(person.id) !== String(this.userId)).map(person => {
            const button = createNode('button', 'group-user-option');
            button.type = 'button';
            button.setAttribute('role', 'option');
            const chosen = this.selectedGroupUsers.some(item => String(item.id) === String(person.id));
            button.setAttribute('aria-selected', String(chosen));
            button.append(createNode('span', 'search-user-avatar', String(person.name || '?')[0]),
                createNode('span', '', person.name || 'Người dùng'));
            button.addEventListener('click', () => {
                const index = this.selectedGroupUsers.findIndex(item => String(item.id) === String(person.id));
                if (index >= 0) this.selectedGroupUsers.splice(index, 1);
                else if (this.selectedGroupUsers.length < 3) this.selectedGroupUsers.push(person);
                this.renderGroupUsers(users);
            });
            return button;
        }));
        selected.replaceChildren(...this.selectedGroupUsers.map(person =>
            createNode('span', 'group-selected-user', person.name || 'Người dùng')));
    }

    async loadGroupUsers(query = '') {
        const result = query.trim().length >= 2
            ? await this.api.searchUsers(query.trim())
            : await this.api.getSuggestedUsers();
        this.renderGroupUsers(result.users || []);
    }

    async createGroup() {
        const input = document.getElementById('groupName');
        if (!this.userId || !input.value.trim() || !this.selectedGroupUsers.length) {
            this.ui.showToast('Nhập tên nhóm và chọn ít nhất một thành viên');
            return;
        }
        const result = await this.api.createGroup(input.value.trim(), this.selectedGroupUsers.map(person => person.id));
        this.ui.closeDialog();
        input.value = '';
        this.selectedGroupUsers = [];
        await this.loadConversations();
        await this.selectConversation(result.id, result.name);
    }
    async handleDeleteConv() {
        if (!this.isNumericConversation(this.contextMenuConvId) || !confirm('Rời cuộc trò chuyện này?')) return;
        await this.api.leaveConversation(this.contextMenuConvId);
        if (String(this.currentConversationId) === String(this.contextMenuConvId)) await this.selectConversation(null, 'Hỗ trợ khách hàng');
        await this.loadConversations();
    }
    async handleMarkRead() {
        if (!this.isNumericConversation(this.contextMenuConvId)) return;
        await this.api.markAsRead(this.contextMenuConvId);
        this.clearUnread(this.contextMenuConvId);
        this.ui.hideContextMenu();
    }
    handleEmojiChangeRequest() {
        if (!this.isNumericConversation()) return;
        this.ui.openDialog('emojiDefaultModal');
    }
    async handleDefaultEmojiChange(emoji) {
        await this.socket.request('update_conversation_settings', { ...this.scope(), settings: { default_emoji: emoji } });
        this.ui.closeDialog();
        await this.loadSettings();
    }
    async handleThemeChange(color) {
        if (!this.isNumericConversation()) return;
        await this.socket.request('update_conversation_settings', { ...this.scope(), settings: { theme_color: color } });
        this.ui.applyTheme(color);
        this.ui.closeDialog();
    }
    async handleNicknamePrompt() {
        if (!this.isNumericConversation()) return;
        const data = await this.api.getParticipants(this.currentConversationId);
        const body = document.getElementById('nicknameListBody');
        body.replaceChildren(...data.participants.map(person => {
            const row = createNode('div', 'nickname-item');
            const input = createNode('input', 'nickname-input');
            input.value = person.nickname || person.name;
            input.maxLength = 100;
            input.setAttribute('aria-label', `Biệt danh ${person.name}`);
            const button = createNode('button', 'btn-primary', 'Lưu');
            button.addEventListener('click', () => this.run(() => this.saveNickname(person.id, input.value)));
            row.append(createNode('span', 'nickname-avatar', String(person.name)[0]), input, button);
            return row;
        }));
        this.ui.openDialog('nicknameModal');
    }
    async saveNickname(id, nickname) {
        await this.socket.request('update_participant_settings', { ...this.scope(), user_id: Number(id), settings: { nickname } });
        await this.loadConversations();
        await this.loadParticipants(this.currentConversationId);
    }
    async handleMuteToggle() {
        if (!this.isNumericConversation()) return;
        const own = this.participants.find(person => String(person.id) === String(this.userId));
        await this.api.updateMySettings(this.currentConversationId, { is_muted: !own?.is_muted });
        await this.loadParticipants(this.currentConversationId);
        const text = document.getElementById('muteText');
        if (text) text.textContent = own?.is_muted ? 'Tắt thông báo' : 'Bật thông báo';
    }
    handleProfileClick() { this.ui.showToast('Ứng dụng chưa có trang hồ sơ công khai'); }
    async loadAttachments(type) {
        if (!this.isNumericConversation()) return;
        const data = await this.api.getAttachments(this.currentConversationId, type);
        this.ui.openMediaBrowser(type, data.attachments || []);
    }

    async startRecording() {
        if (!await this.recorder.start()) return;
        document.getElementById('recordingUI').style.display = 'flex';
        this.recordTimer = setInterval(() => { document.getElementById('recordingTimer').textContent = this.recorder.getDuration(); }, 1000);
    }
    resetRecordingUI() {
        clearInterval(this.recordTimer);
        document.getElementById('recordingUI').style.display = 'none';
        document.getElementById('recordingTimer').textContent = '00:00';
    }
    cancelRecording() { this.recorder.cancel(); this.resetRecordingUI(); }
    stopRecording() { this.recorder.stop(); this.resetRecordingUI(); }
    handleAudioRecorded(blob) {
        if (!blob?.size || this.closed) return;
        const extension = blob.type.startsWith('audio/ogg') ? 'ogg' : 'webm';
        return this.handleFileUpload(new File([blob], `voice-message.${extension}`, { type: blob.type }));
    }

    run(operation) {
        try {
            return Promise.resolve(operation()).catch(error => { if (!this.closed) this.ui.showToast(error.message); });
        } catch (error) {
            if (!this.closed) this.ui.showToast(error.message);
            return Promise.resolve();
        }
    }
    initEventListeners() {
        const on = (id, event, action) => document.getElementById(id)?.addEventListener(event,
            data => this.run(() => action(data)), { signal: this.eventController.signal });
        on('btnOpenSupport', 'click', () => this.selectConversation(null, 'Hỗ trợ khách hàng'));
        on('ctxReadConversation', 'click', () => this.handleMarkRead());
        on('ctxLeaveConversation', 'click', () => this.handleDeleteConv());
        const actions = { heart: () => this.reactMsg('❤️'), laugh: () => this.reactMsg('😆'),
            pin: () => this.handlePin(), unpin: () => this.handleUnpin(), recall: () => this.handleRecall() };
        document.querySelectorAll('[data-message-action]').forEach(button => button.addEventListener('click', () => {
            this.run(actions[button.dataset.messageAction]);
        }, { signal: this.eventController.signal }));
        document.querySelectorAll('.info-section-title').forEach(button => button.addEventListener('click', () => {
            const open = button.closest('.info-section').classList.toggle('open');
            button.setAttribute('aria-expanded', String(open));
        }, { signal: this.eventController.signal }));
        on('sendBtn', 'click', () => this.sendMessage());
        on('btnMobileBack', 'click', () => this.ui.showConversationList());
        on('messageInput', 'keydown', event => {
            if (!shouldSendOnEnter(event)) return;
            event.preventDefault();
            return this.sendMessage();
        });
        on('messageInput', 'input', () => { this.updateTypingStatus(); this.updateComposerState(); });
        on('messageInput', 'focus', () => { this.updateTypingStatus(); return this.markRead(); });
        on('messageInput', 'blur', () => this.updateTypingStatus(true));
        on('likeBtn', 'click', () => this.sendMessage(document.getElementById('likeBtn').dataset.emoji || '👍'));
        on('emojiBtn', 'click', () => {
            const open = document.getElementById('emojiPicker').classList.toggle('active');
            document.getElementById('emojiBtn').setAttribute('aria-expanded', String(open));
        });
        for (const [id, type] of [['stickerBtn', 'sticker'], ['gifBtn', 'gif']]) on(id, 'click', () => {
            const picker = document.getElementById('stickerPicker');
            if (this.currentPickerMode !== type || !picker.classList.contains('active')) {
                (type === 'gif' ? renderGifs : renderStickers)('stickerGrid');
                picker.classList.add('active');
            } else picker.classList.remove('active');
            this.currentPickerMode = type;
            document.getElementById(id).setAttribute('aria-expanded', String(picker.classList.contains('active')));
        });
        on('attachFileBtn', 'click', () => document.getElementById('fileInput').click());
        on('attachImageBtn', 'click', () => document.getElementById('imageInput').click());
        for (const id of ['fileInput', 'imageInput']) on(id, 'change', event => this.handleFileUpload(event.target.files[0]));
        on('cancelReplyBtn', 'click', () => this.cancelReply());
        on('closePinnedBtn', 'click', () => document.getElementById('pinnedShelf').classList.remove('active'));
        on('sidebarSearchInput', 'input', event => this.handleSearch(event.target.value.trim()));
        on('sidebarSearchInput', 'focus', () => this.loadSuggestedUsers());
        on('btnCreateGroup', 'click', () => {
            if (!this.userId) return;
            this.selectedGroupUsers = [];
            document.getElementById('groupMemberSearch').value = '';
            this.ui.openDialog('groupModal');
            this.run(() => this.loadGroupUsers());
        });
        on('groupMemberSearch', 'input', event => this.loadGroupUsers(event.target.value));
        document.querySelectorAll('[data-close-modal]').forEach(button => button.addEventListener('click', () => {
            this.ui.closeDialog();
        }, { signal: this.eventController.signal }));
        on('btnSubmitGroup', 'click', () => this.createGroup());
        on('toggleInfoBtn', 'click', () => this.ui.toggleInfoPanel());
        on('closeInfoBtn', 'click', () => {
            document.getElementById('infoPanel')?.classList.remove('panel-open');
            document.getElementById('infoPanel')?.classList.add('hidden');
            document.getElementById('toggleInfoBtn')?.setAttribute('aria-expanded', 'false');
            document.getElementById('toggleInfoBtn')?.focus();
        });
        on('btnInfoProfile', 'click', () => this.handleProfileClick());
        on('btnInfoMute', 'click', () => this.handleMuteToggle());
        on('btnInfoSearch', 'click', () => {
            this.ui.showConversationList();
            document.getElementById('sidebarSearchInput')?.focus();
        });
        on('btnInfoTheme', 'click', () => { if (this.isNumericConversation()) this.ui.openDialog('themeModal'); });
        on('btnInfoEmoji', 'click', () => this.handleEmojiChangeRequest());
        on('btnInfoNickname', 'click', () => this.handleNicknamePrompt());
        on('btnInfoMedia', 'click', () => this.loadAttachments('image'));
        on('btnInfoFiles', 'click', () => this.loadAttachments('file'));
        on('btnCall', 'click', () => this.startCall(false));
        on('btnVideo', 'click', () => this.startCall(true));
        on('micBtn', 'click', () => this.startRecording());
        on('cancelRecordBtn', 'click', () => this.cancelRecording());
        on('sendRecordBtn', 'click', () => this.stopRecording());
        document.querySelectorAll('.theme-option').forEach(choice => choice.addEventListener('click', () => this.run(() => this.handleThemeChange(choice.dataset.color))));
        document.querySelectorAll('.emoji-default-option').forEach(choice => choice.addEventListener('click', () => this.run(() => this.handleDefaultEmojiChange(choice.dataset.emoji))));
        document.addEventListener('click', event => {
            if (!event.target.closest('.search-box')) {
                document.getElementById('searchResults')?.classList.remove('active');
                document.getElementById('sidebarSearchInput')?.setAttribute('aria-expanded', 'false');
            }
            if (!event.target.closest('.context-menu') && !event.target.closest('.message-bubble') && !event.target.closest('.conv-item')) this.ui.hideContextMenu();
            if (!event.target.closest('#emojiBtn') && !event.target.closest('#emojiPicker')) {
                document.getElementById('emojiPicker').classList.remove('active');
                document.getElementById('emojiBtn').setAttribute('aria-expanded', 'false');
            }
        }, { signal: this.eventController.signal });
        document.addEventListener('keydown', event => {
            if (event.key !== 'Escape' || this.callManager.currentCall) return;
            document.getElementById('emojiPicker')?.classList.remove('active');
            document.getElementById('stickerPicker')?.classList.remove('active');
            document.getElementById('emojiBtn')?.setAttribute('aria-expanded', 'false');
        }, { signal: this.eventController.signal });
        window.addEventListener('pagehide', () => this.dispose(), { once: true });
    }
    dispose() {
        if (this.closed) return;
        this.updateTypingStatus(true);
        this.closed = true;
        this.eventController.abort();
        clearTimeout(this.searchTimer);
        clearTimeout(this.conversationTimer);
        clearTimeout(this.typingTimer);
        clearInterval(this.recordTimer);
        this.ui.dispose?.();
        this.recorder.cancel();
        this.viewer.dispose?.();
        this.callManager.dispose();
        this.meshCallManager.dispose();
        this.socket?.close();
    }
}

if (document.getElementById('conversationList')) {
    window.chatApp = new ChatApp(window.chatConfig || {});
    for (const method of ['reactMsg', 'handleRecall', 'handlePin', 'handleUnpin', 'handleDeleteConv', 'handleMarkRead', 'saveNickname']) {
        window[method] = (...args) => window.chatApp.run(() => window.chatApp[method](...args));
    }
    window.endCall = () => window.chatApp.meshCallManager.isBusy
        ? window.chatApp.meshCallManager.endCall()
        : window.chatApp.callManager.endCall();
}
