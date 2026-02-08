/**
 * Image Viewer Service
 * Handles full-screen image viewing with smooth interactions.
 */
class ImageViewer {
    constructor() {
        this.modal = document.getElementById('imageViewerModal');
        this.img = document.getElementById('viewerImage');
        this.content = document.getElementById('viewerContent');
        this.info = document.getElementById('viewerInfo');

        // Buttons
        this.closeBtn = document.getElementById('viewerCloseBtn');
        this.prevBtn = document.getElementById('viewerPrevBtn');
        this.nextBtn = document.getElementById('viewerNextBtn');
        this.zoomInBtn = document.getElementById('zoomInBtn');
        this.zoomOutBtn = document.getElementById('zoomOutBtn');
        this.resetBtn = document.getElementById('resetBtn');
        this.rotateLeftBtn = document.getElementById('rotateLeftBtn');
        this.rotateRightBtn = document.getElementById('rotateRightBtn');
        this.flipHBtn = document.getElementById('flipHBtn');
        this.downloadBtn = document.getElementById('downloadBtn');

        // State
        this.images = [];
        this.currentIndex = -1;
        this.scale = 1;
        this.rotation = 0;
        this.flipH = false;
        this.isDragging = false;
        this.startX = 0;
        this.startY = 0;
        this.translateX = 0;
        this.translateY = 0;

        // Inertia properties
        this.lastX = 0;
        this.lastY = 0;
        this.velocityX = 0;
        this.velocityY = 0;
        this.inertiaFrame = null;

        this.initEvents();
    }

    initEvents() {
        if (!this.modal || !this.content) return;

        // Button Listeners
        this.closeBtn?.addEventListener('click', () => this.close());
        this.prevBtn?.addEventListener('click', () => this.prev());
        this.nextBtn?.addEventListener('click', () => this.next());
        this.zoomInBtn?.addEventListener('click', () => this.zoom(0.2));
        this.zoomOutBtn?.addEventListener('click', () => this.zoom(-0.2));
        this.resetBtn?.addEventListener('click', () => this.reset());
        this.rotateLeftBtn?.addEventListener('click', () => this.rotate(-90));
        this.rotateRightBtn?.addEventListener('click', () => this.rotate(90));
        this.flipHBtn?.addEventListener('click', () => this.toggleFlipH());
        this.downloadBtn?.addEventListener('click', () => this.download());

        // Prevent browser default drag
        if (this.img) {
            this.img.setAttribute('draggable', 'false');
            this.img.addEventListener('dragstart', (e) => e.preventDefault());
        }

        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal || e.target === this.content) {
                this.close();
            }
        });

        this.content.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            e.preventDefault();

            this.isDragging = true;
            this.startX = e.clientX - this.translateX;
            this.startY = e.clientY - this.translateY;
            this.lastX = e.clientX;
            this.lastY = e.clientY;

            cancelAnimationFrame(this.inertiaFrame);
            this.velocityX = 0;
            this.velocityY = 0;

            this.content.style.cursor = 'grabbing';
        });

        window.addEventListener('mousemove', (e) => {
            if (!this.isDragging) return;

            this.translateX = e.clientX - this.startX;
            this.translateY = e.clientY - this.startY;

            this.velocityX = e.clientX - this.lastX;
            this.velocityY = e.clientY - this.lastY;
            this.lastX = e.clientX;
            this.lastY = e.clientY;

            this.updateTransform();
        });

        window.addEventListener('mouseup', () => {
            if (!this.isDragging) return;
            this.isDragging = false;
            this.content.style.cursor = 'grab';

            if (Math.abs(this.scale - 1) < 0.1) {
                if (Math.abs(this.translateY) > 200) {
                    this.close();
                    return;
                }
            }

            this.applyInertia();
        });

        this.content.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY > 0 ? -0.2 : 0.2;
            this.zoom(delta);
        }, { passive: false });

        // Keyboard support
        window.addEventListener('keydown', (e) => {
            if (!this.modal.classList.contains('active')) return;

            switch (e.key) {
                case 'Escape': this.close(); break;
                case 'ArrowLeft': this.prev(); break;
                case 'ArrowRight': this.next(); break;
                case '+':
                case '=': this.zoom(0.2); break;
                case '-':
                case '_': this.zoom(-0.2); break;
                case '0': this.reset(); break;
                case 'l':
                case 'L': this.rotate(-90); break;
                case 'r':
                case 'R': this.rotate(90); break;
                case 'h':
                case 'H': this.toggleFlipH(); break;
            }
        });
    }

    toggleFlipH() {
        this.flipH = !this.flipH;
        this.updateTransform();
    }

    scanImages() {
        // Collect all images from the current chat area
        const imgEls = document.querySelectorAll('.message-image img');
        this.images = Array.from(imgEls).map(el => el.src);
    }

    open(url) {
        if (!this.modal || !this.img) return;

        this.scanImages();
        this.currentIndex = this.images.indexOf(url);
        if (this.currentIndex === -1) {
            this.images = [url];
            this.currentIndex = 0;
        }

        this.showImage();
        this.modal.classList.add('active');
        this.reset();
    }

    showImage() {
        if (this.currentIndex < 0 || this.currentIndex >= this.images.length) return;

        const url = this.images[this.currentIndex];
        this.img.src = url;

        if (this.info) {
            this.info.textContent = `${this.currentIndex + 1} / ${this.images.length}`;
        }

        this.img.onload = () => {
            this.reset();
            this.img.style.opacity = '1';
        };
        this.img.style.opacity = '0';

        // Update nav buttons visibility
        if (this.prevBtn) this.prevBtn.style.display = this.images.length > 1 ? 'flex' : 'none';
        if (this.nextBtn) this.nextBtn.style.display = this.images.length > 1 ? 'flex' : 'none';
    }

    prev() {
        if (this.images.length <= 1) return;
        this.currentIndex = (this.currentIndex - 1 + this.images.length) % this.images.length;
        this.showImage();
    }

    next() {
        if (this.images.length <= 1) return;
        this.currentIndex = (this.currentIndex + 1) % this.images.length;
        this.showImage();
    }

    applyInertia() {
        const friction = 0.95;
        const step = () => {
            if (Math.abs(this.velocityX) < 0.1 && Math.abs(this.velocityY) < 0.1) {
                cancelAnimationFrame(this.inertiaFrame);
                return;
            }

            this.velocityX *= friction;
            this.velocityY *= friction;

            this.translateX += this.velocityX;
            this.translateY += this.velocityY;

            this.updateTransform();
            this.inertiaFrame = requestAnimationFrame(step);
        };
        this.inertiaFrame = requestAnimationFrame(step);
    }

    close() {
        if (this.modal) {
            this.modal.classList.remove('active');
            cancelAnimationFrame(this.inertiaFrame);
        }
    }

    zoom(delta) {
        const oldScale = this.scale;
        this.scale = Math.max(0.1, Math.min(10, this.scale + delta));

        if (this.scale <= 1) {
            this.translateX *= (this.scale / oldScale);
            this.translateY *= (this.scale / oldScale);
        }

        this.updateTransform();
    }

    rotate(deg) {
        this.rotation += deg;
        this.updateTransform();
    }

    reset() {
        this.scale = 1;
        this.rotation = 0;
        this.flipH = false;
        this.translateX = 0;
        this.translateY = 0;
        this.velocityX = 0;
        this.velocityY = 0;
        cancelAnimationFrame(this.inertiaFrame);
        this.updateTransform();
    }

    updateTransform() {
        if (this.img) {
            this.img.style.transition = this.isDragging ? 'none' : 'transform 0.2s cubic-bezier(0.2, 0.8, 0.2, 1)';

            const rotateStr = `rotate(${this.rotation}deg)`;
            const scaleStr = `scale(${this.scale * (this.flipH ? -1 : 1)}, ${this.scale})`;
            const translateStr = `translate(${this.translateX}px, ${this.translateY}px)`;

            // Note: Order matters for transform. ScaleX(-1) should be independent of rotation for flip.
            // But we can combine them.
            this.img.style.transform = `${translateStr} ${scaleStr} ${rotateStr}`;

            if (this.scale <= 1.1) {
                const opacity = Math.max(0.5, 1 - Math.abs(this.translateY) / 1000);
                this.modal.style.background = `rgba(0, 0, 0, ${opacity * 0.95})`;
            } else {
                this.modal.style.background = `rgba(0, 0, 0, 0.95)`;
            }
        }
    }

    download() {
        if (!this.img || !this.img.src) return;
        const link = document.createElement('a');
        link.href = this.img.src;
        const filename = this.img.src.split('/').pop() || 'image';
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
}

export default ImageViewer;
