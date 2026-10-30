/* Shared bootstrap: the js flag, copy buttons, the nav toggle, the reveal
   observer and the hero canvas. The registry and console live in registry.js. */

document.documentElement.classList.add('js');

class Reveal {
    constructor(elements) {
        this.edge = window.innerHeight * 0.85;
        elements.forEach(element => this.check(element));
        if (!('IntersectionObserver' in window)) {
            // With no observer nothing would ever reveal a section below the fold,
            // so the enhancement degrades to every section being visible.
            elements.forEach(element => element.classList.add('visible'));
            return;
        }
        this.observer = new IntersectionObserver(entries => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) return;
                entry.target.classList.add('visible');
                this.observer.unobserve(entry.target);
            });
        }, { rootMargin: '0px 0px -15% 0px' });
        elements.forEach(element => this.observer.observe(element));
    }

    check(element) {
        if (element.getBoundingClientRect().top < this.edge) element.classList.add('visible');
    }
}

function copyButtons() {
    document.querySelectorAll('.codeblock').forEach(block => {
        const button = block.querySelector('.copy-btn');
        const code = block.querySelector('code');
        if (!button || !code) return;
        button.addEventListener('click', async () => {
            const label = button.textContent;
            let ok = false;
            try {
                await navigator.clipboard.writeText(code.textContent);
                ok = true;
            } catch {
                ok = false;
            }
            button.textContent = ok ? 'Copied' : 'Select and copy';
            button.classList.toggle('copied', ok);
            window.setTimeout(() => {
                button.textContent = label;
                button.classList.remove('copied');
            }, 1800);
        });
    });
}

function primaryNavToggle() {
    const bar = document.querySelector('.navbar');
    const button = bar.querySelector('.nav-toggle');
    const close = () => {
        bar.classList.remove('nav-open');
        button.setAttribute('aria-expanded', 'false');
    };

    button.addEventListener('click', () => {
        const open = bar.classList.toggle('nav-open');
        button.setAttribute('aria-expanded', String(open));
    });
    bar.querySelectorAll('.nav-links a').forEach(link => link.addEventListener('click', close));
    // Escape while the panel is closed belongs to whatever the visitor is typing into.
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && bar.classList.contains('nav-open')) {
            close();
            button.focus();
        }
    });
    window.matchMedia('(min-width: 901px)').addEventListener('change', close);
}

copyButtons();
primaryNavToggle();
new Reveal(document.querySelectorAll('.section-inner'));

const canvas = document.getElementById('hero-canvas');
if (canvas && typeof HeroBackdrop !== 'undefined') new HeroBackdrop(canvas);
