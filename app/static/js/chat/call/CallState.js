/**
 * CallState - Manages call state persistence in localStorage
 */
class CallState {
    static STORAGE_KEY = 'active_call_state';
    static CALL_TIMEOUT = 30000; // 30 seconds

    /**
     * Save current call state to localStorage
     */
    static save(conversationId, isVideo, localStream, screenStream) {
        const stream = localStream || screenStream;
        const audioTrack = stream?.getAudioTracks()[0];
        const videoTrack = stream?.getVideoTracks()[0];

        const state = {
            conversation_id: conversationId,
            isVideo: isVideo,
            timestamp: Date.now(),
            micEnabled: audioTrack?.enabled ?? true,
            camEnabled: videoTrack?.enabled ?? true
        };
        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(state));
    }

    /**
     * Clear saved call state
     */
    static clear() {
        localStorage.removeItem(this.STORAGE_KEY);
    }

    /**
     * Get saved call state if still valid
     */
    static get() {
        const stateStr = localStorage.getItem(this.STORAGE_KEY);
        if (!stateStr) return null;

        try {
            const state = JSON.parse(stateStr);
            // Check if call state is still valid (within timeout)
            if (Date.now() - state.timestamp < this.CALL_TIMEOUT) {
                return state;
            }
            // Expired, clean up
            this.clear();
            return null;
        } catch (e) {
            this.clear();
            return null;
        }
    }

    /**
     * Keep call state alive by updating timestamp
     */
    static keepAlive() {
        const stateStr = localStorage.getItem(this.STORAGE_KEY);
        if (stateStr) {
            try {
                const state = JSON.parse(stateStr);
                state.timestamp = Date.now();
                localStorage.setItem(this.STORAGE_KEY, JSON.stringify(state));
            } catch (e) { }
        }
    }

    /**
     * Restore mic/cam state from saved state
     */
    static restoreMediaState(state, localStream) {
        if (!localStream) return;

        // Restore mic state
        const audioTrack = localStream.getAudioTracks()[0];
        if (audioTrack && state.micEnabled !== undefined) {
            audioTrack.enabled = state.micEnabled;

            const btnMic = document.getElementById('btnToggleMic');
            const micIcon = btnMic?.querySelector('i');
            if (micIcon) {
                micIcon.className = state.micEnabled ? 'fas fa-microphone' : 'fas fa-microphone-slash';
            }
            const localMicStatus = document.getElementById('localMicStatus');
            if (localMicStatus) {
                localMicStatus.classList.toggle('muted', !state.micEnabled);
            }
        }

        // Restore cam state
        const videoTrack = localStream.getVideoTracks()[0];
        if (videoTrack && state.camEnabled !== undefined) {
            videoTrack.enabled = state.camEnabled;

            const btnCam = document.getElementById('btnToggleCam');
            const camIcon = btnCam?.querySelector('i');
            if (camIcon) {
                camIcon.className = state.camEnabled ? 'fas fa-video' : 'fas fa-video-slash';
            }
            const placeholder = document.querySelector('#localParticipant .participant-placeholder');
            if (placeholder) {
                placeholder.style.display = state.camEnabled ? 'none' : 'flex';
            }
        }
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CallState;
}
