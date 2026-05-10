import * as vscode from 'vscode';

export class RavenPanel {
  public static readonly viewType = 'raven.chat';
  private _panel: vscode.WebviewPanel | undefined;
  private _uri: vscode.Uri;
  private _apiEndpoint: string;

  constructor(extensionUri: vscode.Uri, apiEndpoint: string) {
    this._uri = extensionUri;
    this._apiEndpoint = apiEndpoint;
  }

  reveal() {
    if (this._panel) {
      this._panel.reveal(vscode.ViewColumn.Beside);
      return;
    }

    this._panel = vscode.window.createWebviewPanel(
      RavenPanel.viewType,
      'Raven AI',
      vscode.ViewColumn.Beside,
      { enableScripts: true, retainContextWhenHidden: true }
    );

    this._panel.webview.html = this._getHtml();
    this._panel.onDidDispose(() => { this._panel = undefined; });
  }

  dispose() { this._panel?.dispose(); }

  private _getHtml(): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Raven AI</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, sans-serif; background: #1a1a2e; color: #e4e4e7; display: flex; flex-direction: column; height: 100vh; }
  #header { padding: 12px 16px; background: #16213e; border-bottom: 1px solid #2a2a4a; display: flex; align-items: center; gap: 8px; }
  #header span { font-size: 20px; }
  #header h1 { font-size: 14px; font-weight: 600; }
  #messages { flex: 1; overflow-y: auto; padding: 16px; }
  .msg { margin-bottom: 12px; line-height: 1.5; font-size: 13px; }
  .msg.user { text-align: right; }
  .msg.user .bubble { background: #0f3460; color: white; display: inline-block; padding: 8px 14px; border-radius: 12px 12px 4px 12px; max-width: 85%; }
  .msg.assistant .bubble { background: #16213e; border: 1px solid #2a2a4a; display: inline-block; padding: 8px 14px; border-radius: 12px 12px 12px 4px; max-width: 85%; }
  .msg.system .bubble { background: #2d1b4e; border: 1px solid #4a2d6e; display: inline-block; padding: 6px 12px; border-radius: 8px; font-size: 12px; color: #c4a0e0; }
  #input-area { padding: 12px 16px; background: #16213e; border-top: 1px solid #2a2a4a; display: flex; gap: 8px; }
  #input { flex: 1; background: #1e1e3a; border: 1px solid #2a2a4a; color: #e4e4e7; padding: 10px 14px; border-radius: 8px; font-size: 13px; outline: none; }
  #input:focus { border-color: #0f3460; }
  #send { background: #0f3460; color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 13px; }
  #send:hover { background: #1a4a7a; }
  pre { background: #0d0d1a; padding: 10px; border-radius: 6px; overflow-x: auto; margin: 6px 0; font-size: 12px; }
  code { font-family: 'Cascadia Code', 'Fira Code', monospace; }
</style>
</head>
<body>
<div id="header"><span>🐦</span><h1>Raven AI</h1></div>
<div id="messages">
  <div class="msg system"><div class="bubble">Connected to Raven AI. Ask me anything about your code.</div></div>
</div>
<div id="input-area">
  <input id="input" type="text" placeholder="Ask Raven..." autofocus>
  <button id="send">Send</button>
</div>
<script>
  const ws = new WebSocket('ws://${new URL(this._apiEndpoint).hostname}:${new URL(this._apiEndpoint).port || 18888}/ws');
  ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === 'message') {
      addMsg(data.role, data.content);
    }
  };
  ws.onclose = () => addMsg('system', 'Disconnected. Reconnecting...');
  ws.onerror = () => addMsg('system', 'Connection error. Is Raven running?');

  function addMsg(role, text) {
    const c = document.getElementById('messages');
    const d = document.createElement('div');
    d.className = 'msg ' + role;
    d.innerHTML = '<div class="bubble">' + text.replace(/</g, '&lt;').replace(/\n/g, '<br>') + '</div>';
    c.appendChild(d);
    c.scrollTop = c.scrollHeight;
  }

  document.getElementById('send').onclick = send;
  document.getElementById('input').onkeydown = (e) => { if (e.key === 'Enter') send(); };

  function send() {
    const input = document.getElementById('input');
    const text = input.value.trim();
    if (!text) return;
    addMsg('user', text);
    ws.send(JSON.stringify({ text, session_id: 'vscode:panel:default' }));
    input.value = '';
  }
</script>
</body>
</html>`;
  }
}
