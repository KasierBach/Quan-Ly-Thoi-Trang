import ChatAPI from './ChatAPI.js';
import ChatUI from '../ui/ChatUI.js';
import { createNode } from '../utils/helpers.js';

export class ChatWidget {
    constructor(api, elements) {
        this.api = api;
        this.elements = elements;
        this.sessionId = null;
        this.isOpen = false;
        this.sending = false;
        this.loading = false;
        this.closed = false;
        this.requestRevision = 0;
        this.ui = new ChatUI({ api });
        this.ready = this.initialize();
    }

    async initialize() {
        try {
            const credentials = await this.api.ensureGuestSession();
            if (this.closed) return false;
            this.sessionId = credentials.session_id;
            this.elements.input.disabled = false;
            this.elements.send.disabled = false;
            await this.loadMessages();
            return true;
        } catch (error) {
            if (!this.closed) this.showError(error.message);
            return false;
        }
    }

    toggle() {
        this.isOpen = !this.isOpen;
        this.elements.window.classList.toggle('active', this.isOpen);
        if (this.isOpen) this.ready.then(ready => { if (ready) this.loadMessages(); });
    }

    showError(message) {
        this.elements.body.querySelector('.chat-error')?.remove();
        const error = createNode('div', 'message admin chat-error', message || 'Chat tạm thời không khả dụng');
        error.setAttribute('role', 'status');
        this.elements.body.appendChild(error);
    }

    appendMessage(message) {
        const node = createNode('div', `message ${message.sender_type === 'admin' ? 'admin' : 'user'}`);
        if (message.attachments?.[0]) node.appendChild(this.ui.renderAttachment(message.attachments[0]));
        else node.textContent = String(message.content ?? '');
        node.appendChild(createNode('div', 'message-time', this.ui.formatTime(message.created_at || message.timestamp)));
        this.elements.body.appendChild(node);
    }

    async loadMessages() {
        if (!this.sessionId || this.closed || this.loading || this.sending) return;
        const revision = this.requestRevision;
        this.loading = true;
        try {
            const data = await this.api.getHistory(this.sessionId);
            if (this.closed || revision !== this.requestRevision) return;
            this.elements.body.replaceChildren();
            const welcome = createNode('div', 'message admin', 'Chào bạn! Shop có thể giúp gì cho bạn hôm nay?');
            welcome.appendChild(createNode('div', 'message-time', 'Hệ thống'));
            this.elements.body.appendChild(welcome);
            for (const message of data.messages || []) this.appendMessage(message);
            this.elements.body.scrollTop = this.elements.body.scrollHeight;
        } catch (error) {
            if (!this.closed) this.showError(error.message);
        } finally { this.loading = false; }
    }

    async sendMessage() {
        if (this.sending || this.closed) return;
        const content = this.elements.input.value.trim();
        if (!content) return;
        this.sending = true;
        this.elements.send.disabled = true;
        ++this.requestRevision;
        try {
            if (!await this.ready || this.closed) return;
            const message = await this.api.sendMessage(content, this.sessionId);
            if (this.closed) return;
            // Render only after server acknowledgement, not a false optimistic success.
            if (this.elements.input.value.trim() === content) this.elements.input.value = '';
            this.elements.body.querySelector('.chat-error')?.remove();
            this.appendMessage(message);
            this.elements.body.scrollTop = this.elements.body.scrollHeight;
        } catch (error) {
            if (!this.closed) this.showError(error.message);
        } finally {
            this.sending = false;
            this.elements.send.disabled = !this.sessionId || this.closed;
        }
    }

    close() {
        this.closed = true;
        ++this.requestRevision;
        clearInterval(this.pollTimer);
    }
}

const windowElement = document.getElementById('chatWindow');
if (windowElement) {
    const config = JSON.parse(document.getElementById('chatWidgetConfig').textContent);
    const widget = new ChatWidget(new ChatAPI(document.querySelector('meta[name="csrf-token"]')?.content, config), {
        window: windowElement, body: document.getElementById('chatBody'),
        input: document.getElementById('chatInput'), send: document.getElementById('chatSend')
    });
    window.toggleLiveChat = () => widget.toggle();
    document.getElementById('chatClose')?.addEventListener('click', () => {
        widget.isOpen = false;
        windowElement.classList.remove('active');
    });
    widget.elements.send.addEventListener('click', () => widget.sendMessage());
    widget.elements.input.addEventListener('keydown', event => {
        if (event.key === 'Enter') { event.preventDefault(); widget.sendMessage(); }
    });
    widget.pollTimer = setInterval(() => { if (widget.isOpen) widget.loadMessages(); }, 3000);
    window.addEventListener('pagehide', () => widget.close(), { once: true });
}
