/* Landing-only behaviour: the scroll rail, pointer light, the generated counts and the
   transport switch on the recorded handshake.

   Nothing here invents a number or a frame. The five counts and the category split come from
   ``site/stats.js``, which ``scripts/record_site_frames.py`` measures from the tree, and the
   console already holds the recorded frames in its markup — this file only changes how they are
   carried, so the page says the same thing with scripting switched off. */

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

/* ---------- the rail under the bar, and the bar that condenses ---------- */

class ScrollRail {
    constructor(bar) {
        this.bar = bar;
        this.root = document.documentElement;
        this.ticking = false;
        this.paint();
        window.addEventListener('scroll', () => this.schedule(), { passive: true });
        window.addEventListener('resize', () => this.schedule(), { passive: true });
    }

    schedule() {
        if (this.ticking) return;
        this.ticking = true;
        window.requestAnimationFrame(() => {
            this.ticking = false;
            this.paint();
        });
    }

    paint() {
        const scrollable = this.root.scrollHeight - window.innerHeight;
        const ratio = scrollable > 0 ? Math.min(1, Math.max(0, window.scrollY / scrollable)) : 1;
        // The CSSOM, not a style attribute: ``style-src 'self'`` drops the latter.
        this.root.style.setProperty('--scroll', ratio.toFixed(4));
        this.bar.classList.toggle('scrolled', window.scrollY > 8);
    }
}

/* ---------- pointer light ---------- */

class PointerLight {
    constructor(elements) {
        elements.forEach(element => {
            element.addEventListener('pointermove', event => {
                if (reducedMotion.matches) return;
                const box = element.getBoundingClientRect();
                element.style.setProperty('--gx', `${event.clientX - box.left}px`);
                element.style.setProperty('--gy', `${event.clientY - box.top}px`);
            });
            element.addEventListener('pointerleave', () => {
                element.style.setProperty('--gx', '50%');
                element.style.setProperty('--gy', '50%');
            });
        });
    }
}

/* ---------- the counts the recorder measured ---------- */

class StatCounters {
    constructor(spans, stats) {
        this.spans = spans;
        this.stats = stats;
        this.settled = 0;
        spans.forEach(span => {
            const value = stats[span.dataset.stat];
            if (typeof value !== 'number') return;
            this.settled += 1;
            span.textContent = String(value);
            if (reducedMotion.matches) return;
            span.dataset.target = String(value);
            span.textContent = '0';
        });
    }

    /* Counting up a number the page already knows is decoration, so it only runs for the
       visitors who asked for motion — and it always lands on the generated value, never near it. */
    run() {
        this.spans.forEach(span => {
            const target = Number(span.dataset.target);
            if (!Number.isFinite(target)) return;
            const start = performance.now();
            const step = now => {
                const t = Math.min(1, (now - start) / 900);
                const eased = 1 - (1 - t) ** 3;
                span.textContent = String(Math.round(target * eased));
                if (t < 1) window.requestAnimationFrame(step);
                else span.textContent = String(target);
            };
            window.requestAnimationFrame(step);
        });
    }
}

/* ---------- registry composition, drawn from the same file ---------- */

class Composition {
    constructor(list, stats) {
        this.list = list;
        this.stats = stats;
    }

    render() {
        const categories = this.stats.categories || {};
        const names = Object.keys(categories);
        if (!names.length) return;
        const total = names.reduce((sum, name) => sum + categories[name], 0);
        const largest = Math.max(...names.map(name => categories[name]));
        this.list.replaceChildren();
        this.list.setAttribute('aria-label', `The registry split across ${names.length} categories, ${total} tools`);
        names.forEach(name => {
            const count = categories[name];
            const item = document.createElement('li');
            item.className = 'composition-row';

            const label = document.createElement('span');
            label.className = 'composition-name';
            label.textContent = name;

            const track = document.createElement('span');
            track.className = 'composition-track';
            const fill = document.createElement('span');
            fill.className = 'composition-fill';
            // Width through the CSSOM so the bar is a measured ratio, not a hand-drawn guess.
            // Ranked against the largest category — the exact count sits at the end of the row.
            fill.style.setProperty('--rel', `${((count / largest) * 100).toFixed(2)}%`);
            track.append(fill);

            const value = document.createElement('span');
            value.className = 'composition-count';
            value.textContent = String(count);

            item.append(label, track, value);
            this.list.append(item);
        });
    }
}

/* ---------- the recorded handshake, on the transport the visitor picks ---------- */

const ENVELOPES = {
    stdio: {
        title: 'raven-mcp — stdio',
        request: 'client → raven-mcp · stdin',
        response: 'raven-mcp → client · stdout',
    },
    http: {
        title: 'raven-mcp — HTTP',
        request: 'POST /mcp/rpc · Authorization: Bearer',
        response: '200 OK · application/json',
    },
};

class TransportSwitch {
    constructor(console_, name, routes) {
        this.console = console_;
        this.name = name;
        this.routes = routes;
        this.inputs = [...document.querySelectorAll('input[name="transport"]')];
        this.inputs.forEach(input => input.addEventListener('change', () => this.apply(input.value)));
        this.apply(this.current());
    }

    current() {
        const checked = this.inputs.find(input => input.checked);
        return checked ? checked.value : 'stdio';
    }

    apply(kind) {
        const envelope = ENVELOPES[kind] || ENVELOPES.stdio;
        // Only the name span: the live dot is its sibling inside the title.
        if (this.name) this.name.textContent = envelope.title;
        this.routes.forEach(route => {
            const line = route.closest('.console-line');
            const isRequest = line.classList.contains('line-request');
            route.textContent = isRequest ? envelope.request : envelope.response;
        });
        this.console.dataset.transport = kind;
    }
}

/* ---------- the replay ---------- */

class Replay {
    constructor(lines) {
        this.lines = lines;
        if (reducedMotion.matches) return;
        lines.forEach(line => line.classList.add('replay-pending'));
        this.play();
    }

    play() {
        window.setTimeout(() => {
            this.lines.forEach((line, index) => {
                window.setTimeout(() => line.classList.remove('replay-pending'), index * 260);
            });
        }, 240);
    }
}

function boot() {
    document.documentElement.classList.add('js');
    const bar = document.querySelector('.navbar');
    if (bar) new ScrollRail(bar);
    new PointerLight(document.querySelectorAll('.feature-card, .door, .explore-card'));

    const stats = typeof RAVEN_STATS === 'undefined' ? null : RAVEN_STATS;
    const counters = new StatCounters(document.querySelectorAll('[data-stat]'), stats || {});
    const composition = document.getElementById('composition-list');
    if (composition && stats) new Composition(composition, stats).render();

    const console_ = document.querySelector('.hero .console');
    if (console_) {
        const name = console_.querySelector('.console-name');
        const routes = [...console_.querySelectorAll('.frame-route')];
        new TransportSwitch(console_, name, routes);
        new Replay([...console_.querySelectorAll('.console-line')]);
    }

    const numbers = document.getElementById('numbers');
    if (numbers && 'IntersectionObserver' in window) {
        const observer = new IntersectionObserver(entries => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) return;
                counters.run();
                observer.disconnect();
            });
        }, { threshold: 0.25 });
        observer.observe(numbers);
    } else {
        counters.run();
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
} else {
    boot();
}
