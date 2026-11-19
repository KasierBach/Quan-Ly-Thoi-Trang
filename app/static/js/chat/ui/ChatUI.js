import { createNode, escapeHtml, findMessage, stickerUrl } from '../utils/helpers.js';

/** Colorful chat UI; persisted content is always text or validated DOM properties. */
class ChatUI {
    constructor(app) { this.app = app; }

    get messagesArea() { return document.getElementById('messagesArea'); }
    get conversationList() { return document.getElementById('conversationList'); }
    get activeChatContainer() { return document.getElementById('activeChatContainer'); }
    get welcomeScreen() { return document.getElementById('welcomeScreen'); }
    get pinnedShelf() { return document.getElementById('pinnedShelf'); }
    get pinnedContent() { return document.getElementById('pinnedContent'); }
    get messageInput() { return document.getElementById('messageInput'); }

    renderConversationList(conversations, currentId, onSelect) {
        if (!this.conversationList) return;
        this.conversationList.replaceChildren(this.createConversationItem({
            id: null, name: 'Hỗ trợ khách hàng', last_message: 'Chat với đội ngũ hỗ trợ',
            is_support: true, active: currentId === null
        }, onSelect));
        if (!conversations.length) this.renderEmptyConversations();
        for (const conv of conversations) {
            this.conversationList.appendChild(this.createConversationItem({
                ...conv, active: String(currentId) === String(conv.id)
            }, onSelect));
        }
    }

    createConversationItem(conv, onSelect) {
        const item = createNode('div', `conv-item${conv.active ? ' active' : ''}`);
        item.dataset.conversationId = conv.id ?? '';
        const name = String(conv.name || 'Người dùng');
        const avatar = createNode('div', `conv-avatar${conv.is_support ? ' support-avatar' : ''}`);
        if (conv.is_support) avatar.appendChild(createNode('i', 'fas fa-headset'));
        else avatar.textContent = name[0].toUpperCase();
        if (conv.is_online) avatar.appendChild(createNode('div', 'online-dot'));
        const info = createNode('div', 'conv-info');
        info.append(createNode('div', 'conv-name', name), createNode('div', 'conv-preview', conv.last_message || 'Chưa có tin nhắn'));
        item.append(avatar, info);
        if (!conv.is_support) item.appendChild(createNode('div', 'conv-time', this.formatTime(conv.last_message_at)));
        item.addEventListener('click', () => onSelect(conv.id, name, conv.is_online));
        return item;
    }

    renderEmptyConversations() {
        const hint = createNode('div', '', this.app.userId ?
            'Chưa có cuộc trò chuyện nào khác. Tìm bạn bè ở thanh tìm kiếm.' :
            'Đăng nhập để trò chuyện với bạn bè. Bạn vẫn có thể nhắn hỗ trợ.');
        hint.style.cssText = 'padding:20px; text-align:center; color:var(--text-secondary); font-size:0.9rem;';
        this.conversationList?.appendChild(hint);
    }

    switchChatUI(name, isOnline, id) {
        if (this.welcomeScreen) this.welcomeScreen.style.display = 'none';
        this.activeChatContainer?.classList.add('active');
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
                wrapper.addEventListener('click', () => this.app.viewer?.open(url));
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
            const quote = createNode('div', 'message-reply-quote');
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
            const choice = createNode('span', 'hover-emoji', emoji);
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
            const badge = createNode('div', `reaction-badge${own.has(emoji) ? ' own' : ''}`, emoji);
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
    showToast(message, background = '#333') {
        const toast = createNode('div', '', message);
        toast.style.cssText = 'position:fixed; bottom:20px; left:50%; transform:translateX(-50%); color:white; padding:10px 20px; border-radius:30px; z-index:9999; font-size:14px;';
        toast.style.background = background;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
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
        document.documentElement.style.setProperty('--messenger-blue', color);
        document.documentElement.style.setProperty('--messenger-primary', color);
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
        modal.style.display = 'block';
    }
}

export default ChatUI;
