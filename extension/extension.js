const vscode = require('vscode');

function activate(context) {
    const askCmd = vscode.commands.registerCommand('ravencode.ask', async () => {
        const prompt = await vscode.window.showInputBox({ prompt: 'Ask RavenCode', placeHolder: 'e.g. explain this code' });
        if (!prompt) return;
        const editor = vscode.window.activeTextEditor;
        const selection = editor ? editor.document.getText(editor.selection) : '';
        const fullPrompt = selection ? `${prompt}\n\n\`\`\`\n${selection}\n\`\`\`` : prompt;
        const panel = vscode.window.createWebviewPanel('ravencode', 'RavenCode', vscode.ViewColumn.Beside, { enableScripts: true });
        panel.webview.html = `<!DOCTYPE html><html><head><style>body{font-family:sans-serif;padding:16px;background:#1e1e1e;color:#d4d4d4;}</style></head><body><h2>RavenCode</h2><p>${fullPrompt}</p><div id="result">Waiting...</div></body></html>`;
        try {
            const resp = await fetch('http://localhost:8000/v1/chat/completions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: 'ravencode', messages: [{ role: 'user', content: fullPrompt }], stream: false })
            });
            const data = await resp.json();
            panel.webview.html = `<!DOCTYPE html><html><head><style>body{font-family:sans-serif;padding:16px;background:#1e1e1e;color:#d4d4d4;white-space:pre-wrap;}</style></head><body><h2>RavenCode</h2><div>${data.choices?.[0]?.message?.content || '(no response)'}</div></body></html>`;
        } catch (e) {
            panel.webview.html = `<!DOCTYPE html><html><head><style>body{font-family:sans-serif;padding:16px;background:#1e1e1e;color:#f48771;}</style></head><body><h2>RavenCode</h2><p>Error: ${e.message}. Ensure the RavenCode API server is running on port 8000.</p></body></html>`;
        }
    });
    context.subscriptions.push(askCmd);

    const explainCmd = vscode.commands.registerCommand('ravencode.explain', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) return;
        const selection = editor.document.getText(editor.selection);
        if (!selection) { vscode.window.showInformationMessage('Select code first'); return; }
        vscode.commands.executeCommand('ravencode.ask');
    });
    context.subscriptions.push(explainCmd);

    const fixCmd = vscode.commands.registerCommand('ravencode.fix', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) return;
        const diagnostics = vscode.languages.getDiagnostics(editor.document.uri);
        if (diagnostics.length === 0) { vscode.window.showInformationMessage('No issues detected'); return; }
        const issues = diagnostics.map(d => `Line ${d.range.start.line + 1}: ${d.message}`).join('\n');
        vscode.commands.executeCommand('ravencode.ask');
    });
    context.subscriptions.push(fixCmd);
}

function deactivate() {}

module.exports = { activate, deactivate };
