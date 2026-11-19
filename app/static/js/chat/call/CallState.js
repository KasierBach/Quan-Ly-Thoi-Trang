/** In-memory lifecycle only: a new socket/page cannot restore a server-bound call. */
export default class CallState {
    constructor() {
        this.current = null;
        this.generation = 0;
    }

    static validSignal(data) {
        return data && typeof data.call_id === 'string' && /^[A-Za-z0-9_-]{16,64}$/.test(data.call_id) &&
            /^\d+$/.test(String(data.conversation_id)) &&
            Number.isSafeInteger(Number(data.conversation_id)) && Number(data.conversation_id) > 0;
    }

    begin(data, phase) {
        if (this.current || !CallState.validSignal(data)) return null;
        this.current = {
            ...data, conversation_id: Number(data.conversation_id),
            generation: ++this.generation, phase
        };
        return this.current;
    }

    isCurrent(call) { return call != null && this.current === call; }
    matches(data) {
        return CallState.validSignal(data) && this.current?.call_id === data.call_id &&
            this.current.conversation_id === Number(data.conversation_id);
    }
    end() {
        const call = this.current;
        this.current = null;
        ++this.generation;
        return call;
    }
}
