/**
 * Chat API Service
 * Handles all backend communication.
 */
class ChatAPI {
    constructor(csrfToken) {
        this.csrfToken = csrfToken;
    }

    async getConversations() {
        const res = await fetch('/api/conversations');
        if (!res.ok) throw new Error(`API Error: ${res.status}`);
        return await res.json();
    }

    async getConversation(id) {
        const res = await fetch(`/api/conversations/${id}`);
        if (!res.ok) throw new Error(`API Error: ${res.status}`);
        return await res.json();
    }


    async getHistory(sessionId, conversationId = null) {
        let url = `/api/chat/history?session_id=${sessionId}`;
        if (conversationId) url += `&conversation_id=${conversationId}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`API Error: ${res.status}`);
        return await res.json();
    }

    async getPinnedMessages(convId) {
        const res = await fetch(`/api/chat/conversations/${convId}/pinned`);
        return res.ok ? await res.json() : { pinned: [] };
    }

    async getParticipants(convId) {
        const res = await fetch(`/api/conversations/${convId}/participants`);
        return res.ok ? await res.json() : { participants: [] };
    }

    async uploadFile(file, sessionId, conversationId) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('conversation_id', conversationId || '');
        formData.append('session_id', sessionId);

        const res = await fetch('/api/chat/upload', {
            method: 'POST',
            headers: { 'X-CSRFToken': this.csrfToken },
            body: formData
        });
        return await res.json();
    }

    async searchUsers(query) {
        const res = await fetch(`/api/users/search?q=${encodeURIComponent(query)}`);
        return await res.json();
    }

    async getSuggestedUsers() {
        const res = await fetch('/api/users/suggested');
        return await res.json();
    }

    async startDirectChat(userId) {
        const res = await fetch('/api/conversations/direct', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify({ user_id: userId })
        });
        return await res.json();
    }

    async leaveConversation(convId) {
        const res = await fetch(`/api/conversations/${convId}/leave`, {
            method: 'POST',
            headers: { 'X-CSRFToken': this.csrfToken }
        });
        return await res.json();
    }

    async markAsRead(convId) {
        const res = await fetch(`/api/conversations/${convId}/read`, {
            method: 'POST',
            headers: { 'X-CSRFToken': this.csrfToken }
        });
        return await res.json();
    }

    async createGroup(name) {
        const res = await fetch('/api/conversations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify({ name, type: 'group' })
        });
        return await res.json();
    }

    async addGroupParticipant(convId, userId) {
        const res = await fetch(`/api/conversations/${convId}/participants`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify({ user_id: userId })
        });
        return await res.json();
    }

    async updateConversationSettings(convId, settings) {
        const res = await fetch(`/api/conversations/${convId}/settings`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify(settings)
        });
        return await res.json();
    }

    async updateMySettings(convId, settings) {
        const res = await fetch(`/api/conversations/${convId}/participants/me`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify(settings)
        });
        return await res.json();
    }

    async updateParticipantSettings(convId, userId, settings) {
        const res = await fetch(`/api/conversations/${convId}/participants/${userId}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify(settings)
        });
        return await res.json();
    }

    async getAttachments(convId, type = null) {
        let url = `/api/conversations/${convId}/attachments`;
        if (type) url += `?type=${type}`;
        const res = await fetch(url);
        return await res.json();
    }
}

export default ChatAPI;
