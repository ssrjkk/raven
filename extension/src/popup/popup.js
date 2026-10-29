"use strict";

/* Side-panel client for the gateway's /ws endpoint. Two things this replaces: Alpine + Tailwind
   loaded from CDNs (MV3 rejects remotely hosted code, and the manifest CSP blocked the inline script
   too, so the old popup never ran its own component), and an unauthenticated socket -- /ws closes 1008
   unless it receives a token, so the token now comes from storage and travels as ?token= the same way
   the browser UI sends it. */

import { safeExternalUrl } from './popup-security.js';

const DEFAULT_ENDPOINT = "http://localhost:18888";

const messages = document.getElementById("messages");
const draft = document.getElementById("draft");
const sendButton = document.getElementById("send");
const composer = document.getElementById("composer");
const statusDot = document.getElementById("status");
const settings = document.getElementById("settings");
const gear = document.getElementById("gear");
const endpointField = document.getElementById("endpoint");
const tokenField = document.getElementById("token");
const saveButton = document.getElementById("save");
const settingsNote = document.getElementById("settings-note");

let socket = null;
let sessionId = "";
let streamRow = null;
let retries = 0;
let config = { endpoint: DEFAULT_ENDPOINT, token: "" };

function setStatus(text, cls) {
  statusDot.textContent = cls === "live" ? "●" : "○";
  statusDot.className = "dot " + cls;
  statusDot.title = text;
}

function editableReady(isReady) {
  draft.disabled = !isReady;
  sendButton.disabled = !isReady;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function inline(source, into) {
  const pattern = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[[^\]\n]+\]\((?:https?:\/\/|\/)[^)\s]+\))/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(source)) !== null) {
    if (match.index > last) into.appendChild(document.createTextNode(source.slice(last, match.index)));
    const chunk = match[0];
    if (chunk.startsWith("*")) {
      const strong = chunk[1] === "*";
      into.appendChild(el(strong ? "strong" : "em", null, chunk.slice(strong ? 2 : 1, strong ? -2 : -1)));
    } else if (chunk.startsWith("`")) {
      into.appendChild(el("code", null, chunk.slice(1, -1)));
    } else {
      const parts = chunk.slice(1, -1).split("](");
      const href = safeExternalUrl(parts[1] ?? '');
      if (!href) {
        into.appendChild(document.createTextNode(chunk));
      } else {
        const link = el("a", null, parts[0]);
        link.href = href;
        link.rel = "noopener noreferrer";
        link.target = "_blank";
        into.appendChild(link);
      }
    }
    last = pattern.lastIndex;
  }
  if (last < source.length) into.appendChild(document.createTextNode(source.slice(last)));
}

/* Model output becomes text nodes; nothing here is assigned to innerHTML. */
function render(text, into) {
  const lines = String(text ?? "").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const body = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++]);
      i += 1;
      const code = el("code", null, body.join("\n"));
      const pre = el("pre");
      pre.appendChild(code);
      into.appendChild(pre);
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const node = el("h" + Math.min(6, heading[1].length + 3));
      inline(heading[2], node);
      into.appendChild(node);
      i += 1;
      continue;
    }
    if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const bullet = ordered ? /^\s*\d+\.\s+/ : /^\s*[-*+]\s+/;
      const list = el(ordered ? "ol" : "ul");
      while (i < lines.length && bullet.test(lines[i])) {
        const item = el("li");
        inline(lines[i++].replace(bullet, ""), item);
        list.appendChild(item);
      }
      into.appendChild(list);
      continue;
    }
    if (!line.trim()) { i += 1; continue; }
    const paragraph = el("p");
    const gathered = [line];
    i += 1;
    while (
      i < lines.length && lines[i].trim() && !lines[i].startsWith("```")
      && !/^(#{1,4})\s+/.test(lines[i]) && !/^\s*[-*+]\s+/.test(lines[i]) && !/^\s*\d+\.\s+/.test(lines[i])
    ) gathered.push(lines[i++]);
    inline(gathered.join("\n"), paragraph);
    into.appendChild(paragraph);
  }
}

function bubble(kind) {
  const wrap = el("div", kind === "user" ? "line-user" : "line-ai");
  const body = el("div", "bubble " + (kind === "user" ? "user" : "ai"));
  wrap.appendChild(body);
  messages.appendChild(wrap);
  messages.scrollTop = messages.scrollHeight;
  return body;
}

function note(text) {
  messages.appendChild(el("div", "bubble info", text));
  messages.scrollTop = messages.scrollHeight;
}

function wsUrl() {
  const base = config.endpoint.replace(/\/+$/, "").replace(/^http/, "ws");
  return base + "/ws?token=" + encodeURIComponent(config.token);
}

function connect() {
  if (!config.token) {
    setStatus("no token configured", "down");
    openSettings("Enter the gateway token to connect.");
    return;
  }
  setStatus("connecting", "");
  try {
    socket = new WebSocket(wsUrl());
  } catch (error) {
    setStatus("bad gateway url", "down");
    return;
  }
  socket.onopen = () => { retries = 0; setStatus("connected", "live"); editableReady(true); };
  socket.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
    if (data.type === "session") {
      sessionId = data.session_id || "";
    } else if (data.type === "stream") {
      if (!streamRow) streamRow = bubble("ai");
      streamRow.textContent = data.content || "";
      messages.scrollTop = messages.scrollHeight;
    } else if (data.type === "message") {
      const body = streamRow || bubble("ai");
      body.textContent = "";
      render(data.content, body);
      streamRow = null;
    } else if (data.type === "tool_call") {
      note(((data.data && data.data.name) || "tool") + " → running");
    } else if (data.type === "tool_result") {
      note(((data.data && data.data.name) || "tool") + " → done");
    } else if (data.type === "error") {
      note("error: " + (data.content || "unknown"));
    } else if (data.type === "done") {
      streamRow = null;
    }
  };
  socket.onclose = () => {
    editableReady(false);
    retries += 1;
    setStatus("disconnected", "down");
    setTimeout(connect, Math.min(10000, 1000 * 2 ** Math.min(retries, 4)));
  };
}

function openSettings(hint) {
  settings.hidden = false;
  endpointField.value = config.endpoint;
  tokenField.value = config.token;
  settingsNote.textContent = hint || "";
}

gear.addEventListener("click", () => { settings.hidden = !settings.hidden; openSettings(); });

saveButton.addEventListener("click", () => {
  config = { endpoint: endpointField.value.trim() || DEFAULT_ENDPOINT, token: tokenField.value.trim() };
  chrome.storage.local.set({ raven: config }, () => {
    settings.hidden = true;
    if (socket) socket.close();
    connect();
  });
});

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = draft.value;
  if (!text.trim() || !socket || socket.readyState !== WebSocket.OPEN) return;
  render(text, bubble("user"));
  socket.send(JSON.stringify({ text, session_id: sessionId }));
  draft.value = "";
});

chrome.storage.local.get("raven", (stored) => {
  config = { endpoint: (stored.raven && stored.raven.endpoint) || DEFAULT_ENDPOINT, token: (stored.raven && stored.raven.token) || "" };
  connect();
});
