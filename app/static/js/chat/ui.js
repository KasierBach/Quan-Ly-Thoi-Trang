/**
 * Chat UI Service
 * Handles all DOM manipulation and rendering.
 */
class ChatUI {
    constructor(app) {
        this.app = app;
        this.messagesArea = document.getElementById('messagesArea');
        this.conversationList = document.getElementById('conversationList');
        this.activeChatContainer = document.getElementById('activeChatContainer');
        this.welcomeScreen = document.getElementById('welcomeScreen');
        this.pinnedShelf = document.getElementById('pinnedShelf');
        this.pinnedContent = document.getElementById('pinnedContent');
        this.messageInput = document.getElementById('messageInput');
    }

    renderConversationList(conversations, currentId, onSelect) {
        if (!this.conversationList) return;
        this.conversationList.innerHTML = '';

        // Support Chat always at top
        const supportItem = this.createConversationItem({
            id: null,
            name: 'Hỗ trợ khách hàng',
            last_message: 'Chat với đội ngũ hỗ trợ',
            is_support: true,
            active: currentId === null
        }, onSelect);
        this.conversationList.appendChild(supportItem);

        if (conversations.length === 0) {
            this.renderEmptyConversations();
        }

        conversations.forEach(conv => {
            const item = this.createConversationItem({
                ...conv,
                active: currentId == conv.id
            }, onSelect);
            this.conversationList.appendChild(item);
        });
    }

    createConversationItem(conv, onSelect) {
        const item = document.createElement('div');
        item.className = 'conv-item' + (conv.active ? ' active' : '');
        item.dataset.conversationId = conv.id;

        const avatarChar = conv.name ? conv.name[0].toUpperCase() : '?';
        const time = conv.last_message_at ? this.formatTime(conv.last_message_at) : '';
        const onlineDot = conv.is_online ? '<div class="online-dot"></div>' : '';

        if (conv.is_support) {
            item.innerHTML = `
                <div class="conv-avatar support-avatar"><i class="fas fa-headset"></i></div>
                <div class="conv-info">
                    <div class="conv-name">${conv.name}</div>
                    <div class="conv-preview">${conv.last_message}</div>
                </div>
            `;
        } else {
            item.innerHTML = `
                <div class="conv-avatar">${avatarChar}${onlineDot}</div>
                <div class="conv-info">
                    <div class="conv-name">${conv.name || 'Người dùng'}</div>
                    <div class="conv-preview">${conv.last_message || 'Chưa có tin nhắn'}</div>
                </div>
                <div class="conv-time">${time}</div>
            `;
        }

        item.onclick = () => onSelect(conv.id, conv.name, conv.is_online);
        return item;
    }

    renderEmptyConversations() {
        const hint = document.createElement('div');
        hint.style = 'padding: 20px; text-align: center; color: var(--text-secondary); font-size: 0.9rem;';
        hint.innerHTML = `
            <div class="mb-2"><i class="fas fa-user-plus" style="font-size: 2rem; opacity: 0.3;"></i></div>
            <div>Chưa có cuộc trò chuyện nào khác.</div>
            <div style="font-size: 0.8rem; margin-top: 5px;">Sử dụng thanh tìm kiếm để tìm bạn bè!</div>
        `;
        this.conversationList.appendChild(hint);
    }

    switchChatUI(name, isOnline, id) {
        if (this.welcomeScreen) this.welcomeScreen.style.display = 'none';
        if (this.activeChatContainer) this.activeChatContainer.classList.add('active');

        const chatName = name || 'Hỗ trợ khách hàng';
        const avatarChar = name ? name[0].toUpperCase() : 'H';

        const nameEl = document.getElementById('currentChatName');
        const avatarEl = document.getElementById('currentChatAvatar');
        const infoNameEl = document.getElementById('infoPanelName');
        const infoAvatarEl = document.getElementById('infoPanelAvatar');

        if (nameEl) nameEl.textContent = chatName;
        if (avatarEl) avatarEl.textContent = avatarChar;
        if (infoNameEl) infoNameEl.textContent = chatName;
        if (infoAvatarEl) infoAvatarEl.textContent = avatarChar;

        this.updateStatus(id, isOnline);
    }

    updateStatus(id, isOnline) {
        const statusEl = document.getElementById('currentChatStatus') || document.getElementById('headerStatus');
        const infoStatusEl = document.getElementById('infoPanelStatus') || document.getElementById('infoStatus');
        const activeHtml = '<i class="fas fa-circle" style="font-size: 8px;"></i> Đang hoạt động';

        if (!id || isOnline) {
            [statusEl, infoStatusEl].forEach(el => {
                if (el) {
                    el.innerHTML = activeHtml;
                    el.style.color = 'var(--online-green)';
                }
            });
        } else {
            [statusEl, infoStatusEl].forEach(el => {
                if (el) {
                    el.textContent = 'Không hoạt động';
                    el.style.color = 'var(--text-secondary)';
                }
            });
        }
    }

    appendMessage(data) {
        if (!this.messagesArea) return;

        const { type, content, time, msgType = 'text', id = null, attachments = null, reactions = null, avatarText, senderName } = data;

        const div = document.createElement('div');
        div.className = `message-group ${type}` + (data.is_pinned ? ' pinned' : '');
        div.dataset.messageId = id;
        div.dataset.pinned = data.is_pinned ? 'true' : 'false';
        div.dataset.senderName = senderName || (type === 'sent' ? 'Bạn' : (avatarText || 'Người dùng'));

        let bubbleContent = this.escapeHtml(content);
        if (msgType === 'image' || (attachments && attachments[0] && attachments[0].file_type === 'image')) {
            const url = attachments ? attachments[0].file_url : content;
            bubbleContent = `<div class="message-image" onclick="window.chatApp.viewer.open('${url}')"><img src="${url}"></div>`;
        } else if (msgType === 'video' || (attachments && attachments[0] && attachments[0].file_type === 'video')) {
            const url = attachments ? attachments[0].file_url : content;
            bubbleContent = `<div class="message-video"><video controls src="${url}"></video></div>`;
        } else if (attachments && attachments[0]) {
            const att = attachments[0];
            bubbleContent = `<a href="${att.file_url}" download class="file-attachment"><i class="fas fa-file"></i> ${att.file_name}</a>`;
        }

        // Detect single emoji for "Big Emoji" effect (Messenger style)
        const isBigEmoji = msgType === 'text' && /^(\u00a9|\u00ae|[\u2000-\u3300]|\ud83c[\ud000-\udfff]|\ud83d[\ud000-\udfff]|\ud83e[\ud000-\udfff])$/.test(content.trim());
        const bubbleClass = isBigEmoji ? 'message-bubble big-emoji' : 'message-bubble';

        const avatarHtml = type === 'received' ? `<div class="message-avatar">${avatarText}</div>` : '';
        const reactionsHtml = this.renderReactions(reactions, id);

        const quickEmojis = ['❤️', '😂', '😮', '😢', '😡', '👍'];

        let quoteHtml = '';
        if (data.parent_content) {
            const pName = data.parent_sender_name || (data.parent_sender_type === 'admin' ? 'Admin' : 'Khách');
            quoteHtml = `
                <div class="message-reply-quote" onclick="window.chatApp.scrollToMessage('${data.reply_to_id}')">
                    <span class="quote-user">${this.escapeHtml(pName)}</span>
                    <span class="quote-text">${this.escapeHtml(data.parent_content)}</span>
                </div>
            `;
        }

        const html = `
            <div class="message-row">
                ${avatarHtml}
                <div class="${bubbleClass}" oncontextmenu="window.chatApp.showMsgOptions('${id}', event)" data-msg-id="${id}">
                    ${quoteHtml}
                    <div class="message-bubble-main">
                        ${bubbleContent}
                    </div>
                    <div class="message-actions">
                        <button class="msg-action-btn" title="Thêm cảm xúc">
                            <i class="far fa-smile"></i>
                        </button>
                        <button class="msg-action-btn" title="Trả lời" onclick="window.chatApp.handleReply('${id}', event)">
                            <i class="fas fa-reply"></i>
                        </button>
                        <button class="msg-action-btn" title="Xem thêm" onclick="window.chatApp.showMsgOptions('${id}', event)">
                            <i class="fas fa-ellipsis-h"></i>
                        </button>
                        <div class="hover-reaction-bar" id="reactionBar-${id}">
                            ${quickEmojis.map(emoji => `<span class="hover-emoji" onclick="window.chatApp.toggleReaction('${id}', '${emoji}')">${emoji}</span>`).join('')}
                        </div>
                    </div>
                </div>
            </div>
            <div class="message-footer">
                ${reactionsHtml}
                <div class="message-time">${time}</div>
            </div>
        `;
        div.innerHTML = html;
        this.messagesArea.appendChild(div);
        this.scrollToBottom();
    }

    renderReactions(reactions, messageId) {
        if (!reactions || reactions.length === 0) return '';
        const counts = {};
        const userReactions = new Set();

        reactions.forEach(r => {
            counts[r.emoji] = (counts[r.emoji] || 0) + 1;
            if (r.user_id === this.app.userId) {
                userReactions.add(r.emoji);
            }
        });

        let html = `<div class="message-reactions">`;
        for (let emoji in counts) {
            const isOwn = userReactions.has(emoji);
            html += `
                <div class="reaction-badge ${isOwn ? 'own' : ''}"
                     onclick="window.chatApp.toggleReaction('${messageId}', '${emoji}')"
                     title="${counts[emoji]} người đã thả cảm xúc">
                    ${emoji} <span>${counts[emoji] > 1 ? counts[emoji] : ''}</span>
                </div>`;
        }
        html += `</div>`;
        return html;
    }

    updateMessageReactions(msgId, reactions) {
        const msgGroup = document.querySelector(`.message-group[data-message-id="${msgId}"]`);
        if (!msgGroup) return;

        const footer = msgGroup.querySelector('.message-footer');
        let reactionArea = footer.querySelector('.message-reactions');

        if (reactions && reactions.length > 0) {
            const newHtml = this.renderReactions(reactions, msgId);
            if (reactionArea) {
                reactionArea.outerHTML = newHtml;
            } else {
                const timeEl = footer.querySelector('.message-time');
                const temp = document.createElement('div');
                temp.innerHTML = newHtml;
                footer.insertBefore(temp.firstChild, timeEl);
            }
        } else if (reactionArea) {
            reactionArea.remove();
        }
    }

    showReplyShelf(userName, content) {
        const shelf = document.getElementById('replyShelf');
        const userEl = document.getElementById('replyUserName');
        const msgEl = document.getElementById('replyMsgPreview');
        if (shelf && userEl && msgEl) {
            userEl.textContent = `Đang trả lời ${userName}`;
            msgEl.textContent = content;
            shelf.classList.add('active');
            document.querySelector('.chat-input-area').classList.add('with-reply');
        }
    }

    hideReplyShelf() {
        const shelf = document.getElementById('replyShelf');
        if (shelf) {
            shelf.classList.remove('active');
            document.querySelector('.chat-input-area').classList.remove('with-reply');
        }
    }

    scrollToBottom() {
        if (this.messagesArea) {
            this.messagesArea.scrollTop = this.messagesArea.scrollHeight;
        }
    }

    showPinnedShelf(content) {
        if (this.pinnedShelf && this.pinnedContent) {
            this.pinnedContent.textContent = content;
            this.pinnedShelf.classList.add('active');
        }
    }

    showToast(msg, bg = '#333') {
        const toast = document.createElement('div');
        toast.style = `position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:${bg}; color:white; padding:10px 20px; border-radius:30px; z-index:9999; font-size:14px;`;
        toast.textContent = msg;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    renderSeenStatus(userId, avatarUrl) {
        // Remove old status
        const existing = this.messagesArea.querySelectorAll(`.seen-status-${userId}`);
        existing.forEach(el => el.remove());

        // Find last message sent by ME
        const sentMessages = this.messagesArea.querySelectorAll('.message-group.sent');
        if (sentMessages.length === 0) return;
        const lastMsg = sentMessages[sentMessages.length - 1];

        // Create status
        const statusDiv = document.createElement('div');
        statusDiv.className = `message-seen-status seen-status-${userId}`;
        statusDiv.innerHTML = `<img src="${avatarUrl || '/static/images/default-avatar.png'}" title="Đã xem">`;

        // Insert after the message bubble or time
        const footer = lastMsg.querySelector('.message-footer');
        if (footer) {
            footer.appendChild(statusDiv);
        }
        this.scrollToBottom();
    }

    formatTime(str) {
        if (!str) return '';
        const d = new Date(str);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

export default ChatUI;
