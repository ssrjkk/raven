/* Registry, filters, reveal and clipboard. Data comes from tools-data.js,
   which scripts/record_site_frames.py generates from `raven-mcp tools/list`. */

document.documentElement.classList.add('js');

const SAMPLE_ARGUMENTS = {
    path: 'README.md',
    file_path: 'README.md',
    pattern: 'docs/*.md',
    include: '*.py',
    command: 'python --version',
    query: 'workspace confinement',
    url: 'https://example.com',
};

const TYPE_DEFAULTS = {
    string: '<string>',
    integer: 1,
    number: 1,
    boolean: false,
    array: [],
    object: {},
};

function sampleValue(name, type) {
    const named = SAMPLE_ARGUMENTS[name];
    if (typeof named === 'string' && (type === 'string' || type === undefined)) return named;
    return TYPE_DEFAULTS[type] ?? TYPE_DEFAULTS.string;
}

function frameFor(tool) {
    const required = tool.required || [];
    const args = {};
    (required.length ? required : Object.keys(tool.params || {})).forEach(name => {
        if (tool.params && name in tool.params) args[name] = sampleValue(name, tool.params[name]);
    });
    return JSON.stringify({
        jsonrpc: '2.0',
        id: 10,
        method: 'tools/call',
        params: { name: tool.name, arguments: args },
    });
}

class Reveal {
    constructor(elements) {
        this.edge = window.innerHeight * 0.85;
        elements.forEach(element => this.check(element));
        if (!('IntersectionObserver' in window)) return;
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

class ToolRegistry {
    constructor({ grid, status, search, filters, tools, onPick }) {
        this.grid = grid;
        this.status = status;
        this.search = search;
        this.filters = Array.from(filters);
        this.tools = tools;
        this.onPick = onPick;
        this.category = 'all';
        this.query = '';

        this.filters.forEach(button => {
            button.addEventListener('click', () => {
                this.category = button.dataset.category;
                this.filters.forEach(other => {
                    other.setAttribute('aria-pressed', String(other === button));
                });
                this.render();
            });
        });

        this.search.addEventListener('input', () => {
            this.query = this.search.value.trim().toLowerCase();
            this.render();
        });

        this.render();
    }

    matches(tool) {
        if (this.category !== 'all' && tool.category !== this.category) return false;
        if (!this.query) return true;
        return tool.name.toLowerCase().includes(this.query)
            || tool.description.toLowerCase().includes(this.query);
    }

    render() {
        const shown = this.tools.filter(tool => this.matches(tool));
        this.grid.textContent = '';

        if (!shown.length) {
            const empty = document.createElement('p');
            empty.className = 'no-results';
            empty.append(`No tool matches “${this.search.value.trim()}”`);
            const reset = document.createElement('button');
            reset.type = 'button';
            reset.textContent = 'clear filters';
            reset.addEventListener('click', () => {
                this.search.value = '';
                this.query = '';
                this.category = 'all';
                this.filters.forEach(other => {
                    other.setAttribute('aria-pressed', String(other.dataset.category === 'all'));
                });
                this.render();
            });
            empty.append(reset);
            this.grid.append(empty);
            this.status.textContent = `0 of ${this.tools.length} tools`;
            return;
        }

        const fragment = document.createDocumentFragment();
        shown.forEach(tool => fragment.append(this.card(tool)));
        this.grid.append(fragment);
        this.status.textContent =
            `${shown.length} of ${this.tools.length} tools`
            + (this.category === 'all' ? '' : ` · category: ${this.category}`)
            + (this.query ? ` · matching “${this.query}”` : '');
    }

    card(tool) {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'tool-card';
        card.setAttribute('aria-label', `Build a tools/call frame for ${tool.name}`);

        const header = document.createElement('div');
        header.className = 'tool-card-header';
        const name = document.createElement('span');
        name.className = 'tool-name';
        name.textContent = tool.name;
        const badge = document.createElement('span');
        badge.className = 'tool-category-badge';
        badge.textContent = tool.category;
        header.append(name, badge);

        const description = document.createElement('p');
        description.className = 'tool-desc';
        description.textContent = tool.description;

        const params = document.createElement('div');
        params.className = 'tool-params';
        const entries = Object.entries(tool.params || {});
        if (!entries.length) {
            const none = document.createElement('span');
            none.className = 'param param-none';
            none.textContent = 'no parameters';
            params.append(none);
        }
        const required = new Set(tool.required || []);
        entries.forEach(([key, type]) => {
            const chip = document.createElement('span');
            chip.className = 'param';
            if (required.has(key)) chip.classList.add('param-required');
            chip.append(`${key}: `);
            const value = document.createElement('span');
            value.className = 'param-type';
            value.textContent = type;
            chip.append(value);
            params.append(chip);
        });

        const hint = document.createElement('span');
        hint.className = 'card-hint';
        hint.textContent = 'build request frame';

        card.append(header, description, params, hint);
        card.addEventListener('click', () => {
            this.grid.querySelectorAll('.tool-card-built').forEach(other => {
                other.classList.remove('tool-card-built');
            });
            card.classList.add('tool-card-built');
            this.onPick(frameFor(tool));
        });
        return card;
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

const tools = typeof TOOLS_DATA === 'undefined' ? [] : TOOLS_DATA;
const frames = new FrameConsole({
    output: document.getElementById('terminal-output'),
    form: document.getElementById('request-form'),
    input: document.getElementById('terminal-command'),
    presets: Array.from(document.querySelectorAll('.ghost-btn[data-cmd]')),
    clearButton: document.getElementById('clear-console'),
    frames: typeof MCP_FRAMES === 'undefined' ? [] : MCP_FRAMES.frames,
    tools,
});

document.querySelectorAll('[data-tool-count]').forEach(element => {
    element.textContent = tools.length;
});

const search = document.getElementById('tool-search');
if (search && tools.length) search.placeholder = `Search ${tools.length} tools`;

new ToolRegistry({
    grid: document.getElementById('tools-grid'),
    status: document.getElementById('registry-status'),
    search,
    filters: document.querySelectorAll('.filter-btn'),
    tools,
    onPick: frame => frames.prefill(frame),
});

copyButtons();
new Reveal(document.querySelectorAll('.section-inner'));

const canvas = document.getElementById('hero-canvas');
if (canvas && typeof HeroBackdrop !== 'undefined') new HeroBackdrop(canvas);
