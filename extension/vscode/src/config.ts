import * as vscode from 'vscode';

// The gateway token is a credential, so it lives in VS Code's SecretStorage rather than in
// settings.json, which is plain text and gets synced, backed up and screenshotted. A setting with
// `"format": "password"` would only mask the input box, not the stored value.
export const TOKEN_SECRET = 'raven.gatewayToken';

export function getConfig() {
  const cfg = vscode.workspace.getConfiguration('raven');
  return {
    endpoint: cfg.get<string>('endpoint', 'http://localhost:18888'),
    stateless: cfg.get<boolean>('stateless', false),
    autoReviewOnSave: cfg.get<boolean>('autoReviewOnSave', false),
    enableDiagnostics: cfg.get<boolean>('enableDiagnostics', true),
    enableHover: cfg.get<boolean>('enableHover', true),
    enableCodeActions: cfg.get<boolean>('enableCodeActions', true),
    enableInlineValues: cfg.get<boolean>('enableInlineValues', false),
    replCommand: cfg.get<string>('replCommand', 'raven repl'),
    tuiCommand: cfg.get<string>('tuiCommand', 'raven tui'),
    pythonPath: cfg.get<string>('pythonPath', 'python'),
  };
}

/** The chat socket for a gateway endpoint, or null when the endpoint is not a URL the user can fix by
 * reading their own error message. An earlier version answered a bad endpoint with
 * `ws://localhost:18888`, which connected the panel to whatever happened to be on this machine.
 */
export function getWsUrl(endpoint: string): string | null {
  let url: URL;
  try {
    url = new URL(endpoint);
  } catch {
    return null;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  // The socket scheme has to follow the endpoint: a gateway behind TLS refuses a plain `ws:` upgrade,
  // and a port written into the endpoint is the port the socket belongs on -- no default invented here.
  const scheme = url.protocol === 'https:' ? 'wss' : 'ws';
  const port = url.port ? `:${url.port}` : '';
  return `${scheme}://${url.hostname}${port}/ws`;
}
