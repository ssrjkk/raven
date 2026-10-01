class ProceduralAnimation {
    constructor() {
        this.canvas = document.getElementById('frame-canvas');
        this.ctx = this.canvas.getContext('2d');
        this.sections = document.querySelectorAll('.content-section');
        this.progressFill = document.querySelector('.progress-fill');

        this.time = 0;
        this.nodes = [];
        this.particles = [];
        this.dataStreams = [];

        this.init();
    }

    init() {
        this.resizeCanvas();
        window.addEventListener('resize', () => this.resizeCanvas());

        this.generateNodes();
        this.generateParticles();
        this.animate();
        this.setupScrollListener();
    }

    resizeCanvas() {
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = window.innerWidth * dpr;
        this.canvas.height = window.innerHeight * dpr;
        this.ctx.scale(dpr, dpr);
        this.canvas.style.width = window.innerWidth + 'px';
        this.canvas.style.height = window.innerHeight + 'px';
        this.width = window.innerWidth;
        this.height = window.innerHeight;
    }

    generateNodes() {
        this.nodes = [];
        const count = 30;
        for (let i = 0; i < count; i++) {
            this.nodes.push({
                x: Math.random() * this.width,
                y: Math.random() * this.height,
                vx: (Math.random() - 0.5) * 0.5,
                vy: (Math.random() - 0.5) * 0.5,
                radius: Math.random() * 3 + 2,
                pulse: Math.random() * Math.PI * 2,
            });
        }
    }

    generateParticles() {
        this.particles = [];
        const count = 50;
        for (let i = 0; i < count; i++) {
            this.particles.push({
                x: Math.random() * this.width,
                y: Math.random() * this.height,
                vx: (Math.random() - 0.5) * 2,
                vy: (Math.random() - 0.5) * 2,
                life: Math.random(),
                maxLife: Math.random() * 2 + 1,
            });
        }
    }

    setupScrollListener() {
        window.addEventListener('scroll', () => {
            const scrollTop = window.scrollY;
            const docHeight = document.documentElement.scrollHeight - window.innerHeight;
            const scrollProgress = Math.min(Math.max(scrollTop / docHeight, 0), 1);
            this.progressFill.style.width = (scrollProgress * 100) + '%';
            this.updateSections(scrollProgress);
        }, { passive: true });
    }

    updateSections(scrollProgress) {
        this.sections.forEach(section => {
            const start = parseFloat(section.dataset.scrollStart);
            const end = parseFloat(section.dataset.scrollEnd);

            if (scrollProgress >= start && scrollProgress <= end) {
                section.classList.add('active');
            } else {
                section.classList.remove('active');
            }
        });
    }

    animate() {
        this.time += 0.016;
        this.ctx.fillStyle = 'rgba(10, 10, 10, 0.1)';
        this.ctx.fillRect(0, 0, this.width, this.height);

        this.drawGrid();
        this.drawNodes();
        this.drawConnections();
        this.drawParticles();
        this.drawDataStreams();
        this.drawScanlines();

        requestAnimationFrame(() => this.animate());
    }

    drawGrid() {
        this.ctx.strokeStyle = 'rgba(0, 255, 65, 0.1)';
        this.ctx.lineWidth = 1;

        const gridSize = 60;
        const offsetX = (this.time * 10) % gridSize;
        const offsetY = (this.time * 5) % gridSize;

        this.ctx.beginPath();
        for (let x = -gridSize + offsetX; x < this.width + gridSize; x += gridSize) {
            this.ctx.moveTo(x, 0);
            this.ctx.lineTo(x, this.height);
        }
        for (let y = -gridSize + offsetY; y < this.height + gridSize; y += gridSize) {
            this.ctx.moveTo(0, y);
            this.ctx.lineTo(this.width, y);
        }
        this.ctx.stroke();
    }

    drawNodes() {
        this.nodes.forEach(node => {
            node.x += node.vx;
            node.y += node.vy;
            node.pulse += 0.05;

            if (node.x < 0 || node.x > this.width) node.vx *= -1;
            if (node.y < 0 || node.y > this.height) node.vy *= -1;

            const pulseSize = Math.sin(node.pulse) * 2;
            const radius = node.radius + pulseSize;

            const gradient = this.ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, radius * 3);
            gradient.addColorStop(0, 'rgba(0, 255, 65, 0.8)');
            gradient.addColorStop(0.5, 'rgba(0, 255, 65, 0.3)');
            gradient.addColorStop(1, 'rgba(0, 255, 65, 0)');

            this.ctx.fillStyle = gradient;
            this.ctx.beginPath();
            this.ctx.arc(node.x, node.y, radius * 3, 0, Math.PI * 2);
            this.ctx.fill();

            this.ctx.fillStyle = '#00ff41';
            this.ctx.beginPath();
            this.ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
            this.ctx.fill();
        });
    }

    drawConnections() {
        this.ctx.strokeStyle = 'rgba(0, 255, 65, 0.2)';
        this.ctx.lineWidth = 1;

        for (let i = 0; i < this.nodes.length; i++) {
            for (let j = i + 1; j < this.nodes.length; j++) {
                const dx = this.nodes[i].x - this.nodes[j].x;
                const dy = this.nodes[i].y - this.nodes[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);

                if (dist < 150) {
                    const opacity = (1 - dist / 150) * 0.3;
                    this.ctx.strokeStyle = `rgba(0, 255, 65, ${opacity})`;
                    this.ctx.beginPath();
                    this.ctx.moveTo(this.nodes[i].x, this.nodes[i].y);
                    this.ctx.lineTo(this.nodes[j].x, this.nodes[j].y);
                    this.ctx.stroke();
                }
            }
        }
    }

    drawParticles() {
        this.particles.forEach(p => {
            p.x += p.vx;
            p.y += p.vy;
            p.life += 0.016;

            if (p.life > p.maxLife) {
                p.x = Math.random() * this.width;
                p.y = Math.random() * this.height;
                p.life = 0;
            }

            if (p.x < 0 || p.x > this.width) p.vx *= -1;
            if (p.y < 0 || p.y > this.height) p.vy *= -1;

            const alpha = 1 - (p.life / p.maxLife);
            this.ctx.fillStyle = `rgba(0, 255, 255, ${alpha * 0.6})`;
            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, 2, 0, Math.PI * 2);
            this.ctx.fill();
        });
    }

    drawDataStreams() {
        if (Math.random() < 0.05) {
            this.dataStreams.push({
                x: Math.random() * this.width,
                y: 0,
                speed: Math.random() * 3 + 2,
                length: Math.random() * 100 + 50,
            });
        }

        this.dataStreams = this.dataStreams.filter(stream => {
            stream.y += stream.speed;

            const gradient = this.ctx.createLinearGradient(stream.x, stream.y, stream.x, stream.y + stream.length);
            gradient.addColorStop(0, 'rgba(0, 255, 65, 0)');
            gradient.addColorStop(0.5, 'rgba(0, 255, 65, 0.5)');
            gradient.addColorStop(1, 'rgba(0, 255, 65, 0)');

            this.ctx.strokeStyle = gradient;
            this.ctx.lineWidth = 2;
            this.ctx.beginPath();
            this.ctx.moveTo(stream.x, stream.y);
            this.ctx.lineTo(stream.x, stream.y + stream.length);
            this.ctx.stroke();

            return stream.y < this.height + stream.length;
        });
    }

    drawScanlines() {
        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.03)';
        for (let y = 0; y < this.height; y += 4) {
            this.ctx.fillRect(0, y, this.width, 2);
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('frame-canvas');
    const ctx = canvas.getContext('2d');

    const frameImages = [];
    let framesLoaded = 0;

    for (let i = 0; i < 300; i++) {
        const img = new Image();
        const frameNum = String(i).padStart(4, '0');
        img.src = `frames/frame_${frameNum}.jpg`;
        img.onload = () => {
            framesLoaded++;
            if (framesLoaded > 10) {
                new ScrollAnimation();
                return;
            }
        };
        frameImages.push(img);
    }

    setTimeout(() => {
        if (framesLoaded < 10) {
            new ProceduralAnimation();
        }
    }, 2000);
});
