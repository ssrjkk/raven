/* Hero backdrop: one static paint of the palette's grid and light.
   No animation loop — the canvas is a surface, not a screensaver.
   Colours come from the :root tokens; reduced motion keeps the light centred
   and ignores the pointer so nothing moves under the cursor. */

const HERO_GRID = 64;
const WASH_ALPHA = [0.22, 0.06, 0];
const EDGE_ALPHA = 0.12;
const GRID_ALPHA = 0.055;

function tokenRgba(styles, name, alpha) {
    const hex = styles.getPropertyValue(name).trim().replace('#', '');
    const value = parseInt(hex, 16);
    const red = (value >> 16) & 255;
    const green = (value >> 8) & 255;
    const blue = value & 255;
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

class HeroBackdrop {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.host = canvas.parentElement || canvas;
        this.mouseX = 0.5;
        this.mouseY = 0.5;
        this.reduced = window.matchMedia('(prefers-reduced-motion: reduce)');

        if ('ResizeObserver' in window) {
            this.observer = new ResizeObserver(() => this.schedule());
            this.observer.observe(this.host);
        } else {
            window.addEventListener('resize', () => this.schedule());
        }

        this.host.addEventListener('mousemove', (e) => {
            if (this.reduced.matches) return;
            const rect = this.host.getBoundingClientRect();
            this.mouseX = (e.clientX - rect.left) / rect.width;
            this.mouseY = (e.clientY - rect.top) / rect.height;
            this.schedule();
        });

        this.reduced.addEventListener('change', () => {
            this.mouseX = 0.5;
            this.mouseY = 0.5;
            this.paint();
        });

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
        const styles = window.getComputedStyle(document.documentElement);
        const box = this.host.getBoundingClientRect();
        const width = Math.max(1, Math.round(box.width));
        const height = Math.max(1, Math.round(box.height));
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const fixed = this.reduced.matches;
        const mouseX = fixed ? 0.5 : this.mouseX;
        const mouseY = fixed ? 0.5 : this.mouseY;

        this.canvas.width = width * dpr;
        this.canvas.height = height * dpr;
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        this.ctx.fillStyle = styles.getPropertyValue('--bg').trim();
        this.ctx.fillRect(0, 0, width, height);

        const washX = width * (0.5 + (mouseX - 0.5) * 0.6);
        const washY = height * (0.5 + (mouseY - 0.5) * 0.6);
        const wash = this.ctx.createRadialGradient(
            washX, washY, 0,
            washX, washY, Math.max(width, height) * 0.8,
        );
        wash.addColorStop(0, tokenRgba(styles, '--violet', WASH_ALPHA[0]));
        wash.addColorStop(0.55, tokenRgba(styles, '--violet', WASH_ALPHA[1]));
        wash.addColorStop(1, tokenRgba(styles, '--violet', WASH_ALPHA[2]));
        this.ctx.fillStyle = wash;
        this.ctx.fillRect(0, 0, width, height);

        const edgeX = width * (0.08 + (1 - mouseX) * 0.15);
        const edgeY = height * (0.94 + (1 - mouseY) * 0.1);
        const edge = this.ctx.createRadialGradient(
            edgeX, edgeY, 0,
            edgeX, edgeY, Math.max(width, height) * 0.5,
        );
        edge.addColorStop(0, tokenRgba(styles, '--fuchsia', EDGE_ALPHA));
        edge.addColorStop(1, tokenRgba(styles, '--fuchsia', 0));
        this.ctx.fillStyle = edge;
        this.ctx.fillRect(0, 0, width, height);

        this.ctx.strokeStyle = tokenRgba(styles, '--violet', GRID_ALPHA);
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
