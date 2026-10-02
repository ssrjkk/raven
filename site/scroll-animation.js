class ScrollAnimation {
    constructor() {
        this.canvas = document.getElementById('frame-canvas');
        this.ctx = this.canvas.getContext('2d');
        this.frames = [];
        this.currentFrame = 0;
        this.totalFrames = 0;
        this.sections = document.querySelectorAll('.content-section');
        this.progressFill = document.querySelector('.progress-fill');

        this.init();
    }

    async init() {
        this.resizeCanvas();
        window.addEventListener('resize', () => this.resizeCanvas());

        await this.loadFrames();
        this.setupScrollListener();
        this.updateAnimation();
    }

    resizeCanvas() {
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = window.innerWidth * dpr;
        this.canvas.height = window.innerHeight * dpr;
        this.ctx.scale(dpr, dpr);
        this.canvas.style.width = window.innerWidth + 'px';
        this.canvas.style.height = window.innerHeight + 'px';
    }

    async loadFrames() {
        const frameCount = 300;
        const loadPromises = [];

        for (let i = 0; i < frameCount; i++) {
            const img = new Image();
            const frameNum = String(i).padStart(4, '0');
            img.src = `frames/frame_${frameNum}.jpg`;

            const promise = new Promise((resolve) => {
                img.onload = () => resolve(true);
                img.onerror = () => resolve(false);
            });

            loadPromises.push(promise);
            this.frames.push(img);
        }

        const results = await Promise.all(loadPromises);
        this.totalFrames = results.filter(r => r).length;

        if (this.totalFrames === 0) {
            this.renderPlaceholder();
        }
    }

    renderPlaceholder() {
        const width = window.innerWidth;
        const height = window.innerHeight;

        this.ctx.fillStyle = '#000';
        this.ctx.fillRect(0, 0, width, height);

        this.ctx.strokeStyle = '#a78bfa';
        this.ctx.lineWidth = 2;
        this.ctx.beginPath();

        const gridSize = 40;
        for (let x = 0; x < width; x += gridSize) {
            this.ctx.moveTo(x, 0);
            this.ctx.lineTo(x, height);
        }
        for (let y = 0; y < height; y += gridSize) {
            this.ctx.moveTo(0, y);
            this.ctx.lineTo(width, y);
        }
        this.ctx.stroke();

        this.ctx.fillStyle = '#a78bfa';
        this.ctx.font = '20px Courier New';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('RAVEN MCP SERVER', width / 2, height / 2 - 20);
        this.ctx.font = '14px Courier New';
        this.ctx.fillText('Video frames not yet generated', width / 2, height / 2 + 20);
    }

    setupScrollListener() {
        window.addEventListener('scroll', () => {
            this.updateAnimation();
        }, { passive: true });
    }

    updateAnimation() {
        const scrollTop = window.scrollY;
        const docHeight = document.documentElement.scrollHeight - window.innerHeight;
        const scrollProgress = Math.min(Math.max(scrollTop / docHeight, 0), 1);

        this.progressFill.style.width = (scrollProgress * 100) + '%';

        if (this.totalFrames > 0) {
            const frameIndex = Math.floor(scrollProgress * (this.totalFrames - 1));
            if (frameIndex !== this.currentFrame) {
                this.currentFrame = frameIndex;
                this.renderFrame();
            }
        } else {
            this.renderPlaceholder();
        }

        this.updateSections(scrollProgress);
    }

    renderFrame() {
        const frame = this.frames[this.currentFrame];
        if (!frame) return;

        const canvasWidth = window.innerWidth;
        const canvasHeight = window.innerHeight;
        const imgAspect = frame.width / frame.height;
        const canvasAspect = canvasWidth / canvasHeight;

        let drawWidth, drawHeight, drawX, drawY;

        if (imgAspect > canvasAspect) {
            drawHeight = canvasHeight;
            drawWidth = canvasHeight * imgAspect;
            drawX = (canvasWidth - drawWidth) / 2;
            drawY = 0;
        } else {
            drawWidth = canvasWidth;
            drawHeight = canvasWidth / imgAspect;
            drawX = 0;
            drawY = (canvasHeight - drawHeight) / 2;
        }

        this.ctx.clearRect(0, 0, canvasWidth, canvasHeight);
        this.ctx.drawImage(frame, drawX, drawY, drawWidth, drawHeight);
    }

    updateSections(scrollProgress) {
        this.sections.forEach(section => {
            const start = parseFloat(section.dataset.scrollStart);
            const end = parseFloat(section.dataset.scrollEnd);
            const mid = (start + end) / 2;
            const range = (end - start) / 2;

            if (scrollProgress >= start && scrollProgress <= end) {
                section.classList.add('active');
            } else {
                section.classList.remove('active');
            }
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new ScrollAnimation();
});
