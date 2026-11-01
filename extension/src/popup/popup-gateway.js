/* The gateway address the panel may actually reach.

   An MV3 extension cannot open a socket to a host its manifest never mentioned: Chrome closes
   it, and the panel only sees a disconnect. So the typed address is normalized here and turned
   into the exact origin patterns the panel asks permission for. */

const SOCKET_SCHEME = { "http:": "ws:", "https:": "wss:" };
const HTTP_SCHEME = { ws: "http", wss: "https" };

export function normalizeGatewayEndpoint(value) {
  let typed = String(value ?? "").trim().replace(/\/+$/, "");
  if (!typed) return "";
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(typed)) typed = `http://${typed}`;
  const socket = typed.match(/^(ws|wss):\/\//i);
  if (socket) typed = typed.replace(/^(ws|wss):\/\//i, `${HTTP_SCHEME[socket[1].toLowerCase()]}://`);
  let url;
  try {
    url = new URL(typed);
  } catch {
    return "";
  }
  if (!SOCKET_SCHEME[url.protocol] || !url.hostname || url.username || url.password) return "";
  return url.origin;
}

export function gatewayOriginPatterns(endpoint) {
  const normalized = normalizeGatewayEndpoint(endpoint);
  if (!normalized) return [];
  const url = new URL(normalized);
  return [`${normalized}/*`, `${SOCKET_SCHEME[url.protocol]}//${url.host}/*`];
}
