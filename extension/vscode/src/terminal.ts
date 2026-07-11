import * as vscode from 'vscode';
import { getConfig } from './config';

const TERMINAL_NAME = 'Raven AI';

function getOrCreateTerminal(): vscode.Terminal {
  const existing = vscode.window.terminals.find(t => t.name === TERMINAL_NAME);
  if (existing) return existing;
  return vscode.window.createTerminal(TERMINAL_NAME);
}

export function openRepl() {
  const cfg = getConfig();
  const terminal = getOrCreateTerminal();
  terminal.show(true);
  const cmd = cfg.pythonPath === 'python'
    ? cfg.replCommand
    : `${cfg.pythonPath} -m ${cfg.replCommand.replace(/^python\s+-m\s+/, '')}`;
  terminal.sendText(cmd);
}

export function openTui() {
  const cfg = getConfig();
  const terminal = getOrCreateTerminal();
  terminal.show(true);
  const cmd = cfg.pythonPath === 'python'
    ? cfg.tuiCommand
    : `${cfg.pythonPath} -m ${cfg.tuiCommand.replace(/^python\s+-m\s+/, '')}`;
  terminal.sendText(cmd);
}

export async function startGateway() {
  const cfg = getConfig();
  const terminal = getOrCreateTerminal();
  terminal.show(true);
  terminal.sendText(`${cfg.pythonPath} -m raven start`);
}

export async function stopGateway() {
  const cfg = getConfig();
  const terminal = getOrCreateTerminal();
  terminal.show(true);
  terminal.sendText(`${cfg.pythonPath} -m raven stop`);
}
