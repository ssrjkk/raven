/* Registry and request console. Data comes from tools-data.js and mcp-frames.js,
   which scripts/record_site_frames.py generates from a live raven-mcp process. */

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

/* #tool=read and #cat=file make a registry state linkable. replaceState keeps the address
   bar in step without pushing a history entry for every click. */
function hashState() {
    const params = new URLSearchParams(location.hash.slice(1));
    return { category: params.get('cat') || 'all', tool: params.get('tool') };
}

function writeHash(state) {
    const params = new URLSearchParams();
    if (state.tool) params.set('tool', state.tool);
    if (state.category && state.category !== 'all') params.set('cat', state.category);
    const hash = params.toString();
    history.replaceState(null, '', `${location.pathname}${location.search}${hash ? `#${hash}` : ''}`);
}

class ToolRegistry {
    constructor({
        grid,
        empty,
        status,
        search,
        filters,
        tools,
        onPick,
        initialCategory = 'all',
        onNavigate,
        onFilter,
    }) {
        this.grid = grid;
        this.empty = empty;
        this.status = status;
        this.search = search;
        this.filters = Array.from(filters);
        this.tools = tools;
        this.onPick = onPick;
        this.onNavigate = onNavigate;
        this.onFilter = onFilter;
        this.category = 'all';
        this.query = '';

        this.filters.forEach(button => {
            button.addEventListener('click', () => {
                this.setCategory(button.dataset.category);
                this.onFilter?.(this.category);
            });
        });

        this.search.addEventListener('input', () => {
            clearTimeout(this._searchTimer);
            this._searchTimer = setTimeout(() => {
                this.query = this.search.value.trim().toLowerCase();
                this.render();
            }, 120);
        });

        document.addEventListener('keydown', event => {
            if (event.isComposing || event.keyCode === 229) return;
            if (event.key !== '/' || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
            const typing = event.target instanceof HTMLElement
                && event.target.closest('input, textarea, select, [contenteditable="true"]');
            if (typing) return;
            this.search.focus();
            event.preventDefault();
        });

        if (!this.setCategory(initialCategory)) this.setCategory('all');
    }

    setCategory(category) {
        const button = this.filters.find(other => other.dataset.category === category);
        if (!button) return false;
        this.category = category;
        this.filters.forEach(other => {
            other.setAttribute('aria-pressed', String(other === button));
        });
        this.render();
        return true;
    }

    selectTool(name) {
        const tool = this.tools.find(entry => entry.name === name);
        if (!tool) return false;
        this.search.value = '';
        this.query = '';
        this.setCategory('all');
        const card = Array.from(this.grid.querySelectorAll('.tool-card'))
            .find(entry => entry.dataset.tool === name);
        if (card) {
            card.classList.add('tool-card-built');
            card.scrollIntoView({ block: 'center' });
        }
        // A link shows the card and fills the console; only a click moves focus to the input.
        this.onPick(frameFor(tool), { focus: false });
        return true;
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
        this.empty.textContent = '';
        this.empty.hidden = true;

        if (!shown.length) {
            this.empty.append(`No tool matches “${this.search.value.trim()}”`);
            const reset = document.createElement('button');
            reset.type = 'button';
            reset.textContent = 'clear filters';
            reset.addEventListener('click', () => {
                this.search.value = '';
                this.query = '';
                this.setCategory('all');
                this.onFilter?.('all');
                this.search.focus();
            });
            this.empty.append(reset);
            this.empty.hidden = false;
            this.status.textContent = `0 of ${this.tools.length} tools`;
            return;
        }

        const fragment = document.createDocumentFragment();
        shown.forEach(tool => {
            // The grid is a list of 66 buttons, so each card needs its own listitem: a button
            // cannot carry both roles, and a bare <p> in a <ul> is invalid markup.
            const item = document.createElement('li');
            item.className = 'tool-item';
            item.append(this.card(tool));
            fragment.append(item);
        });
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
        card.dataset.tool = tool.name;

        const header = document.createElement('span');
        header.className = 'tool-card-header';
        const name = document.createElement('span');
        name.className = 'tool-name';
        name.id = `tool-name-${tool.name}`;
        name.textContent = tool.name;
        const badge = document.createElement('span');
        badge.className = 'tool-category-badge';
        badge.textContent = tool.category;
        header.append(name, badge);

        const description = document.createElement('span');
        description.className = 'tool-desc';
        description.id = `tool-desc-${tool.name}`;
        description.textContent = tool.description;
        // The card names itself from the text a sighted visitor reads instead of a
        // second, hidden sentence; the description follows as the accessible description.
        card.setAttribute('aria-labelledby', name.id);
        card.setAttribute('aria-describedby', description.id);

        const params = document.createElement('span');
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

        card.append(header, description, params);
        card.addEventListener('click', () => {
            this.grid.querySelectorAll('.tool-card-built').forEach(other => {
                other.classList.remove('tool-card-built');
            });
            card.classList.add('tool-card-built');
            this.onPick(frameFor(tool));
            this.onNavigate?.(tool.name);
        });
        return card;
    }
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

const initial = hashState();
const registry = new ToolRegistry({
    grid: document.getElementById('tools-grid'),
    empty: document.getElementById('registry-empty'),
    status: document.getElementById('registry-status'),
    search,
    filters: document.querySelectorAll('.filter-btn'),
    tools,
    onPick: (frame, options) => frames.prefill(frame, options),
    initialCategory: initial.category,
    onNavigate: name => writeHash({ tool: name }),
    onFilter: category => writeHash({ category }),
});

if (initial.tool) registry.selectTool(initial.tool);

window.addEventListener('hashchange', () => {
    const state = hashState();
    if (state.tool) registry.selectTool(state.tool);
    else registry.setCategory(state.category);
});
