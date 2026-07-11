import * as vscode from 'vscode';

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

export function getWsUrl(endpoint: string): string {
  try {
    const url = new URL(endpoint);
    return `ws://${url.hostname}:${url.port || 18888}/ws`;
  } catch {
    return 'ws://localhost:18888/ws';
  }
}
