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

function copyStatus() {
    let region = document.getElementById('copy-status');
    if (!region) {
        region = document.createElement('div');
        region.id = 'copy-status';
        region.className = 'sr-only';
        region.setAttribute('role', 'status');
        region.setAttribute('aria-live', 'polite');
        document.body.append(region);
    }
    return region;
}

function selectCode(code) {
    const range = document.createRange();
    range.selectNodeContents(code);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
}

function copyButtons() {
    const status = copyStatus();
    document.querySelectorAll('.codeblock').forEach(block => {
        const button = block.querySelector('.copy-btn');
        const code = block.querySelector('code');
        if (!button || !code) return;
        const label = button.textContent;
        let reset;
        button.addEventListener('click', async () => {
            let copied = false;
            try {
                // The Clipboard API only exists in a secure context; a preview served over
                // plain http from a LAN address has none, so the fallback selects the text.
                await navigator.clipboard.writeText(code.textContent);
                copied = true;
            } catch {
                selectCode(code);
            }
            button.textContent = copied ? 'Copied' : 'Selected';
            button.classList.toggle('copied', copied);
            status.textContent = copied
                ? 'The code is on the clipboard.'
                : 'The clipboard is unavailable here; the code is selected, press Ctrl+C or Command+C.';
            // A second click inside the 1.8 s window would otherwise read "Copied" as the
            // label to restore and leave the button saying it for good.
            window.clearTimeout(reset);
            reset = window.setTimeout(() => {
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
