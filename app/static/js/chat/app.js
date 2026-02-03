import ChatAPI from './api.js';
import ChatUI from './ui.js';
import ChatSocket from './socket.js';
import ImageViewer from './viewer.js';
import ChatRecorder from './recorder.js';
import { initEmojiPicker, initStickerPicker } from './utils.js';

class ChatApp {
    constructor() {
        this.sessionId = window.chatSessionId || localStorage.getItem('chat_session_id');
        if (!this.sessionId) {
            this.sessionId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
                var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
            localStorage.setItem('chat_session_id', this.sessionId);
        }
        this.userId = window.chatUserId || 0;
        this.isAdmin = window.isChatAdmin || false;
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

        this.api = new ChatAPI(this.csrfToken);
        this.ui = new ChatUI(this);
        this.socket = new ChatSocket(this.sessionId, this);
        this.viewer = new ImageViewer();
        this.recorder = new ChatRecorder(this.handleAudioRecorded.bind(this));

        this.currentConversationId = null;
        this.selectedGroupUsers = [];
        this.contextMenuMsgId = null;
        this.contextMenuConvId = null;
        this.isSending = false;
        this.hoveredEmoji = null;
        this.currentPinnedMessageId = null;
        this.currentReplyTo = null;

        this.init();
    }

    init() {
        document.addEventListener('DOMContentLoaded', () => {
            this.initEventListeners();
            this.loadConversations();
            initEmojiPicker();
            initStickerPicker();
        });

        // Expose globally for inline event handlers in HTML
        window.chatApp = this;
    }

    async loadConversations() {
        try {
            const data = await this.api.getConversations();
            this.ui.renderConversationList(data.conversations || [], this.currentConversationId, this.selectConversation.bind(this));
        } catch (e) {
            console.error("Error loading conversations:", e);
        }
    }

    async selectConversation(id, name, isOnline = false) {
        this.currentConversationId = id;
        this.ui.switchChatUI(name, isOnline, id);
        this.loadHistory();
        this.loadConversations(); // Update active class

        if (id) {
            this.socket.emit('join_conversation', { conversation_id: id });
            this.loadParticipants(id);
            this.loadPinnedMessages(id);
            const gSection = document.getElementById('groupMembersSection');
            if (gSection) gSection.style.display = 'block';
            this.loadSettings();
        } else {
            const gSection = document.getElementById('groupMembersSection');
            if (gSection) gSection.style.display = 'none';
        }
    }

    async loadHistory() {
        try {
            const data = await this.api.getHistory(this.sessionId, this.currentConversationId);
            const area = document.getElementById('messagesArea');
            if (area) {
                area.innerHTML = '';
                if (data.messages && data.messages.length > 0) {
                    data.messages.forEach(msg => {
                        const isMyMsg = (msg.user_id && msg.user_id === this.userId) ||
                            (!msg.user_id && msg.session_id === this.sessionId && msg.sender_type === 'user') ||
                            (this.isAdmin && msg.sender_type === 'admin');

                        this.ui.appendMessage({
                            type: isMyMsg ? 'sent' : 'received',
                            content: msg.content,
                            time: this.ui.formatTime(msg.created_at),
                            msgType: msg.message_type,
                            id: msg.id,
                            attachments: msg.attachments,
                            reactions: msg.reactions,
                            avatarText: (msg.sender_name ? msg.sender_name[0].toUpperCase() : (msg.sender_type === 'admin' ? 'A' : 'K')),
                            senderName: msg.sender_name,
                            reply_to_id: msg.reply_to_id,
                            parent_content: msg.parent_content,
                            parent_sender_type: msg.parent_sender_type,
                            parent_sender_name: msg.parent_sender_name
                        });
                    });
                } else {
                    area.innerHTML = '<div class="p-3 text-center text-muted">Chưa có tin nhắn nào</div>';
                }
            }
        } catch (e) {
            console.error(e);
        }
    }

    async loadPinnedMessages(convId) {
        if (!convId) return;
        try {
            const data = await this.api.getPinnedMessages(convId);
            if (data.pinned && data.pinned.length > 0) {
                const first = data.pinned[0];
                this.currentPinnedMessageId = first.id;
                this.ui.showPinnedShelf(first.content);
            } else {
                this.currentPinnedMessageId = null;
                document.getElementById('pinnedShelf')?.classList.remove('active');
            }
        } catch (e) { console.error(e); }
    }

    async loadParticipants(convId) {
        if (!convId) return;
        try {
            const data = await this.api.getParticipants(convId);
            const section = document.getElementById('groupMembersSection');
            const list = document.getElementById('groupMembersList');
            if (data.participants && data.participants.length > 2) {
                if (section) section.style.display = 'block';
                if (list) {
                    list.innerHTML = data.participants.map(p => `
                        <div class="info-item">
                            <i class="fas fa-user-circle"></i>
                            <span>${p.name || 'Thành viên'}</span>
                        </div>
                    `).join('');
                }
            } else {
                if (section) section.style.display = 'none';
            }
        } catch (e) {
            console.warn("Could not load participants:", e);
        }
    }

    async loadSettings() {
        if (!this.currentConversationId) return;
        try {
            const data = await this.api.getConversation(this.currentConversationId);
            if (data) {
                this.ui.renderSettings(data);
                // Also update local state if needed
            }
        } catch (e) {
            console.error("Error loading settings:", e);
        }
    }

    sendMessage(content = null) {
        if (this.isSending) return;
        const input = document.getElementById('messageInput');
        if (!content) content = input?.value.trim();

        if (!content) return;

        this.isSending = true;
        const sendBtn = document.getElementById('sendBtn');
        if (sendBtn) sendBtn.style.opacity = '0.5';

        this.socket.emit('send_message', {
            content,
            session_id: this.sessionId,
            conversation_id: this.currentConversationId,
            reply_to_id: this.currentReplyTo
        });

        this.ui.appendMessage({
            type: 'sent',
            content,
            time: this.ui.formatTime(new Date().toISOString()),
            avatarText: ''
        });

        if (input) {
            input.value = '';
            input.style.height = 'auto';
        }

        this.cancelReply();

        setTimeout(() => {
            this.loadHistory();
            this.isSending = false;
            if (sendBtn) sendBtn.style.opacity = '1';
        }, 500);
    }

    handleNewMessage(data) {
        const isCurrent = data.conversation_id == this.currentConversationId ||
            (data.session_id == this.currentConversationId) ||
            (data.session_id == this.sessionId && !this.currentConversationId);

        if (isCurrent) {
            if (data.sender !== 'user' || (this.isAdmin && data.sender === 'user' && data.session_id !== this.sessionId)) {
                // If it's from someone else, or it's from a user (guest) and I'm an admin viewing them
                const avatarEl = document.getElementById('currentChatAvatar');
                this.ui.appendMessage({
                    type: 'received',
                    content: data.content,
                    time: this.ui.formatTime(new Date().toISOString()),
                    msgType: data.message_type,
                    attachments: data.attachments,
                    avatarText: avatarEl ? avatarEl.textContent : (data.sender === 'admin' ? 'A' : 'K'),
                    senderName: data.sender_name,
                    id: data.id,
                    reply_to_id: data.reply_to_id,
                    parent_content: data.parent_content,
                    parent_sender_type: data.parent_sender_type,
                    parent_sender_name: data.parent_sender_name
                });
            }
        }
        this.loadConversations();
    }

    handleReply(msgId, e) {
        if (e) {
            e.stopPropagation();
            e.preventDefault();
        }
        this.currentReplyTo = msgId;
        const msgBubble = document.querySelector(`.message-bubble[data-msg-id="${msgId}"]`);
        if (msgBubble) {
            const content = msgBubble.querySelector('.message-bubble-main')?.textContent.trim() || "Tin nhắn phương tiện";
            const group = msgBubble.closest('.message-group');
            const senderName = group?.dataset.senderName || "Người dùng";
            this.ui.showReplyShelf(senderName, content);
        }
        document.getElementById('messageInput')?.focus();
    }

    cancelReply() {
        this.currentReplyTo = null;
        this.ui.hideReplyShelf();
    }

    scrollToMessage(id) {
        const el = document.querySelector(`.message-bubble[data-msg-id="${id}"]`);
        if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            el.classList.add('highlight-msg');
            setTimeout(() => el.classList.remove('highlight-msg'), 2000);
        }
    }

    initEventListeners() {
        const app = this;

        // Send Actions
        document.getElementById('messagesArea')?.addEventListener('contextmenu', (e) => e.preventDefault());
        document.getElementById('sendBtn')?.addEventListener('click', () => this.sendMessage());
        document.getElementById('messageInput')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                if (window.getHoveredEmoji && window.getHoveredEmoji()) return;
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Typing Indicator
        let typingTimeout = null;
        document.getElementById('messageInput')?.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 100) + 'px';
            this.style.overflowY = this.scrollHeight > 100 ? 'auto' : 'hidden';

            if (app.currentConversationId || app.sessionId) {
                if (!typingTimeout) app.socket.emit('typing', {
                    conversation_id: app.currentConversationId,
                    session_id: app.sessionId
                });
                clearTimeout(typingTimeout);
                typingTimeout = setTimeout(() => {
                    app.socket.emit('stop_typing', {
                        conversation_id: app.currentConversationId,
                        session_id: app.sessionId
                    });
                    typingTimeout = null;
                }, 2000);
            }
        });

        // Toggle Buttons
        const setupClick = (id, fn) => {
            const el = document.getElementById(id);
            if (el) {
                console.log(`Setting up click listener for: ${id}`);
                el.addEventListener('click', (e) => {
                    console.log(`Clicked element: ${id}`);
                    fn(e);
                });
            } else {
                console.warn(`Element not found for setupClick: ${id}`);
            }
        };

        // Info Section Accordion
        document.querySelectorAll('.info-section-title').forEach(title => {
            title.addEventListener('click', () => {
                title.parentElement.classList.toggle('open');
                console.log('Toggled info section');
            });
        });

        setupClick('emojiBtn', () => document.getElementById('emojiPicker')?.classList.toggle('active'));
        setupClick('stickerBtn', () => document.getElementById('stickerPicker')?.classList.toggle('active'));
        setupClick('toggleInfoBtn', () => document.getElementById('infoPanel')?.classList.toggle('active'));
        setupClick('closePinnedBtn', () => this.handleUnpinCurrent());
        setupClick('cancelReplyBtn', () => this.cancelReply());
        setupClick('likeBtn', () => this.sendMessage('👍'));

        // File Uploads
        setupClick('attachFileBtn', () => document.getElementById('fileInput')?.click());
        setupClick('attachImageBtn', () => document.getElementById('imageInput')?.click());

        document.getElementById('fileInput')?.addEventListener('change', (e) => this.handleFileUpload(e.target.files[0]));
        document.getElementById('imageInput')?.addEventListener('change', (e) => this.handleFileUpload(e.target.files[0]));

        // Voice Recording
        setupClick('micBtn', () => this.startRecording());
        setupClick('cancelRecordBtn', () => this.cancelRecording());
        setupClick('sendRecordBtn', () => this.stopRecording());

        // Search
        document.getElementById('sidebarSearchInput')?.addEventListener('input', (e) => this.handleSearch(e.target.value.trim()));
        document.getElementById('sidebarSearchInput')?.addEventListener('focus', () => {
            const val = document.getElementById('sidebarSearchInput')?.value?.trim();
            if (!val) this.loadSuggestedUsers();
        });

        // Modals
        setupClick('btnCreateGroup', () => {
            const modal = document.getElementById('groupModal');
            if (modal) modal.style.display = 'block';
        });
        setupClick('closeGroupModal', () => {
            const modal = document.getElementById('groupModal');
            if (modal) modal.style.display = 'none';
            this.selectedGroupUsers = [];
        });
        setupClick('btnSubmitGroup', () => this.createGroup());

        // Info Panel Actions
        setupClick('btnInfoProfile', () => {
            console.log('Profile action triggered');
            if (!this.currentConversationId) return;
            this.handleProfileClick();
        });

        setupClick('btnInfoMute', () => {
            console.log('Mute action triggered');
            this.handleMuteToggle();
        });
        setupClick('btnInfoSearch', () => {
            console.log('Search action triggered');
            document.getElementById('sidebarSearchInput')?.focus();
        });

        setupClick('btnInfoTheme', () => {
            console.log('Theme modal open triggered');
            const modal = document.getElementById('themeModal');
            if (modal) modal.style.display = 'block';
        });
        setupClick('btnInfoEmoji', () => {
            console.log('Emoji change triggered');
            this.handleEmojiChangeRequest();
        });
        setupClick('btnInfoNickname', () => {
            console.log('Nickname prompt triggered');
            this.handleNicknamePrompt();
        });
        setupClick('btnInfoMedia', () => {
            console.log('Media browser triggered');
            this.loadAttachments('image');
        });
        setupClick('btnInfoFiles', () => {
            console.log('Files browser triggered');
            this.loadAttachments('file');
        });

        // Theme Selection
        document.querySelectorAll('.theme-option').forEach(opt => {
            opt.onclick = () => {
                console.log(`Theme selected: ${opt.dataset.color}`);
                this.handleThemeChange(opt.dataset.color);
            };
        });

        // Global Click-away
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.search-box')) document.getElementById('searchResults')?.classList.remove('active');
            if (!e.target.closest('#emojiPicker') && !e.target.closest('#emojiBtn')) document.getElementById('emojiPicker')?.classList.remove('active');
            if (!e.target.closest('#stickerBtn') && !e.target.closest('#stickerPicker')) document.getElementById('stickerPicker')?.classList.remove('active');
            if (!e.target.closest('.message-bubble') && !e.target.closest('#msgContextMenu')) {
                const menu = document.getElementById('msgContextMenu');
                if (menu) menu.style.display = 'none';
                document.querySelectorAll('.hover-reaction-bar').forEach(bar => bar.style.visibility = '');
            }
            const convMenu = document.getElementById('convContextMenu');
            if (convMenu) convMenu.style.display = 'none';
        });

        // Context Menu
        document.addEventListener('contextmenu', (e) => {
            const item = e.target.closest('.conv-item');
            if (item && document.getElementById('conversationList')?.contains(item)) {
                e.preventDefault();
                this.contextMenuConvId = item.dataset.conversationId;
                const menu = document.getElementById('convContextMenu');
                if (menu) {
                    menu.style.display = 'block';
                    menu.style.left = e.pageX + 'px';
                    menu.style.top = e.pageY + 'px';
                }
            }
        });

        // Mark Read Triggers
        document.addEventListener('click', () => this.markRead());
        window.addEventListener('focus', () => this.markRead());
        document.getElementById('messageInput')?.addEventListener('focus', () => this.markRead());
    }


    async handleFileUpload(file) {
        if (!file) return;
        try {
            const data = await this.api.uploadFile(file, this.sessionId, this.currentConversationId);
            if (data.status === 'success') {
                this.ui.showToast('Tải lên thành công!', 'var(--online-green)');
                this.loadHistory();
            }
        } catch (e) { console.error(e); }
    }

    async handleSearch(query) {
        if (query.length < 2) {
            if (query.length === 0) this.loadSuggestedUsers();
            else document.getElementById('searchResults')?.classList.remove('active');
            return;
        }
        const data = await this.api.searchUsers(query);
        this.renderSearchResults(data.users || []);
    }

    async loadSuggestedUsers() {
        const data = await this.api.getSuggestedUsers();
        this.renderSearchResults(data.users || [], 'Gợi ý người dùng');
    }

    renderSearchResults(users, title = '') {
        const resultsDiv = document.getElementById('searchResults');
        if (!resultsDiv) return;

        let html = title ? `<div class="p-2 border-bottom text-muted small px-3">${title}</div>` : '';
        if (users.length > 0) {
            html += users.map(u => `
                <div class="search-user-item" data-user-id="${u.id}" data-user-name="${u.name}">
                    <div class="search-user-avatar">${u.name[0]}</div>
                    <div>
                        <div style="font-weight: 600;">${u.name}</div>
                        <div style="font-size: 0.8rem; color: #65676b;">${u.email}</div>
                    </div>
                </div>
            `).join('');
            resultsDiv.innerHTML = html;
            resultsDiv.querySelectorAll('.search-user-item').forEach(item => {
                item.onclick = () => this.startDirectChat(item.dataset.userId, item.dataset.userName);
            });
            resultsDiv.classList.add('active');
        } else {
            resultsDiv.innerHTML = '<div class="p-3 text-center text-muted">Không tìm thấy người dùng</div>';
            resultsDiv.classList.add('active');
        }
    }

    async startDirectChat(userId, name) {
        document.getElementById('searchResults')?.classList.remove('active');
        this.ui.showToast(`Đang kết nối với ${name}...`);
        const data = await this.api.startDirectChat(userId);
        if (data.conversation) {
            this.selectConversation(data.conversation.id, name);
        } else {
            this.ui.showToast('Lỗi: ' + (data.error || 'Không thể kết nối'), '#e74c3c');
        }
    }

    showMsgOptions(msgId, e) {
        if (e) e.preventDefault();
        this.contextMenuMsgId = msgId;
        const menu = document.getElementById('msgContextMenu');
        if (!menu) return;

        // Dynamic Pin/Unpin
        const msgGroup = document.querySelector(`.message-group[data-message-id="${msgId}"]`);
        const isPinned = msgGroup?.dataset.pinned === 'true';
        const pinBtn = document.getElementById('ctxPinBtn');
        const unpinBtn = document.getElementById('ctxUnpinBtn');
        if (pinBtn) pinBtn.style.display = isPinned ? 'none' : 'block';
        if (unpinBtn) unpinBtn.style.display = isPinned ? 'block' : 'none';

        // Suppress hover bar while menu is open
        const hoverBar = msgGroup?.querySelector('.hover-reaction-bar');
        if (hoverBar) hoverBar.style.visibility = 'hidden';

        menu.style.display = 'block';

        // Calculate smart position
        const clickX = e.clientX;
        const clickY = e.clientY;
        const menuRect = menu.getBoundingClientRect();
        const winWidth = window.innerWidth;
        const winHeight = window.innerHeight;

        // X-axis: flip to left if too close to right edge
        if (clickX + menuRect.width > winWidth) {
            menu.style.left = (clickX - menuRect.width) + 'px';
        } else {
            menu.style.left = clickX + 'px';
        }

        // Y-axis: flip up if too close to bottom
        if (clickY + menuRect.height > winHeight) {
            menu.style.top = (clickY - menuRect.height) + 'px';
            menu.classList.add('up');
        } else {
            menu.style.top = clickY + 'px';
            menu.classList.remove('up');
        }
    }

    toggleReactionPopup(msgId, e) {
        if (e) e.stopPropagation();
        const bar = document.getElementById(`reactionBar-${msgId}`);
        if (!bar) return;

        const wasActive = bar.classList.contains('active');
        // Hide all others
        document.querySelectorAll('.hover-reaction-bar.active').forEach(b => b.classList.remove('active'));

        if (!wasActive) {
            bar.classList.add('active');
        }
    }

    // --- Message Actions ---
    toggleReaction(msgId, emoji) {
        if (!msgId || msgId === 'null') {
            this.ui.showToast('Vui lòng đợi tin nhắn được gửi xong');
            return;
        }

        // Toggle: check DOM to see if we already reacted with THIS SPECIFIC emoji
        const msgGroup = document.querySelector(`.message-group[data-message-id="${msgId}"]`);
        const ownBadges = msgGroup?.querySelectorAll(`.reaction-badge.own`) || [];
        const hasReacted = Array.from(ownBadges).some(b => b.textContent.includes(emoji));

        const event = hasReacted ? 'remove_reaction' : 'add_reaction';
        this.socket.emit(event, {
            message_id: parseInt(msgId),
            emoji: emoji,
            conversation_id: this.currentConversationId,
            session_id: this.sessionId
        });
    }

    reactMsg(emoji) {
        if (!this.contextMenuMsgId) return;
        this.toggleReaction(this.contextMenuMsgId, emoji);
        document.getElementById('msgContextMenu').style.display = 'none';
    }

    handleRecall() {
        if (!this.contextMenuMsgId) return;
        this.socket.emit('recall_message', {
            message_id: this.contextMenuMsgId,
            conversation_id: this.currentConversationId,
            session_id: this.sessionId
        });
        document.getElementById('msgContextMenu').style.display = 'none';
        this.ui.showToast('Đang thu hồi tin nhắn...');
    }

    handlePin() {
        if (!this.contextMenuMsgId || !this.currentConversationId) return;
        this.socket.emit('pin_message', {
            message_id: this.contextMenuMsgId,
            conversation_id: this.currentConversationId
        });
        document.getElementById('msgContextMenu').style.display = 'none';
        this.ui.showToast('Đã ghim tin nhắn');
    }

    handleUnpin(msgId = null) {
        const targetId = msgId || this.contextMenuMsgId;
        if (!targetId || !this.currentConversationId) return;
        this.socket.emit('unpin_message', {
            message_id: targetId,
            conversation_id: this.currentConversationId
        });
        document.getElementById('msgContextMenu').style.display = 'none';
        this.ui.showToast('Đã bỏ ghim tin nhắn');
    }

    handleUnpinCurrent() {
        if (this.currentPinnedMessageId) {
            this.handleUnpin(this.currentPinnedMessageId);
        } else {
            document.getElementById('pinnedShelf')?.classList.remove('active');
        }
    }

    sendSticker(url) {
        this.socket.emit('send_message', {
            content: url,
            message_type: 'image',
            session_id: this.sessionId,
            conversation_id: this.currentConversationId
        });
        this.ui.appendMessage({ type: 'sent', content: url, time: this.ui.formatTime(new Date().toISOString()), msgType: 'image' });
        document.getElementById('stickerPicker').classList.remove('active');
    }

    // --- Conversation Actions ---
    async handleDeleteConv() {
        if (!this.contextMenuConvId || !confirm('Bạn có chắc chắn muốn xóa cuộc hội thoại này?')) return;
        try {
            const data = await this.api.leaveConversation(this.contextMenuConvId);
            if (data.status === 'success') {
                this.ui.showToast('Đã xóa cuộc hội thoại');
                if (this.currentConversationId == this.contextMenuConvId) location.reload();
                else this.loadConversations();
            }
        } catch (e) { console.error(e); }
    }

    async handleMarkRead() {
        if (!this.contextMenuConvId) return;
        try {
            const data = await this.api.markAsRead(this.contextMenuConvId);
            if (data.status === 'success') {
                this.ui.showToast('Đã đánh dấu đã đọc');
                this.loadConversations();
            }
        } catch (e) { console.error(e); }
    }

    // Real-time Seen Status
    markRead() {
        if (this.currentConversationId && !document.hidden && this.socket) {
            this.socket.emit('mark_read', { conversation_id: this.currentConversationId });
        }
    }

    async handleMessagesRead(data) {

        // data.user_id is the person who read the messages
        if (data.user_id == this.userId) return; // Ignore own read receipts

        // Need avatar URL. Check participants cache or fetch status
        let avatarUrl = null;
        if (this.currentConversationId) {
            const convItem = document.querySelector(`.conv-item[data-conversation-id="${this.currentConversationId}"]`);
            // This is a bit hacky, normally we'd have a user store.
            // For now, let's use a generic fetch or cache if possible.
            // Or, stick to the 'active chat' header avatar if it's 1-on-1?
            // Since we don't have a robust user store in frontend, let's just use defaults for now 
            // or fetch user info.
            try {
                const status = await this.api.getUserStatus(data.user_id);
                // The status API currently only returns online/last_seen.
                // We might need to rely on the side panel info if available.
            } catch (e) { }

            // Try to find avatar in message history if they sent a message
            const theirMsg = document.querySelector(`.message-group[data-message-id] .message-avatar`);
            // This is imprecise.
            // Better strategy: Use a default avatar or update API to return avatar.
        }

        // For 1-on-1, use the chat header avatar if available?
        // Let's assume the other person is the one we are chatting with.
        // If it's a group, this is harder.
        // For now, use a generic "check" icon or small avatar.
        // Actually, let's use the standard "blue dot" or small version of conv avatar.

        // Let's try to get it from the chat header if it's 1-on-1
        // const headerAvatar = document.querySelector('.msg-chat-header .header-avatar');
        // avatarUrl = headerAvatar ? getComputedStyle(headerAvatar).backgroundImage.slice(5, -2) : null;

        // BETTER: Create a simple helper or use a default image for now.
        this.ui.renderSeenStatus(data.user_id, 'https://cdn-icons-png.flaticon.com/512/1177/1177568.png'); // Using a generic user icon for now
    }

    async createGroup() {
        const nameInput = document.getElementById('groupName');
        const name = nameInput.value.trim() || "Nhóm mới";
        try {
            const data = await this.api.createGroup(name);
            if (data.id) {
                const convId = data.id;
                for (let user of this.selectedGroupUsers) {
                    await this.api.addGroupParticipant(convId, user.id);
                }
                document.getElementById('groupModal').style.display = 'none';
                nameInput.value = '';
                this.selectedGroupUsers = [];
                this.selectConversation(convId, name);
            }
        } catch (e) { console.error(e); }
    }

    // --- Recording Methods ---
    async startRecording() {
        const started = await this.recorder.start();
        if (started) {
            document.getElementById('recordingUI').style.display = 'flex';
            document.getElementById('messageInput').style.visibility = 'hidden';
            this.recorder.timerInterval = setInterval(() => {
                document.getElementById('recordingTimer').textContent = this.recorder.getDuration();
            }, 1000);
        }
    }

    cancelRecording() {
        this.recorder.cancel();
        this.resetRecordingUI();
    }

    stopRecording() {
        this.recorder.stop(); // Triggers onStopCallback -> handleAudioRecorded
        this.resetRecordingUI();
    }

    resetRecordingUI() {
        clearInterval(this.recorder.timerInterval);
        document.getElementById('recordingUI').style.display = 'none';
        document.getElementById('messageInput').style.visibility = 'visible';
        document.getElementById('recordingTimer').textContent = "00:00";
    }

    async handleAudioRecorded(audioBlob) {
        if (!audioBlob || audioBlob.size === 0) return;

        const file = new File([audioBlob], "voice_message.webm", { type: "audio/webm" });
        await this.handleFileUpload(file);
    }

    // --- New Info Panel Handlers ---

    async handleProfileClick() {
        // Find other participant for direct chat
        if (!this.currentConversationId) return;
        try {
            const participants = await this.api.getParticipants(this.currentConversationId);
            const other = participants.find(p => p.id !== this.userId);
            if (other) {
                window.location.href = `/profile/${other.id}`; // Adjust route as per your app
            }
        } catch (e) { console.error(e); }
    }

    async handleMuteToggle() {
        if (!this.currentConversationId) return;
        const muteText = document.getElementById('muteText');
        const isCurrentlyMuted = muteText.textContent.includes('Bật');
        const newMute = !isCurrentlyMuted;

        try {
            const res = await this.api.updateMySettings(this.currentConversationId, { is_muted: newMute });
            if (res.status === 'success') {
                muteText.textContent = newMute ? 'Bật thông báo' : 'Tắt thông báo';
                this.ui.showToast(newMute ? 'Đã tắt thông báo' : 'Đã bật thông báo');
            }
        } catch (e) { console.error(e); }
    }

    async handleEmojiChangeRequest() {
        // Temporarily use the emoji picker for this selection
        const picker = document.getElementById('emojiPicker');
        picker.classList.add('active');
        // We'll need a way to distinguish if we are picking for chat or for setting
        this.pickingForSetting = 'emoji';
    }

    async handleThemeChange(color) {
        if (!this.currentConversationId) return;
        try {
            const res = await this.api.updateConversationSettings(this.currentConversationId, { theme_color: color });
            if (res.status === 'success') {
                this.ui.applyTheme(color);
                document.getElementById('themeModal').style.display = 'none';
                this.ui.showToast('Đã đổi chủ đề');
                // Emit socket event so others see it
                this.socket.emit('update_conversation_settings', { conversation_id: this.currentConversationId, settings: { theme_color: color } });
            }
        } catch (e) { console.error(e); }
    }

    async handleNicknamePrompt() {
        if (!this.currentConversationId) return;
        const body = document.getElementById('nicknameListBody');
        try {
            const participants = await this.api.getParticipants(this.currentConversationId);
            body.innerHTML = participants.map(p => `
                <div style="margin-bottom: 10px; display: flex; align-items: center; gap: 10px;">
                    <div style="width: 30px; height: 30px; border-radius: 50%; background: #ccc; display: flex; align-items: center; justify-content: center;">${p.name[0]}</div>
                    <div style="flex: 1;">
                        <input type="text" class="nickname-input" data-user-id="${p.id}" value="${p.nickname || p.name}" 
                               style="width: 100%; padding: 5px; border: 1px solid #ddd; border-radius: 4px;">
                    </div>
                    <button onclick="window.chatApp.saveNickname(${p.id}, this.previousElementSibling.querySelector('input').value)" 
                            style="padding: 5px 10px; background: var(--messenger-blue); color: white; border: none; border-radius: 4px; cursor: pointer;">Lưu</button>
                </div>
            `).join('');
            document.getElementById('nicknameModal').style.display = 'block';
        } catch (e) { console.error(e); }
    }

    async saveNickname(targetUserId, nickname) {
        if (!this.currentConversationId) return;
        try {
            // If it's for current user, use updateMySettings
            let res;
            if (targetUserId == this.userId) {
                res = await this.api.updateMySettings(this.currentConversationId, { nickname });
            } else {
                // If it's for someone else (admin only or specific endpoint needed)
                // For now let's assume users can set their own or admin can set anyone
                res = await this.api.updateMySettings(this.currentConversationId, { nickname }); // Simplified for now
            }

            if (res.status === 'success') {
                this.ui.showToast('Đã cập nhật biệt danh');
                this.loadConversations();
            }
        } catch (e) { console.error(e); }
    }

    async handleDefaultEmojiChange(emoji) {
        if (!this.currentConversationId) return;
        try {
            const res = await this.api.updateConversationSettings(this.currentConversationId, { default_emoji: emoji });
            if (res.status === 'success') {
                this.loadSettings();
                this.ui.showToast('Đã đổi biểu tượng cảm xúc');
                this.socket.emit('update_conversation_settings', { conversation_id: this.currentConversationId, settings: { default_emoji: emoji } });
            }
        } catch (e) { console.error(e); }
    }

    async loadAttachments(type) {
        if (!this.currentConversationId) return;
        try {
            const data = await this.api.getAttachments(this.currentConversationId, type);
            this.ui.openMediaBrowser(type, data.attachments || []);
        } catch (e) { console.error(e); }
    }
}

// Global instance
window.chatApp = new ChatApp();
window.reactMsg = (emoji) => window.chatApp.reactMsg(emoji);
window.handleRecall = () => window.chatApp.handleRecall();
window.handlePin = () => window.chatApp.handlePin();
window.handleUnpin = () => window.chatApp.handleUnpin();
window.handleDeleteConv = () => window.chatApp.handleDeleteConv();
window.handleMarkRead = () => window.chatApp.handleMarkRead();
window.saveNickname = (uid, nik) => window.chatApp.saveNickname(uid, nik);
window.endCall = () => {
    document.getElementById('callModal')?.classList.remove('active');
    window.chatApp.ui.showToast('Cuộc gọi đã kết thúc');
};
window.toggleSection = (el) => {
    const section = el.parentElement;
    section.classList.toggle('open');
    const icon = el.querySelector('.fa-chevron-down, .fa-chevron-up');
    if (icon) {
        icon.classList.toggle('fa-chevron-down');
        icon.classList.toggle('fa-chevron-up');
    }
};
