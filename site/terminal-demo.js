/* Replays the frames recorded from a live raven-mcp process (site/mcp-frames.js).
   Nothing here talks to a server: requests are parsed in the browser and answered
   from the recording, so every byte shown came from the real implementation. */

const PREVIEW_TOOLS = 8;
const FRAME_CHAR_LIMIT = 1200;
const TOOL_CHAR_LIMIT = 230;

function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === 'object') {
        const out = {};
        Object.keys(value).sort().forEach(key => { out[key] = canonical(value[key]); });
        return out;
    }
    return value;
}

function signature(frame) {
    return JSON.stringify([frame.method, canonical(frame.params === undefined ? {} : frame.params)]);
}

function clampJson(value, limit) {
    const text = JSON.stringify(value);
    if (text.length <= limit) return text;
    return `${text.slice(0, limit)} … [+${text.length - limit} chars in the recorded frame]`;
}

class FrameConsole {
    constructor({ output, form, input, presets, clearButton, frames, tools }) {
        this.output = output;
        this.form = form;
        this.input = input;
        this.byId = new Map();
        frames.forEach(frame => this.byId.set(signature(frame.request), frame));
        this.registered = new Set(tools.map(tool => tool.name));
        this.bind(presets, clearButton);
        this.system(`// ${frames.length} request/response pairs recorded from raven-mcp — pick a method below`);
    }

    bind(presets, clearButton) {
        this.form.addEventListener('submit', event => {
            event.preventDefault();
            this.send(this.input.value);
        });

        this.input.addEventListener('input', () => {
            this.input.style.height = 'auto';
            this.input.style.height = `${this.input.scrollHeight}px`;
        });

        this.input.addEventListener('keydown', event => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                this.send(this.input.value);
            }
        });

        presets.forEach(button => {
            button.addEventListener('click', () => {
                this.input.value = button.dataset.cmd;
                this.send(button.dataset.cmd);
            });
        });

        clearButton.addEventListener('click', () => {
            this.output.textContent = '';
            this.system('// console cleared');
        });
    }

    line(text, kind) {
        const row = document.createElement('div');
        row.className = `console-line line-${kind}`;
        row.textContent = text;
        this.output.appendChild(row);
        this.output.scrollTop = this.output.scrollHeight;
        return row;
    }

    request(text) { this.line(text, 'request'); }
    response(text) { this.line(text, 'response'); }
    system(text) { this.line(text, 'system'); }
    note(text) { this.line(text, 'key'); }
    error(text) { this.line(text, 'error'); }

    prefill(frameText) {
        this.input.value = frameText;
        this.input.focus();
        this.input.setSelectionRange(frameText.length, frameText.length);
    }

    send(raw) {
        const text = raw.trim();
        if (!text) return;
        this.input.style.height = '';
        let frame;
        try {
            frame = JSON.parse(text);
        } catch (problem) {
            this.request(`> ${text}`);
            this.error(`// the browser could not parse that frame: ${problem.message}`);
            return;
        }

        if (!frame || typeof frame !== 'object' || typeof frame.method !== 'string') {
            this.request(`> ${text}`);
            this.error('// not a JSON-RPC request frame: a string "method" is required');
            return;
        }

        this.request(`→ ${clampJson(frame, FRAME_CHAR_LIMIT)}`);

        const recorded = this.byId.get(signature(frame));
        if (recorded) {
            this.replay(frame, recorded);
            return;
        }
        this.missing(frame);
    }

    replay(frame, recorded) {
        if (recorded.response === null) {
            this.system('// notification — the server sends no response frame on the wire');
            return;
        }
        const answer = JSON.parse(JSON.stringify(recorded.response));
        if (frame.id !== undefined) answer.id = frame.id;

        if (answer.error) {
            this.response(`← ${JSON.stringify(answer)}`);
            this.error(`// server error ${answer.error.code}: ${answer.error.message}`);
            return;
        }

        const result = answer.result || {};
        if (Array.isArray(result.tools)) {
            this.response(`← {"jsonrpc":"2.0","id":${answer.id},"result":{"tools":[`);
            result.tools.slice(0, PREVIEW_TOOLS).forEach(tool => {
                this.response(`  ${clampJson(tool, TOOL_CHAR_LIMIT)}`);
            });
            const hidden = result.tools.length - PREVIEW_TOOLS;
            if (hidden > 0) this.note(`  // ${hidden} more tools in this frame, every one listed in the registry above`);
            this.response(']}}');
            return;
        }

        this.response(`← ${clampJson(answer, FRAME_CHAR_LIMIT)}`);

        (result.content || []).forEach((part, index) => {
            if (part.type !== 'text') return;
            const lines = part.text.split('\n');
            this.note(`// decoded result.content[${index}].text — ${lines.length} line${lines.length === 1 ? '' : 's'}, as the server sent it`);
            lines.slice(0, 14).forEach(line => this.note(`  ${line}`));
            if (lines.length > 14) this.note(`  // … ${lines.length - 14} more lines`);
        });
    }

    missing(frame) {
        if (frame.method === 'tools/call') {
            const name = (frame.params || {}).name;
            if (typeof name !== 'string' || !name) {
                this.system('// no name in params — a running server replies -32602 "Missing tool name"');
                return;
            }
            if (this.registered.has(name)) {
                this.system(`// "${name}" is registered, so a running server answers this frame — these arguments are not in the recording`);
                return;
            }
            this.system(`// "${name}" is not in the registry — a running server replies -32602 for an unknown tool`);
            return;
        }
        if (frame.method.startsWith('notifications/')) {
            this.system('// notification — the server sends no response frame on the wire');
            return;
        }
        this.system('// no recording of this frame; a running raven-mcp server answers it live');
    }
}
