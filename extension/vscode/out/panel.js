"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.RavenPanel = void 0;
const vscode = __importStar(require("vscode"));
const config_1 = require("./config");
class RavenPanel {
    _extensionUri;
    static viewType = 'raven.chat';
    _panel;
    _disposables = [];
    constructor(_extensionUri) {
        this._extensionUri = _extensionUri;
    }
    reveal() {
        if (this._panel) {
            this._panel.reveal(vscode.ViewColumn.Beside);
            return;
        }
        this._panel = vscode.window.createWebviewPanel(RavenPanel.viewType, 'Raven AI', vscode.ViewColumn.Beside, { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [] });
        this._panel.webview.html = this._getHtml();
        this._panel.onDidDispose(() => {
            this._panel = undefined;
            for (const d of this._disposables)
                d.dispose();
            this._disposables = [];
        });
    }
    dispose() {
        this._panel?.dispose();
        for (const d of this._disposables)
            d.dispose();
        this._disposables = [];
    }
    _getHtml() {
        const cfg = (0, config_1.getConfig)();
        const wsUrl = (0, config_1.getWsUrl)(cfg.endpoint);
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
  <span id="status" class="status disconnected">disconnected</span>
</div>
<div id="messages">
  <div class="msg system"><div class="bubble">Connected to Raven AI. Ask me anything about your code.</div></div>
</div>
<div id="input-area">
  <input id="input" type="text" placeholder="Ask Raven..." autofocus>
  <button id="send">Send</button>
</div>
<script>
  (function() {
    const wsUrl = "${wsUrl}";
    let ws = null;
    let reconnectTimer = null;
    let msgId = 0;

    function connect() {
      try {
        ws = new WebSocket(wsUrl);
      } catch(e) {
        setStatus('disconnected');
        scheduleReconnect();
        return;
      }
      ws.onopen = () => { setStatus('connected'); };
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'message') addMsg(data.role || 'assistant', data.content || '');
        } catch {
          addMsg('assistant', e.data);
        }
      };
      ws.onclose = () => { setStatus('disconnected'); scheduleReconnect(); };
      ws.onerror = () => { setStatus('disconnected'); scheduleReconnect(); };
    }

    function scheduleReconnect() {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => connect(), 3000);
    }

    function setStatus(s) {
      const el = document.getElementById('status');
      if (!el) return;
      el.textContent = s;
      el.className = 'status ' + s;
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
      if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
      addMsg('user', text);
      ws.send(JSON.stringify({ text, session_id: 'vscode:panel:default' }));
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
exports.RavenPanel = RavenPanel;
