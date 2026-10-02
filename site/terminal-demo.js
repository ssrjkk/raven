class TerminalDemo {
    constructor() {
        this.output = document.getElementById('terminal-output');
        this.input = document.getElementById('terminal-command');
        this.exampleBtns = document.querySelectorAll('.example-btn');

        this.responses = {
            'initialize': {
                jsonrpc: "2.0",
                id: 1,
                result: {
                    protocolVersion: "2025-03-26",
                    capabilities: { tools: {} },
                    serverInfo: { name: "raven-mcp", version: "0.4.8" }
                }
            },
            'tools/list': {
                jsonrpc: "2.0",
                id: 2,
                result: {
                    tools: [
                        { name: "read", description: "Read files with line numbers", inputSchema: { type: "object", properties: { path: { type: "string" } } } },
                        { name: "write", description: "Create or overwrite files", inputSchema: { type: "object", properties: { path: { type: "string" }, content: { type: "string" } } } },
                        { name: "edit", description: "Surgical string replacements", inputSchema: { type: "object", properties: { path: { type: "string" }, old_string: { type: "string" }, new_string: { type: "string" } } } },
                        { name: "bash", description: "Execute shell commands", inputSchema: { type: "object", properties: { command: { type: "string" } } } }
                    ]
                }
            },
            'tools/call': {
                jsonrpc: "2.0",
                id: 3,
                result: {
                    content: [
                        { type: "text", text: "# Raven\n\nAI Gateway with MCP Protocol\n\nConnect Claude Desktop, Qoder, opencode, Cursor to 66+ tools..." }
                    ]
                }
            },
            'ping': {
                jsonrpc: "2.0",
                id: 4,
                result: {}
            }
        };

        this.init();
    }

    init() {
        this.input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.executeCommand(this.input.value);
                this.input.value = '';
            }
        });

        this.exampleBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const cmd = btn.dataset.cmd;
                this.input.value = cmd;
                this.executeCommand(cmd);
            });
        });

        this.addLine('Raven MCP Server v0.4.8', 'system');
        this.addLine('Type "initialize" to start, or click examples below', 'system');
        this.addLine('', 'blank');
    }

    executeCommand(cmd) {
        try {
            const parsed = JSON.parse(cmd);
            this.addLine(`$ ${cmd}`, 'input');

            setTimeout(() => {
                const method = parsed.method;
                let response;

                if (method === 'initialize') response = this.responses['initialize'];
                else if (method === 'tools/list') response = this.responses['tools/list'];
                else if (method === 'tools/call') response = this.responses['tools/call'];
                else if (method === 'ping') response = this.responses['ping'];
                else response = { jsonrpc: "2.0", id: parsed.id, error: { code: -32601, message: `Method not found: ${method}` } };

                this.addLine(JSON.stringify(response, null, 2), 'output');
                this.output.scrollTop = this.output.scrollHeight;
            }, 300);
        } catch (e) {
            this.addLine(`Error: Invalid JSON - ${e.message}`, 'error');
        }
    }

    addLine(text, type) {
        const line = document.createElement('div');
        line.className = `terminal-line terminal-${type}`;
        line.textContent = text;
        this.output.appendChild(line);
        this.output.scrollTop = this.output.scrollHeight;
    }
}
