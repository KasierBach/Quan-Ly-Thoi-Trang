import ChatAPI from './ChatAPI.js';
import ChatUI from '../ui/ChatUI.js';
import ChatSocket from './ChatSocket.js';
import ImageViewer from '../call/StreamViewer.js';
import ChatRecorder from '../media/MediaRecorder.js';
import { createNode, findMessage, initEmojiPicker, renderStickers, renderGifs, stickerUrl } from '../utils/helpers.js';
import { CallManager } from '../call/CallManager.js';

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
            this.initEventListeners();
            initEmojiPicker();
            await this.loadConversations();
            await this.selectConversation(null, 'Hỗ trợ khách hàng');
            this.socket.connect();
            this.setSendBusy(false);
            return true;
        } catch (error) {
            if (!this.closed) {
                const list = document.getElementById('conversationList');
                list?.replaceChildren(createNode('div', 'p-4 text-danger', 'Không thể khởi tạo chat. Hãy tải lại trang.'));
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
        const data = this.userId ? await this.api.getConversations() : { conversations: [] };
        if (this.closed) return;
        this.conversations = data.conversations || [];
        this.ui.renderConversationList(this.conversations, this.currentConversationId,
            (id, name, online) => this.run(() => this.selectConversation(id, name, online)));
    }

    async selectConversation(id, name, online = false) {
        if (this.closed) return;
        const previous = this.currentConversationId;
        if (previous !== id) {
            this.updateTypingStatus(true);
            if (this.socket?.connected) this.socket.emit('leave_conversation', this.scope(previous));
        }
        this.currentConversationId = id == null || id === '' ? null : id;
        const revision = ++this.selectionRevision;
        this.cancelReply();
        this.currentConversationType = null;
        this.currentConversationRole = null;
        this.participants = [];
        this.updateCallAvailability();
        document.getElementById('typingIndicator')?.classList.remove('active');
        document.getElementById('pinnedShelf')?.classList.remove('active');
        this.ui.switchChatUI(name, online, this.currentConversationId);
        this.ui.renderSettings({ default_emoji: '👍' });
        await this.joinCurrentConversation();
        await this.loadHistory();
        if (revision !== this.selectionRevision || this.closed) return;
        await this.loadSettings();
        if (revision !== this.selectionRevision || this.closed) return;
        await this.loadParticipants(this.currentConversationId);
        if (revision !== this.selectionRevision || this.closed) return;
        await this.loadPinnedMessages(this.currentConversationId);
        if (revision === this.selectionRevision && !this.closed) {
            this.ui.renderConversationList(this.conversations, this.currentConversationId,
                (nextId, nextName, nextOnline) => this.run(() => this.selectConversation(nextId, nextName, nextOnline)));
        }
    }

    async joinCurrentConversation() {
        if (!this.socket?.connected || !this.sessionId) return;
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
            for (const message of data.messages || []) this.renderMessage(message);
            if (!data.messages?.length) area?.appendChild(createNode('div', 'chat-empty p-3 text-muted', 'Chưa có tin nhắn nào'));
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
            reply_to_id: message.reply_to_id, parent_content: message.parent_content,
            parent_sender_type: message.parent_sender_type, parent_sender_name: message.parent_sender_name,
        });
    }

    handleNewMessage(data) {
        if (this.closed) return;
        if (this.isCurrentScope(data)) {
            this.renderMessage(data);
            if (document.activeElement === document.getElementById('messageInput')) this.markRead();
        }
        this.run(() => this.loadConversations());
    }

    setSendBusy(busy) {
        for (const id of ['sendBtn', 'likeBtn', 'attachFileBtn', 'attachImageBtn']) {
            const button = document.getElementById(id);
            if (button) button.disabled = busy || !this.sessionId || this.closed;
        }
    }

    async sendMessage(content = null, messageType = 'text') {
        if (this.isSending || this.closed) return false;
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
                if (input?.value.trim() === content && messageType === 'text') input.value = '';
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
        if (section) section.style.display = 'block';
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
        const canCall = !!this.userId && this.socket?.connected && this.isNumericConversation() &&
            this.currentConversationType === 'private' && this.participants.length === 2;
        for (const id of ['btnCall', 'btnVideo']) {
            const button = document.getElementById(id);
            if (button) {
                button.disabled = !canCall;
                button.setAttribute('aria-label', id === 'btnCall' ? 'Gọi thoại' : 'Gọi video');
                button.title = canCall ? (id === 'btnCall' ? 'Gọi thoại' : 'Gọi video') : 'Chỉ gọi trong cuộc trò chuyện riêng tư một-một';
            }
        }
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
        const typing = !forceStop && !!input?.value.trim() && document.activeElement === input;
        clearTimeout(this.typingTimer);
        if (typing !== !!this.isTyping && this.socket?.connected) {
            this.socket.emit(typing ? 'typing' : 'stop_typing', this.scope());
            this.isTyping = typing;
        }
        if (typing) this.typingTimer = setTimeout(() => this.updateTypingStatus(true), 3000);
    }
    markRead() {
        if (this.isNumericConversation() && this.userId && !document.hidden) this.socket?.emit('mark_read', this.scope());
    }
    handleMessagesRead(data) {
        if (String(data.user_id) !== String(this.userId) && this.isCurrentScope(data)) this.ui.renderSeenStatus(data.user_id);
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
        document.getElementById('ctxPinBtn').style.display = canPin ? 'block' : 'none';
        document.getElementById('ctxUnpinBtn').style.display = canPin ? 'block' : 'none';
        menu.style.display = 'block';
        menu.style.left = `${Math.min(event?.clientX || 0, innerWidth - menu.offsetWidth)}px`;
        menu.style.top = `${Math.min(event?.clientY || 0, innerHeight - menu.offsetHeight)}px`;
    }
    toggleReactionPopup(id, event) {
        event?.stopPropagation();
        if (!this.userId) { this.ui.showToast('Đăng nhập để thả cảm xúc'); return; }
        document.getElementById(`reactionBar-${id}`)?.classList.toggle('active');
    }
    async messageAction(event, id, extra = {}) {
        try {
            await this.socket.request(event, { ...this.scope(), message_id: Number(id), ...extra });
            await Promise.all([this.loadHistory(), this.loadPinnedMessages(this.currentConversationId)]);
            return true;
        } catch (error) { this.ui.showToast(error.message); return false; }
        finally { document.getElementById('msgContextMenu').style.display = 'none'; }
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
        if (title) list.appendChild(createNode('div', 'p-2 text-muted', title));
        for (const person of users) {
            const item = createNode('button', 'search-user-item');
            item.type = 'button';
            item.dataset.userId = person.id;
            item.append(createNode('div', 'search-user-avatar', String(person.name || '?')[0]),
                createNode('div', '', person.name || 'Người dùng'));
            item.addEventListener('click', () => this.run(() => this.startDirectChat(person.id, person.name)));
            list.appendChild(item);
        }
        if (!users.length) list.appendChild(createNode('div', 'p-3 text-muted', 'Không tìm thấy người dùng'));
        list.classList.add('active');
    }
    async startDirectChat(id, name) {
        const result = await this.api.startDirectChat(id);
        document.getElementById('searchResults')?.classList.remove('active');
        await this.loadConversations();
        await this.selectConversation(result.conversation.id, name || 'Người dùng');
    }
    async createGroup() {
        const input = document.getElementById('groupName');
        if (!this.userId || !input.value.trim()) return;
        const result = await this.api.createGroup(input.value.trim(), this.selectedGroupUsers.map(person => person.id));
        document.getElementById('groupModal').style.display = 'none';
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
        if (this.isNumericConversation(this.contextMenuConvId)) await this.api.markAsRead(this.contextMenuConvId);
    }
    handleEmojiChangeRequest() {
        if (!this.isNumericConversation()) return;
        document.getElementById('emojiDefaultModal').style.display = 'block';
    }
    async handleDefaultEmojiChange(emoji) {
        await this.socket.request('update_conversation_settings', { ...this.scope(), settings: { default_emoji: emoji } });
        document.getElementById('emojiDefaultModal').style.display = 'none';
        await this.loadSettings();
    }
    async handleThemeChange(color) {
        if (!this.isNumericConversation()) return;
        await this.socket.request('update_conversation_settings', { ...this.scope(), settings: { theme_color: color } });
        this.ui.applyTheme(color);
        document.getElementById('themeModal').style.display = 'none';
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
        document.getElementById('nicknameModal').style.display = 'block';
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
        on('sendBtn', 'click', () => this.sendMessage());
        on('messageInput', 'keydown', event => {
            if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); return this.sendMessage(); }
        });
        on('messageInput', 'input', () => this.updateTypingStatus());
        on('messageInput', 'focus', () => { this.updateTypingStatus(); this.markRead(); });
        on('messageInput', 'blur', () => this.updateTypingStatus(true));
        on('likeBtn', 'click', () => this.sendMessage(document.getElementById('likeBtn').dataset.emoji || '👍'));
        on('emojiBtn', 'click', () => document.getElementById('emojiPicker').classList.toggle('active'));
        for (const [id, type] of [['stickerBtn', 'sticker'], ['gifBtn', 'gif']]) on(id, 'click', () => {
            const picker = document.getElementById('stickerPicker');
            if (this.currentPickerMode !== type || !picker.classList.contains('active')) {
                (type === 'gif' ? renderGifs : renderStickers)('stickerGrid');
                picker.classList.add('active');
            } else picker.classList.remove('active');
            this.currentPickerMode = type;
        });
        on('attachFileBtn', 'click', () => document.getElementById('fileInput').click());
        on('attachImageBtn', 'click', () => document.getElementById('imageInput').click());
        for (const id of ['fileInput', 'imageInput']) on(id, 'change', event => this.handleFileUpload(event.target.files[0]));
        on('cancelReplyBtn', 'click', () => this.cancelReply());
        on('closePinnedBtn', 'click', () => document.getElementById('pinnedShelf').classList.remove('active'));
        on('sidebarSearchInput', 'input', event => this.handleSearch(event.target.value.trim()));
        on('sidebarSearchInput', 'focus', () => this.loadSuggestedUsers());
        on('btnCreateGroup', 'click', () => { if (this.userId) document.getElementById('groupModal').style.display = 'block'; });
        document.querySelectorAll('[data-close-group]').forEach(button => button.addEventListener('click', () => {
            document.getElementById('groupModal').style.display = 'none';
        }, { signal: this.eventController.signal }));
        on('btnSubmitGroup', 'click', () => this.createGroup());
        on('toggleInfoBtn', 'click', () => document.getElementById('infoPanel').classList.toggle('hidden'));
        on('btnInfoProfile', 'click', () => this.handleProfileClick());
        on('btnInfoMute', 'click', () => this.handleMuteToggle());
        on('btnInfoSearch', 'click', () => document.getElementById('sidebarSearchInput').focus());
        on('btnInfoTheme', 'click', () => { if (this.isNumericConversation()) document.getElementById('themeModal').style.display = 'block'; });
        on('btnInfoEmoji', 'click', () => this.handleEmojiChangeRequest());
        on('btnInfoNickname', 'click', () => this.handleNicknamePrompt());
        on('btnInfoMedia', 'click', () => this.loadAttachments('image'));
        on('btnInfoFiles', 'click', () => this.loadAttachments('file'));
        on('btnCall', 'click', () => this.callManager.startCall(false));
        on('btnVideo', 'click', () => this.callManager.startCall(true));
        on('micBtn', 'click', () => this.startRecording());
        on('cancelRecordBtn', 'click', () => this.cancelRecording());
        on('sendRecordBtn', 'click', () => this.stopRecording());
        document.querySelectorAll('.theme-option').forEach(choice => choice.addEventListener('click', () => this.run(() => this.handleThemeChange(choice.dataset.color))));
        document.querySelectorAll('.emoji-default-option').forEach(choice => choice.addEventListener('click', () => this.run(() => this.handleDefaultEmojiChange(choice.dataset.emoji))));
        document.addEventListener('click', event => {
            if (!event.target.closest('.search-box')) document.getElementById('searchResults')?.classList.remove('active');
            if (!event.target.closest('#msgContextMenu') && !event.target.closest('.message-bubble')) document.getElementById('msgContextMenu').style.display = 'none';
            if (!event.target.closest('#emojiBtn') && !event.target.closest('#emojiPicker')) document.getElementById('emojiPicker').classList.remove('active');
        }, { signal: this.eventController.signal });
        window.addEventListener('pagehide', () => this.dispose(), { once: true });
    }
    dispose() {
        if (this.closed) return;
        this.updateTypingStatus(true);
        this.closed = true;
        this.eventController.abort();
        clearTimeout(this.searchTimer);
        clearTimeout(this.typingTimer);
        clearInterval(this.recordTimer);
        this.recorder.cancel();
        this.callManager.dispose();
        this.socket?.close();
    }
}

if (document.getElementById('conversationList')) {
    window.chatApp = new ChatApp(window.chatConfig || {});
    for (const method of ['reactMsg', 'handleRecall', 'handlePin', 'handleUnpin', 'handleDeleteConv', 'handleMarkRead', 'saveNickname']) {
        window[method] = (...args) => window.chatApp.run(() => window.chatApp[method](...args));
    }
    window.endCall = () => window.chatApp.callManager.endCall();
}
