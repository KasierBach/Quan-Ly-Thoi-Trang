import { createNode, escapeHtml, findMessage, stickerUrl } from '../utils/helpers.js';

/** Colorful chat UI; persisted content is always text or validated DOM properties. */
class ChatUI {
    constructor(app) {
        this.app = app;
        this.openDialogId = null;
        this.dialogReturnFocus = null;
        this.eventController = new AbortController();
        document.addEventListener('keydown', event => this.handleDialogKeydown(event), { signal: this.eventController.signal });
    }

    showContextMenu(id, event) {
        this.hideContextMenu();
        const menu = document.getElementById(id);
        if (!menu) return;
        const anchor = event?.currentTarget?.getBoundingClientRect?.();
        const left = event?.clientX || anchor?.left || 8;
        const top = event?.clientY || anchor?.bottom || 8;
        this.contextReturnFocus = document.activeElement;
        this.contextMenuId = id;
        menu.style.display = 'block';
        menu.style.left = `${Math.max(8, Math.min(left, window.innerWidth - menu.offsetWidth - 8))}px`;
        menu.style.top = `${Math.max(8, Math.min(top, window.innerHeight - menu.offsetHeight - 8))}px`;
        menu.querySelector('button:not([hidden])')?.focus();
    }

    hideContextMenu() {
        for (const id of ['msgContextMenu', 'convContextMenu']) {
            const menu = document.getElementById(id);
            if (menu) menu.style.display = 'none';
        }
        this.contextMenuId = null;
    }

    handleDialogKeydown(event) {
        if (this.contextMenuId) {
            const menu = document.getElementById(this.contextMenuId);
            const options = Array.from(menu?.querySelectorAll('button:not([hidden])') || []);
            if (event.key === 'Escape') {
                event.preventDefault();
                this.hideContextMenu();
                this.contextReturnFocus?.focus();
            } else if (['ArrowDown', 'ArrowUp'].includes(event.key) && options.length) {
                event.preventDefault();
                const direction = event.key === 'ArrowDown' ? 1 : -1;
                const index = options.indexOf(document.activeElement);
                options[(index + direction + options.length) % options.length].focus();
            }
            return;
        }
        const dialog = document.getElementById(this.openDialogId);
        if (!dialog) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            this.closeDialog();
            return;
        }
        if (event.key !== 'Tab') return;
        const targets = Array.from(dialog.querySelectorAll('button:not([disabled]), input:not([disabled]), a[href], [tabindex="0"]'))
            .filter(element => !element.hidden && element.getClientRects().length > 0);
        if (!targets.length) { event.preventDefault(); dialog.focus(); return; }
        const first = targets[0], last = targets[targets.length - 1];
        if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    }

    openDialog(id) {
        const dialog = document.getElementById(id);
        if (!dialog) return;
        this.dialogReturnFocus = document.activeElement;
        this.openDialogId = id;
        dialog.style.display = 'block';
        dialog.setAttribute('aria-hidden', 'false');
        dialog.querySelector('input:not([disabled]), button:not([disabled])')?.focus();
    }

    closeDialog() {
        const dialog = document.getElementById(this.openDialogId);
        if (dialog) {
            dialog.style.display = 'none';
            dialog.setAttribute('aria-hidden', 'true');
        }
        this.openDialogId = null;
        if (this.dialogReturnFocus?.isConnected) this.dialogReturnFocus.focus();
    }

    dispose() {
        this.eventController.abort();
        clearTimeout(this.toastTimer);
        document.getElementById('chatToast')?.remove();
    }

    get messagesArea() { return document.getElementById('messagesArea'); }
    get conversationList() { return document.getElementById('conversationList'); }
    get activeChatContainer() { return document.getElementById('activeChatContainer'); }
    get welcomeScreen() { return document.getElementById('welcomeScreen'); }
    get pinnedShelf() { return document.getElementById('pinnedShelf'); }
    get pinnedContent() { return document.getElementById('pinnedContent'); }
    get messageInput() { return document.getElementById('messageInput'); }

    renderConversationList(conversations, currentId, onSelect) {
        if (!this.conversationList) return;
        this.conversationList.setAttribute('aria-busy', 'false');
        const selected = document.activeElement?.dataset?.conversationId;
        this.conversationList.replaceChildren(this.createConversationItem({
            id: null, name: 'Hỗ trợ khách hàng', last_message: 'Chat với đội ngũ hỗ trợ',
            is_support: true, active: this.app.hasSelectedConversation && currentId === null
        }, onSelect));
        if (!conversations.length) this.renderEmptyConversations();
        for (const conv of conversations) {
            this.conversationList.appendChild(this.createConversationItem({
                ...conv, active: this.app.hasSelectedConversation && String(currentId) === String(conv.id)
            }, onSelect));
        }
        if (selected !== undefined) {
            const item = Array.from(this.conversationList.children).find(element => element.dataset.conversationId === selected);
            item?.focus({ preventScroll: true });
        }
    }

    createConversationItem(conv, onSelect) {
        const count = Number(conv.unread_count);
        const unread = Number.isSafeInteger(count) && count > 0 ? count : 0;
        const item = createNode('button', `conv-item${conv.active ? ' active' : ''}${unread ? ' unread' : ''}`);
        item.type = 'button';
        item.setAttribute('aria-pressed', String(!!conv.active));
        item.dataset.conversationId = conv.id ?? '';
        const name = String(conv.name || 'Người dùng');
        const avatar = createNode('span', `conv-avatar${conv.is_support ? ' support-avatar' : ''}`);
        if (conv.is_support) avatar.appendChild(createNode('i', 'fas fa-headset'));
        else avatar.textContent = name[0].toUpperCase();
        if (conv.is_online) avatar.appendChild(createNode('span', 'online-dot'));
        const info = createNode('span', 'conv-info');
        info.append(createNode('span', 'conv-name', name), createNode('span', 'conv-preview', conv.last_message || 'Chưa có tin nhắn'));
        item.append(avatar, info);
        if (!conv.is_support) {
            const meta = createNode('span', 'conv-meta');
            meta.appendChild(createNode('span', 'conv-time', this.formatTime(conv.last_message_at)));
            if (unread) {
                const badge = createNode('span', 'conv-badge', unread > 99 ? '99+' : String(unread));
                badge.setAttribute('role', 'status');
                badge.setAttribute('aria-label', `${unread} tin nhắn chưa đọc`);
                meta.appendChild(badge);
            }
            item.appendChild(meta);
        }
        item.addEventListener('click', () => onSelect(conv.id, name, conv.is_online));
        if (!conv.is_support && /^\d+$/.test(String(conv.id))) {
            item.addEventListener('contextmenu', event => this.app.showConversationOptions(conv.id, event));
        }
        return item;
    }

    renderEmptyConversations() {
        const hint = createNode('div', 'conversation-empty', this.app.userId ?
            'Tìm người dùng ở ô phía trên để bắt đầu đoạn chat riêng.' :
            'Đăng nhập để nhắn bạn bè. Kênh hỗ trợ vẫn dùng được cho khách.');
        this.conversationList?.appendChild(hint);
    }

    switchChatUI(name, isOnline, id) {
        if (this.welcomeScreen) this.welcomeScreen.style.display = 'none';
        this.activeChatContainer?.classList.add('active');
        this.activeChatContainer?.setAttribute('aria-busy', 'true');
        document.querySelector('.messenger-container')?.classList.add('mobile-chat-open');
        const chatName = String(name || 'Hỗ trợ khách hàng');
        for (const key of ['currentChatName', 'infoPanelName']) {
            const el = document.getElementById(key);
            if (el) el.textContent = chatName;
        }
        for (const key of ['currentChatAvatar', 'infoPanelAvatar']) {
            const el = document.getElementById(key);
            if (el) el.textContent = chatName[0].toUpperCase();
        }
        this.updateStatus(id, isOnline);
        document.getElementById('currentChatName')?.focus({ preventScroll: true });
    }

    showConversationList() {
        document.querySelector('.messenger-container')?.classList.remove('mobile-chat-open');
        document.getElementById('infoPanel')?.classList.remove('panel-open');
        document.getElementById('searchResults')?.classList.remove('active');
        document.getElementById('sidebarSearchInput')?.setAttribute('aria-expanded', 'false');
        const selected = Array.from(this.conversationList?.children || []).find(element =>
            element.dataset.conversationId === String(this.app.currentConversationId ?? ''));
        selected?.focus({ preventScroll: true });
    }

    toggleInfoPanel() {
        const panel = document.getElementById('infoPanel');
        const toggle = document.getElementById('toggleInfoBtn');
        if (!panel) return;
        const narrow = window.matchMedia('(max-width: 1100px)').matches;
        const open = narrow ? panel.classList.toggle('panel-open') : !panel.classList.toggle('hidden');
        toggle?.setAttribute('aria-expanded', String(open));
        if (narrow && open) document.getElementById('closeInfoBtn')?.focus();
    }

    showConversationError(message, retry) {
        const error = createNode('div', 'conversation-empty');
        error.setAttribute('role', 'status');
        const button = createNode('button', 'header-btn', 'Thử lại');
        button.type = 'button';
        button.addEventListener('click', retry);
        error.append(createNode('p', '', message || 'Chưa tải được hội thoại.'), button);
        this.conversationList?.replaceChildren(error);
    }

    showEmptyHistory() {
        const empty = createNode('div', 'chat-empty');
        empty.append(createNode('i', 'far fa-comments'), createNode('p', '', 'Chưa có tin nhắn nào. Gửi lời chào để bắt đầu.'));
        this.messagesArea?.appendChild(empty);
    }

    showHistoryError(message, retry) {
        const error = createNode('div', 'chat-empty chat-error');
        error.setAttribute('role', 'status');
        const button = createNode('button', 'chat-empty-action', 'Thử tải lại');
        button.type = 'button';
        button.addEventListener('click', retry);
        error.append(createNode('p', '', message || 'Chưa tải được tin nhắn.'), button);
        this.messagesArea?.replaceChildren(error);
    }

    updateStatus(id, isOnline) {
        const elements = [document.getElementById('currentChatStatus') || document.getElementById('headerStatus'),
            document.getElementById('infoPanelStatus') || document.getElementById('infoStatus')];
        for (const el of elements) {
            if (!el) continue;
            // Support availability is not evidence that a particular operator is online.
            el.textContent = !id || !/^\d+$/.test(String(id)) ? 'Kênh hỗ trợ' : isOnline ? 'Đang hoạt động' : 'Không hoạt động';
            el.style.color = isOnline ? 'var(--online-green)' : 'var(--text-secondary)';
        }
    }

    mediaPlaceholder(type, text = 'File không khả dụng') {
        const placeholder = createNode('div', 'img-error-placeholder');
        const icon = { image: 'image', video: 'video', audio: 'music' }[type] || 'file';
        placeholder.append(createNode('i', `fas fa-${icon}`), createNode('span', '', text));
        return placeholder;
    }

    renderAttachment(att) {
        const url = this.app.api.attachmentUrl(att?.file_url);
        if (!url) return this.mediaPlaceholder(att?.file_type);
        const name = String(att.file_name || 'Tệp đính kèm');
        if (['image', 'video', 'audio'].includes(att.file_type)) {
            const wrapper = createNode('div', `message-${att.file_type}`);
            const media = createNode(att.file_type === 'image' ? 'img' : att.file_type);
            media.src = url;
            media.referrerPolicy = 'no-referrer';
            if (att.file_type === 'image') {
                media.alt = name;
                wrapper.tabIndex = 0;
                wrapper.setAttribute('role', 'button');
                wrapper.setAttribute('aria-label', `Xem ảnh ${name}`);
                wrapper.addEventListener('click', () => this.app.viewer?.open(url));
                wrapper.addEventListener('keydown', event => {
                    if (!['Enter', ' '].includes(event.key)) return;
                    event.preventDefault();
                    this.app.viewer?.open(url);
                });
            } else {
                media.controls = true;
                media.preload = 'metadata';
            }
            media.addEventListener('error', () => wrapper.replaceChildren(this.mediaPlaceholder(att.file_type)), { once: true });
            wrapper.appendChild(media);
            return wrapper;
        }
        const link = createNode('a', 'file-attachment');
        link.href = url;
        link.download = name;
        link.rel = 'noopener noreferrer';
        link.referrerPolicy = 'no-referrer';
        link.append(createNode('i', 'fas fa-file'), createNode('span', '', name));
        return link;
    }

    appendMessage(data) {
        const area = this.messagesArea;
        if (!area || data.id == null || findMessage(data.id)) return;
        area.querySelector('.chat-empty')?.remove();
        const type = data.type === 'sent' ? 'sent' : 'received';
        const id = String(data.id);
        const content = String(data.content ?? '');
        const group = createNode('div', `message-group ${type}${data.is_pinned ? ' pinned' : ''}`);
        group.dataset.messageId = id;
        group.dataset.pinned = data.is_pinned ? 'true' : 'false';
        group.dataset.senderName = String(data.senderName || (type === 'sent' ? 'Bạn' : 'Người dùng'));
        const row = createNode('div', 'message-row');
        if (type === 'received') row.appendChild(createNode('div', 'message-avatar', data.avatarText || '?'));
        const bigEmoji = (data.msgType || 'text') === 'text' && /^\p{Extended_Pictographic}\uFE0F?$/u.test(content.trim());
        const bubble = createNode('div', `message-bubble${bigEmoji ? ' big-emoji' : ''}${data.parent_content ? ' has-reply' : ''}`);
        bubble.dataset.msgId = id;
        bubble.addEventListener('contextmenu', event => this.app.showMsgOptions(id, event));
        if (data.parent_content) {
            const quote = createNode('button', 'message-reply-quote');
            quote.type = 'button';
            quote.append(createNode('span', 'quote-user', data.parent_sender_name || 'Người dùng'),
                createNode('span', 'quote-text', data.parent_content));
            quote.addEventListener('click', () => this.app.scrollToMessage(data.reply_to_id));
            bubble.appendChild(quote);
        }
        const main = createNode('div', 'message-bubble-main');
        if (data.attachments?.[0]) main.appendChild(this.renderAttachment(data.attachments[0]));
        else if (data.msgType === 'sticker' && stickerUrl(content)) {
            const wrapper = createNode('div', 'message-sticker');
            const image = createNode('img', 'sticker-img');
            image.src = stickerUrl(content);
            image.alt = 'Sticker';
            image.referrerPolicy = 'no-referrer';
            image.addEventListener('error', () => wrapper.replaceChildren(this.mediaPlaceholder('image')), { once: true });
            wrapper.appendChild(image);
            main.appendChild(wrapper);
        } else if (['image', 'video', 'audio', 'file'].includes(data.msgType)) {
            main.appendChild(this.mediaPlaceholder(data.msgType));
        } else main.textContent = content;
        bubble.appendChild(main);
        const actions = createNode('div', 'message-actions');
        const action = (icon, title, handler) => {
            const button = createNode('button', 'msg-action-btn');
            button.type = 'button';
            button.title = title;
            button.setAttribute('aria-label', title);
            button.appendChild(createNode('i', icon));
            button.addEventListener('click', handler);
            return button;
        };
        actions.append(action('far fa-smile', 'Thêm cảm xúc', event => this.app.toggleReactionPopup(id, event)),
            action('fas fa-reply', 'Trả lời', event => this.app.handleReply(id, event)),
            action('fas fa-ellipsis-h', 'Xem thêm', event => this.app.showMsgOptions(id, event)));
        const quick = createNode('div', 'hover-reaction-bar');
        quick.id = `reactionBar-${id}`;
        for (const emoji of ['❤️', '😂', '😮', '😢', '😡', '👍']) {
            const choice = createNode('button', 'hover-emoji', emoji);
            choice.type = 'button';
            choice.setAttribute('aria-label', `Thả ${emoji}`);
            choice.addEventListener('click', () => this.app.toggleReaction(id, emoji));
            quick.appendChild(choice);
        }
        actions.appendChild(quick);
        bubble.appendChild(actions);
        row.appendChild(bubble);
        const footer = createNode('div', 'message-footer');
        const reactions = this.renderReactions(data.reactions, id);
        if (reactions) footer.appendChild(reactions);
        footer.appendChild(createNode('div', 'message-time', data.time));
        group.append(row, footer);
        area.appendChild(group);
        this.scrollToBottom();
    }

    renderReactions(reactions, messageId) {
        if (!Array.isArray(reactions) || !reactions.length) return null;
        const counts = new Map();
        const own = new Set();
        for (const reaction of reactions) {
            const emoji = String(reaction.emoji ?? '');
            counts.set(emoji, (counts.get(emoji) || 0) + 1);
            if (this.app.userId && String(reaction.user_id) === String(this.app.userId)) own.add(emoji);
        }
        const area = createNode('div', 'message-reactions');
        for (const [emoji, count] of counts) {
            const badge = createNode('button', `reaction-badge${own.has(emoji) ? ' own' : ''}`, emoji);
            badge.type = 'button';
            badge.setAttribute('aria-pressed', String(own.has(emoji)));
            badge.setAttribute('aria-label', `${emoji}, ${count} người đã thả cảm xúc`);
            badge.dataset.emoji = emoji;
            badge.title = `${count} người đã thả cảm xúc`;
            badge.appendChild(createNode('span', '', count > 1 ? count : ''));
            badge.addEventListener('click', () => this.app.toggleReaction(messageId, emoji));
            area.appendChild(badge);
        }
        return area;
    }

    updateMessageReactions(id, reactions) {
        const footer = findMessage(id)?.querySelector('.message-footer');
        if (!footer) return;
        footer.querySelector('.message-reactions')?.remove();
        const area = this.renderReactions(reactions, id);
        if (area) footer.insertBefore(area, footer.querySelector('.message-time'));
    }

    showReplyShelf(name, content) {
        const shelf = document.getElementById('replyShelf');
        const user = document.getElementById('replyUserName');
        const text = document.getElementById('replyMsgPreview');
        if (!shelf || !user || !text) return;
        user.textContent = `Đang trả lời ${name}`;
        text.textContent = content;
        shelf.classList.add('active');
        document.querySelector('.chat-input-area')?.classList.add('with-reply');
    }
    hideReplyShelf() {
        document.getElementById('replyShelf')?.classList.remove('active');
        document.querySelector('.chat-input-area')?.classList.remove('with-reply');
    }
    scrollToBottom() {
        if (this.messagesArea) this.messagesArea.scrollTop = this.messagesArea.scrollHeight;
    }
    showPinnedShelf(content) {
        if (!this.pinnedShelf || !this.pinnedContent) return;
        this.pinnedContent.textContent = content;
        this.pinnedShelf.classList.add('active');
    }
    showToast(message, background) {
        document.getElementById('chatToast')?.remove();
        clearTimeout(this.toastTimer);
        const toast = createNode('div', 'chat-toast', message);
        toast.id = 'chatToast';
        toast.setAttribute('role', 'status');
        toast.setAttribute('aria-live', 'polite');
        if (background) toast.style.background = background;
        document.body.appendChild(toast);
        this.toastTimer = setTimeout(() => toast.remove(), 4000);
    }
    renderSeenStatus(userId) {
        if (!this.messagesArea) return;
        for (const el of this.messagesArea.querySelectorAll('.message-seen-status')) {
            if (el.dataset.userId === String(userId)) el.remove();
        }
        const sent = this.messagesArea.querySelectorAll('.message-group.sent');
        const footer = sent[sent.length - 1]?.querySelector('.message-footer');
        if (!footer) return;
        const status = createNode('div', 'message-seen-status', 'Đã xem');
        status.dataset.userId = String(userId);
        status.title = 'Đã xem';
        footer.appendChild(status);
    }
    formatTime(value) {
        if (!value) return '';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    escapeHtml(value) { return escapeHtml(value); }
    applyTheme(color) {
        if (typeof color !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(color)) return;
        const container = document.querySelector('.messenger-container');
        if (!container) return;
        container.style.setProperty('--conversation-color', color);
        const channels = color.slice(1).match(/.{2}/g).map(value => parseInt(value, 16) / 255)
            .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
        const luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
        container.style.setProperty('--conversation-ink', luminance > 0.179 ? '#000000' : '#ffffff');
        for (const choice of document.querySelectorAll('.theme-option')) {
            const selected = choice.dataset.color?.toLowerCase() === color.toLowerCase();
            choice.classList.toggle('active', selected);
            choice.setAttribute('aria-pressed', String(selected));
        }
    }
    renderSettings(data) {
        if (data.theme_color) this.applyTheme(data.theme_color);
        const like = document.getElementById('likeBtn');
        if (!like || !data.default_emoji) return;
        const icons = { '👍': 'fas fa-thumbs-up', '❤️': 'fas fa-heart', '😆': 'fas fa-laugh', '😮': 'fas fa-surprise' };
        like.replaceChildren(icons[data.default_emoji] ? createNode('i', icons[data.default_emoji]) :
            createNode('span', '', data.default_emoji));
        like.dataset.emoji = String(data.default_emoji);
    }
    openMediaBrowser(type, attachments) {
        const modal = document.getElementById('mediaBrowserModal');
        const grid = document.getElementById('mediaGridBody');
        const title = document.getElementById('mediaBrowserTitle');
        if (!modal || !grid) return;
        if (title) title.textContent = type === 'image' ? 'File phương tiện' : 'File';
        grid.replaceChildren();
        for (const att of attachments) {
            const item = createNode('div', 'media-item');
            item.appendChild(this.renderAttachment(att));
            const caption = createNode('div', 'media-caption', att.file_name);
            caption.title = String(att.file_name || '');
            item.appendChild(caption);
            grid.appendChild(item);
        }
        if (!attachments.length) grid.appendChild(createNode('div', '', 'Không có file nào'));
        this.openDialog('mediaBrowserModal');
    }
}

export default ChatUI;
