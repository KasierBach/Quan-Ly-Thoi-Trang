/**
 * Handles voice recording logic using MediaRecorder API.
 */
export default class ChatRecorder {
    constructor(onStopCallback) {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.startTime = null;
        this.timerInterval = null;
        this.onStopCallback = onStopCallback; // Function to call with the audio Blob
    }

    async start() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert('Trình duyệt của bạn không hỗ trợ ghi âm.');
            return false;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.mediaRecorder = new MediaRecorder(stream);
            this.audioChunks = [];

            this.mediaRecorder.ondataavailable = (event) => {
                this.audioChunks.push(event.data);
            };

            this.mediaRecorder.onstop = () => {
                const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' }); // Chrome records as webm/opus
                if (this.onStopCallback) this.onStopCallback(audioBlob);
                this.cleanup();
            };

            this.mediaRecorder.start();
            this.isRecording = true;
            this.startTime = Date.now();
            return true;
        } catch (err) {
            console.error('Error accessing microphone:', err);
            alert('Không thể truy cập microphone. Vui lòng kiểm tra quyền truy cập.');
            return false;
        }
    }

    stop() {
        if (this.mediaRecorder && this.isRecording) {
            this.mediaRecorder.stop();
            this.isRecording = false;
        }
    }

    cancel() {
        if (this.mediaRecorder && this.isRecording) {
            // Remove onstop callback to prevent sending
            this.mediaRecorder.onstop = null;
            this.mediaRecorder.stop();
            this.isRecording = false;
            this.cleanup();
        }
    }

    cleanup() {
        if (this.mediaRecorder) {
            this.mediaRecorder.stream.getTracks().forEach(track => track.stop());
            this.mediaRecorder = null;
        }
        this.audioChunks = [];
    }

    getDuration() {
        if (!this.startTime) return "00:00";
        const diff = Math.floor((Date.now() - this.startTime) / 1000);
        const mins = Math.floor(diff / 60).toString().padStart(2, '0');
        const secs = (diff % 60).toString().padStart(2, '0');
        return `${mins}:${secs}`;
    }
}
