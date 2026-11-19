/** Backend requests use credentials issued to this page, never a stored guest ID. */
class ChatAPI {
    constructor(csrfToken, { authenticated = false } = {}) {
        this.csrfToken = csrfToken;
        this.authenticated = authenticated;
        this.authToken = null;
        this.credentialsPromise = null;
        this.expiresAt = 0;
    }

    async ensureGuestSession() {
        if (this.credentialsPromise && this.expiresAt && Date.now() >= this.expiresAt) {
            this.credentialsPromise = null;
            this.authToken = null;
        }
        if (!this.credentialsPromise) {
            this.credentialsPromise = fetch('/api/chat/guest-session', {
                method: 'POST', credentials: 'same-origin', cache: 'no-store',
                headers: { 'X-CSRFToken': this.csrfToken }
            }).then(async res => {
                const credentials = await this.readResponse(res);
                if (typeof credentials.session_id !== 'string' ||
                    !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(credentials.session_id) ||
                    typeof credentials.auth_token !== 'string' || !credentials.auth_token ||
                    credentials.auth_token.length > 2048 ||
                    !Number.isFinite(credentials.expires_in) || credentials.expires_in <= 0) {
                    throw new Error('Thông tin phiên chat không hợp lệ');
                }
                this.authToken = credentials.auth_token;
                this.expiresAt = Date.now() + credentials.expires_in * 1000;
                return credentials;
            }).catch(error => {
                this.credentialsPromise = null;
                this.authToken = null;
                this.expiresAt = 0;
                throw error;
            });
        }
        return this.credentialsPromise;
    }

    headers(json = false) {
        return {
            'X-CSRFToken': this.csrfToken, 'X-Chat-Token': this.authToken || '',
            ...(json ? { 'Content-Type': 'application/json' } : {})
        };
    }

    async readResponse(res) {
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || data.success === false || data.error) {
            const error = new Error(data?.error || data?.message || `Chat không khả dụng (${res.status})`);
            error.status = res.status;
            throw error;
        }
        return data;
    }

    async request(url, { method = 'GET', body } = {}) {
        await this.ensureGuestSession();
        const json = body !== undefined && !(body instanceof FormData);
        const res = await fetch(url, {
            method, credentials: 'same-origin', cache: 'no-store', headers: this.headers(json),
            ...(body !== undefined ? { body: json ? JSON.stringify(body) : body } : {})
        });
        return this.readResponse(res);
    }

    // Numeric conversations and support sessions are separate scopes on the server.
    scope(sessionId, conversationId) {
        if (conversationId != null && /^\d+$/.test(String(conversationId))) {
            return { conversation_id: this.id(conversationId) };
        }
        const sid = conversationId || sessionId;
        if (typeof sid !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(sid)) {
            throw new Error('Cần khởi tạo phiên chat');
        }
        return { session_id: sid };
    }

    id(value) {
        const id = Number(value);
        if (!/^\d+$/.test(String(value)) || !Number.isSafeInteger(id) || id < 1 || id > 2147483647) {
            throw new Error('Mã chat không hợp lệ');
        }
        return id;
    }

    attachmentUrl(value) {
        if (typeof value !== 'string' || !/^\/api\/chat\/attachments\/[1-9]\d*$/.test(value)) return null;
        if (this.authenticated) return value;
        // Never persist/publish token-bearing URLs or append a token to an external URL.
        if (!this.authToken || Date.now() >= this.expiresAt) return null;
        return `${value}?auth_token=${encodeURIComponent(this.authToken)}`;
    }

    getConversations() { return this.request('/api/conversations'); }
    getConversation(id) { return this.request(`/api/conversations/${this.id(id)}`); }

    async getHistory(sessionId, conversationId = null, beforeId = null) {
        const credentials = await this.ensureGuestSession();
        const query = new URLSearchParams(this.scope(sessionId || credentials.session_id, conversationId));
        if (beforeId != null) query.set('before_id', this.id(beforeId));
        return this.request(`/api/chat/history?${query}`);
    }

    async sendMessage(content, sessionId, conversationId = null, messageType = 'text', replyToId = null) {
        const credentials = await this.ensureGuestSession();
        return this.request('/api/chat/send', { method: 'POST', body: {
            ...this.scope(sessionId || credentials.session_id, conversationId),
            content, message_type: messageType,
            ...(replyToId != null ? { reply_to_id: this.id(replyToId) } : {})
        } });
    }

    getPinnedMessages(id) { return this.request(`/api/chat/conversations/${this.id(id)}/pinned`); }
    getParticipants(id) { return this.request(`/api/conversations/${this.id(id)}/participants`); }

    async uploadFile(file, sessionId, conversationId) {
        const credentials = await this.ensureGuestSession();
        const formData = new FormData();
        formData.append('file', file);
        for (const [key, value] of Object.entries(this.scope(sessionId || credentials.session_id, conversationId))) {
            formData.append(key, value);
        }
        return this.request('/api/chat/upload', { method: 'POST', body: formData });
    }

    searchUsers(query) { return this.request(`/api/users/search?q=${encodeURIComponent(query)}`); }
    getSuggestedUsers() { return this.request('/api/users/suggested'); }
    startDirectChat(userId) {
        return this.request('/api/conversations/direct', { method: 'POST', body: { user_id: this.id(userId) } });
    }
    leaveConversation(id) { return this.request(`/api/conversations/${this.id(id)}/leave`, { method: 'POST' }); }
    markAsRead(id) { return this.request(`/api/conversations/${this.id(id)}/read`, { method: 'POST' }); }
    createGroup(name, participantIds = []) {
        return this.request('/api/conversations', { method: 'POST', body: {
            name, type: 'group', participant_ids: participantIds.map(id => this.id(id))
        } });
    }
    addGroupParticipant(id, userId) {
        return this.request(`/api/conversations/${this.id(id)}/participants`, {
            method: 'POST', body: { user_id: this.id(userId) }
        });
    }
    updateConversationSettings(id, settings) {
        return this.request(`/api/conversations/${this.id(id)}/settings`, { method: 'PATCH', body: settings });
    }
    updateMySettings(id, settings) {
        return this.request(`/api/conversations/${this.id(id)}/participants/me`, { method: 'PATCH', body: settings });
    }
    updateParticipantSettings(id, userId, settings) {
        return this.request(`/api/conversations/${this.id(id)}/participants/${this.id(userId)}`, {
            method: 'PATCH', body: settings
        });
    }
    getUserStatus(id) { return this.request(`/api/users/${this.id(id)}/status`); }
    getAttachments(id, type = null) {
        const query = type ? `?type=${encodeURIComponent(type)}` : '';
        return this.request(`/api/conversations/${this.id(id)}/attachments${query}`);
    }
}

export default ChatAPI;
