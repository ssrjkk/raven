import * as vscode from 'vscode';
import { getConfig, getWsUrl, TOKEN_SECRET } from './config';

export class RavenPanel {
  public static readonly viewType = 'raven.chat';
  private _panel: vscode.WebviewPanel | undefined;
  private _disposables: vscode.Disposable[] = [];

  constructor(private _context: vscode.ExtensionContext) {}

  reveal() {
    if (this._panel) {
      this._panel.reveal(vscode.ViewColumn.Beside);
      return;
    }
    this._panel = vscode.window.createWebviewPanel(
      RavenPanel.viewType,
      'Raven AI',
      vscode.ViewColumn.Beside,
      { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [] },
    );
    this._panel.webview.html = this._getHtml();
    this._disposables.push(
      this._panel.webview.onDidReceiveMessage(async (msg: { type?: string }) => {
        // The socket belongs to the webview, but the credential does not: it is read from
        // SecretStorage here and handed over after the page asks, so no token is written into the
        // HTML the webview renders.
        if (msg?.type === 'token' && this._panel) {
          const token = await this._context.secrets.get(TOKEN_SECRET);
          void this._panel.webview.postMessage({ type: 'gatewayToken', token: token ?? '' });
        }
      }),
    );
    this._panel.onDidDispose(() => {
      this._panel = undefined;
      for (const d of this._disposables) d.dispose();
      this._disposables = [];
    });
  }

  async pushToken() {
    if (!this._panel) return;
    const token = await this._context.secrets.get(TOKEN_SECRET);
    void this._panel.webview.postMessage({ type: 'gatewayToken', token: token ?? '' });
  }

  dispose() {
    this._panel?.dispose();
    for (const d of this._disposables) d.dispose();
    this._disposables = [];
  }

  private _getHtml(): string {
    const cfg = getConfig();
    const wsUrl = getWsUrl(cfg.endpoint);

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
  #header .status { margin-left: auto; font-size: 11px; padding: 2px 8px; border-radius: 10px; }
  .status.connected { background: #1a4a2e; color: #4ade80; }
  .status.disconnected { background: #4a1a1a; color: #f87171; }
  .status.waiting { background: #4a3a1a; color: #fbbf24; }
  #messages { flex: 1; overflow-y: auto; padding: 16px; }
  .msg { margin-bottom: 12px; line-height: 1.5; font-size: 13px; }
  .msg.user { text-align: right; }
  .msg.user .bubble { background: #0f3460; color: white; display: inline-block; padding: 8px 14px; border-radius: 12px 12px 4px 12px; max-width: 85%; }
  .msg.assistant .bubble { background: #16213e; border: 1px solid #2a2a4a; display: inline-block; padding: 8px 14px; border-radius: 12px 12px 12px 4px; max-width: 85%; white-space: pre-wrap; }
  .msg.system .bubble { background: #2d1b4e; border: 1px solid #4a2d6e; display: inline-block; padding: 6px 12px; border-radius: 8px; font-size: 12px; color: #c4a0e0; }
  .msg.loading .bubble { background: #1a1a3e; border: 1px dashed #2a2a4a; display: inline-block; padding: 8px 14px; border-radius: 8px; font-size: 12px; color: #888; }
  #input-area { padding: 12px 16px; background: #16213e; border-top: 1px solid #2a2a4a; display: flex; gap: 8px; }
  #input { flex: 1; background: #1e1e3a; border: 1px solid #2a2a4a; color: #e4e4e7; padding: 10px 14px; border-radius: 8px; font-size: 13px; outline: none; }
  #input:focus { border-color: #0f3460; }
  #send { background: #0f3460; color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 13px; }
  #send:hover { background: #1a4a7a; }
  #send:disabled { background: #1a1a3e; color: #555; cursor: default; }
  pre { background: #0d0d1a; padding: 10px; border-radius: 6px; overflow-x: auto; margin: 6px 0; font-size: 12px; }
  code { font-family: 'Cascadia Code', 'Fira Code', monospace; }
  .actions { margin-top: 8px; display: flex; gap: 6px; }
  .actions button { background: #0f3460; color: #ccc; border: 1px solid #2a2a4a; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 11px; }
  .actions button:hover { background: #1a4a7a; color: white; }
</style>
</head>
<body>
<div id="header">
  <span>🐦</span><h1>Raven AI</h1>
  <span id="status" class="status waiting">connecting</span>
</div>
<div id="messages"></div>
<div id="input-area">
  <input id="input" type="text" placeholder="Ask Raven..." autofocus>
  <button id="send">Send</button>
</div>
<script>
  (function() {
    const vscodeApi = acquireVsCodeApi();
    const wsUrl = ${JSON.stringify(wsUrl)};
    let ws = null;
    let reconnectTimer = null;
    let token = null;
    let sessionId = null;
    let needToken = false;
    let tokenNoted = false;

    function note(text) {
      addMsg('system', text);
    }

    function connect() {
      if (!wsUrl) {
        setStatus('bad endpoint');
        note('raven.endpoint is not an http(s) URL, so the chat panel cannot reach a gateway.');
        return;
      }
      setStatus('connecting');
      try {
        ws = new WebSocket(wsUrl);
      } catch(e) {
        setStatus('disconnected');
        scheduleReconnect();
        return;
      }
      // A socket to /ws is authenticated by its first frame; anything else closes 1008. The panel used
      // to send the user's text as that frame, so the gateway read it as a missing credential.
      ws.onopen = () => { vscodeApi.postMessage({ type: 'token' }); };
      ws.onmessage = (e) => {
        let data = null;
        try { data = JSON.parse(e.data); } catch { addMsg('assistant', e.data); return; }
        if (!data || typeof data.type !== 'string') return;
        if (data.type === 'session') {
          sessionId = data.session_id || null;
          setStatus('connected');
          return;
        }
        if (data.type === 'message') { addMsg(data.role || 'assistant', data.content || ''); return; }
        if (data.type === 'error') { note(data.content || 'The gateway rejected this message.'); }
      };
      ws.onclose = () => {
        sessionId = null;
        // Reconnecting without a credential would loop the panel against a socket that answers 1008
        // every three seconds, and repeat the one message that tells the user why.
        if (needToken) { setStatus('no token'); return; }
        setStatus('disconnected');
        scheduleReconnect();
      };
      ws.onerror = () => { setStatus('disconnected'); };
    }

    window.addEventListener('message', (event) => {
      const msg = event.data;
      if (!msg || msg.type !== 'gatewayToken') return;
      token = typeof msg.token === 'string' ? msg.token : '';
      if (!token) {
        needToken = true;
        setStatus('no token');
        if (!tokenNoted) {
          tokenNoted = true;
          note('No gateway token is stored. Run "Raven: Set Gateway Token" with the key the gateway listens with.');
        }
        if (ws && ws.readyState === WebSocket.OPEN) ws.close();
        return;
      }
      needToken = false;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'auth', token: token }));
      } else {
        connect();
      }
    });

    function scheduleReconnect() {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => connect(), 3000);
    }

    function setStatus(s) {
      const el = document.getElementById('status');
      if (!el) return;
      el.textContent = s;
      const cls = s === 'connected' ? 'connected' : s === 'disconnected' ? 'disconnected' : 'waiting';
      el.className = 'status ' + cls;
    }

    function addMsg(role, text) {
      const c = document.getElementById('messages');
      const d = document.createElement('div');
      d.className = 'msg ' + role;
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      const parts = text.split(/(\`\`\`\w*\\n?[\\s\\S]*?\`\`\`)/g);
      for (const part of parts) {
        const codeMatch = part.match(/^\`\`\`(\w*)\\n?([\\s\\S]*?)\`\`\`$/);
        if (codeMatch) {
          const pre = document.createElement('pre');
          const code = document.createElement('code');
          code.textContent = codeMatch[2];
          pre.appendChild(code);
          bubble.appendChild(pre);
        } else if (part) {
          const lines = part.split('\n');
          for (let i = 0; i < lines.length; i++) {
            if (i > 0) bubble.appendChild(document.createElement('br'));
            bubble.appendChild(document.createTextNode(lines[i]));
          }
        }
      }
      d.appendChild(bubble);
      c.appendChild(d);
      c.scrollTop = c.scrollHeight;
    }

    function send() {
      const input = document.getElementById('input');
      const sendBtn = document.getElementById('send');
      const text = input.value.trim();
      if (!text || !ws || ws.readyState !== WebSocket.OPEN || !sessionId) return;
      addMsg('user', text);
      // The gateway assigns the session on connect and ignores an id the client invents outside its own
      // namespace; the panel used to send one of its own, which was silently discarded.
      ws.send(JSON.stringify({ text, session_id: sessionId }));
      input.value = '';
      sendBtn.disabled = true;
      setTimeout(() => { sendBtn.disabled = false; }, 500);
    }

    document.getElementById('send').onclick = send;
    document.getElementById('input').onkeydown = (e) => { if (e.key === 'Enter') send(); };

    connect();
  })();
</script>
</body>
</html>`;
  }
}
