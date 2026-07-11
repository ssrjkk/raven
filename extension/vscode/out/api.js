"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.RavenApi = void 0;
class RavenApi {
    endpoint;
    constructor(endpoint) {
        this.endpoint = endpoint;
    }
    get urlBase() {
        const e = this.endpoint.replace(/\/+$/, '');
        return e;
    }
    async call(action, code, context = '') {
        try {
            const resp = await fetch(`${this.urlBase}/api/raven`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action, code: code.slice(0, 2000), context: context.slice(0, 500) }),
            });
            if (!resp.ok) {
                const text = await resp.text();
                return `Error ${resp.status}: ${text}`;
            }
            const data = (await resp.json());
            return data.response || '(no response)';
        }
        catch (e) {
            return `Connection error: ${e.message}. Ensure Raven gateway is running on ${this.endpoint}. Try: raven start`;
        }
    }
    async review(code, filename) {
        const text = await this.call('review', code, filename);
        const diagnostics = [];
        const lines = text.split('\n');
        for (const line of lines) {
            const m = line.match(/^Line\s+(\d+)(?::(\d+))?\s*-\s*(\d+)(?::(\d+))?\s*\[(\w+)\]\s*(.+)$/);
            if (m) {
                diagnostics.push({
                    line: parseInt(m[1]) - 1,
                    column: m[2] ? parseInt(m[2]) - 1 : 0,
                    endLine: parseInt(m[3]) - 1,
                    endColumn: m[4] ? parseInt(m[4]) - 1 : 100,
                    message: m[6],
                    severity: m[5] === 'error' ? 'error' : m[5] === 'warning' ? 'warning' : 'info',
                    category: 'Raven Review',
                });
            }
        }
        return { diagnostics, summary: text };
    }
    async health() {
        try {
            const resp = await fetch(`${this.urlBase}/health`, { method: 'GET', signal: AbortSignal.timeout(3000) });
            return resp.ok;
        }
        catch {
            return false;
        }
    }
}
exports.RavenApi = RavenApi;
