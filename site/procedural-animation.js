/* Hero backdrop: one static paint of the palette's grid and light.
   No animation loop — the canvas is a surface, not a screensaver. */

const HERO_BG = '#0a0812';
const HERO_GRID = 64;
const HERO_LINE = 'rgba(139, 92, 246, 0.055)';

class HeroBackdrop {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.host = canvas.parentElement || canvas;

        if ('ResizeObserver' in window) {
            this.observer = new ResizeObserver(() => this.schedule());
            this.observer.observe(this.host);
        } else {
            window.addEventListener('resize', () => this.schedule());
        }
        this.paint();
    }

    schedule() {
        if (this.pending) return;
        this.pending = window.requestAnimationFrame(() => {
            this.pending = 0;
            this.paint();
        });
    }

    paint() {
        const box = this.host.getBoundingClientRect();
        const width = Math.max(1, Math.round(box.width));
        const height = Math.max(1, Math.round(box.height));
        const dpr = Math.min(window.devicePixelRatio || 1, 2);

        this.canvas.width = width * dpr;
        this.canvas.height = height * dpr;
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        this.ctx.fillStyle = HERO_BG;
        this.ctx.fillRect(0, 0, width, height);

        const wash = this.ctx.createRadialGradient(
            width * 0.78, height * 0.1, 0,
            width * 0.78, height * 0.1, Math.max(width, height) * 0.8,
        );
        wash.addColorStop(0, 'rgba(139, 92, 246, 0.22)');
        wash.addColorStop(0.55, 'rgba(139, 92, 246, 0.06)');
        wash.addColorStop(1, 'rgba(139, 92, 246, 0)');
        this.ctx.fillStyle = wash;
        this.ctx.fillRect(0, 0, width, height);

        const edge = this.ctx.createRadialGradient(
            width * 0.08, height * 0.94, 0,
            width * 0.08, height * 0.94, Math.max(width, height) * 0.5,
        );
        edge.addColorStop(0, 'rgba(217, 70, 239, 0.12)');
        edge.addColorStop(1, 'rgba(217, 70, 239, 0)');
        this.ctx.fillStyle = edge;
        this.ctx.fillRect(0, 0, width, height);

        this.ctx.strokeStyle = HERO_LINE;
        this.ctx.lineWidth = 1;
        this.ctx.beginPath();
        for (let x = 0.5; x <= width; x += HERO_GRID) {
            this.ctx.moveTo(x, 0);
            this.ctx.lineTo(x, height);
        }
        for (let y = 0.5; y <= height; y += HERO_GRID) {
            this.ctx.moveTo(0, y);
            this.ctx.lineTo(width, y);
        }
        this.ctx.stroke();
    }
}
