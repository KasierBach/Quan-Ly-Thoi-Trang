/** Recorder media work is cancelled when the page or recording is closed. */
export default class ChatRecorder {
    constructor(onStopCallback) {
        this.onStopCallback = onStopCallback;
        this.mediaRecorder = null;
        this.isRecording = false;
        this.pending = false;
        this.generation = 0;
        this.startTime = null;
    }

    async start() {
        if (this.pending || this.isRecording) return false;
        if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder !== 'function') {
            throw new Error('Trình duyệt không hỗ trợ ghi âm');
        }
        this.pending = true;
        const generation = ++this.generation;
        let stream;
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            if (generation !== this.generation) {
                stream.getTracks().forEach(track => track.stop());
                return false;
            }
            const mime = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm']
                .find(type => MediaRecorder.isTypeSupported(type));
            if (!mime) throw new Error('Định dạng ghi âm của trình duyệt chưa được hỗ trợ');
            const recorder = new MediaRecorder(stream, { mimeType: mime });
            const chunks = [];
            this.mediaRecorder = recorder;
            recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
            recorder.onstop = () => {
                stream.getTracks().forEach(track => track.stop());
                if (this.mediaRecorder === recorder) this.mediaRecorder = null;
                if (generation === this.generation && chunks.length) {
                    Promise.resolve(this.onStopCallback?.(new Blob(chunks, { type: mime })))
                        .catch(error => console.error('Không thể gửi bản ghi âm:', error.message));
                }
            };
            recorder.onerror = () => this.cancel();
            recorder.start();
            this.isRecording = true;
            this.startTime = Date.now();
            return true;
        } catch (error) {
            stream?.getTracks().forEach(track => track.stop());
            this.mediaRecorder = null;
            throw error;
        } finally {
            if (generation === this.generation) this.pending = false;
        }
    }

    stop() {
        const recorder = this.mediaRecorder;
        if (recorder && recorder.state !== 'inactive') recorder.stop();
        this.isRecording = false;
    }

    cancel() {
        ++this.generation;
        this.pending = false;
        this.isRecording = false;
        const recorder = this.mediaRecorder;
        this.mediaRecorder = null;
        if (recorder) {
            recorder.onstop = null;
            recorder.ondataavailable = null;
            if (recorder.state !== 'inactive') recorder.stop();
            recorder.stream.getTracks().forEach(track => track.stop());
        }
    }

    cleanup() { this.cancel(); }
    getDuration() {
        const elapsed = this.startTime ? Math.floor((Date.now() - this.startTime) / 1000) : 0;
        return `${Math.floor(elapsed / 60).toString().padStart(2, '0')}:${(elapsed % 60).toString().padStart(2, '0')}`;
    }
}
