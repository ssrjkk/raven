import * as vscode from 'vscode';
import { RavenApi } from './api';
import { getConfig, TOKEN_SECRET } from './config';
import { RavenPanel } from './panel';
import { RavenCodeActionProvider } from './codeAction';
import { RavenHoverProvider } from './hover';
import { RavenInlineValuesProvider } from './inlineValues';
import { RavenCompletionProvider } from './completions';
import { getDiagnosticCollection, runReview } from './diagnostics';
import { openRepl, openTui, startGateway, stopGateway } from './terminal';
import { reviewSelection, explainSelection, fixSelection, suggestImprovements, generateTests, writeCommitMessage } from './commands';

let panel: RavenPanel | undefined;
let statusBarItem: vscode.StatusBarItem | undefined;
let healthTimer: NodeJS.Timeout | undefined;

export function activate(context: vscode.ExtensionContext) {
  const cfg = getConfig();
  const api = new RavenApi(context.secrets);
  panel = new RavenPanel(context);

  // ── Status bar ──────────────────────────────────────────
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.text = '$(hubot) Raven';
  statusBarItem.tooltip = 'Raven AI — Click to open chat';
  statusBarItem.command = 'raven.chat';
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  updateHealthStatus(api);

  // ── Commands ────────────────────────────────────────────
  context.subscriptions.push(
    vscode.commands.registerCommand('raven.chat', () => panel?.reveal()),
    vscode.commands.registerCommand('raven.review', () => reviewSelection(api)),
    vscode.commands.registerCommand('raven.explain', () => explainSelection(api)),
    vscode.commands.registerCommand('raven.fix', () => fixSelection(api)),
    vscode.commands.registerCommand('raven.suggest', () => suggestImprovements(api)),
    vscode.commands.registerCommand('raven.tests', () => generateTests(api)),
    vscode.commands.registerCommand('raven.commit', () => writeCommitMessage(api)),
    vscode.commands.registerCommand('raven.terminal', () => openRepl()),
    vscode.commands.registerCommand('raven.terminalTui', () => openTui()),
    vscode.commands.registerCommand('raven.start', () => startGateway()),
    vscode.commands.registerCommand('raven.stop', () => stopGateway()),
    vscode.commands.registerCommand('raven.status', () => showStatus(api, context)),
    vscode.commands.registerCommand('raven.setGatewayToken', () => setGatewayToken(context)),
  );

  // ── Providers ───────────────────────────────────────────
  if (cfg.enableCodeActions) {
    context.subscriptions.push(
      vscode.languages.registerCodeActionsProvider(
        { scheme: 'file' },
        new RavenCodeActionProvider(api),
        { providedCodeActionKinds: RavenCodeActionProvider.providedCodeActionKinds },
      ),
    );
  }

  if (cfg.enableHover) {
    context.subscriptions.push(
      vscode.languages.registerHoverProvider(
        { scheme: 'file' },
        new RavenHoverProvider(api),
      ),
    );
  }

  if (cfg.enableInlineValues) {
    context.subscriptions.push(
      vscode.languages.registerInlineValuesProvider(
        { scheme: 'file' },
        new RavenInlineValuesProvider(api),
      ),
    );
  }

  context.subscriptions.push(
    vscode.languages.registerCompletionItemProvider(
      { scheme: 'file' },
      new RavenCompletionProvider(),
      '@',
    ),
  );

  // ── Auto-review on save ────────────────────────────────
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument(async (doc) => {
      const config = getConfig();
      if (config.autoReviewOnSave && config.enableDiagnostics) {
        await runReview(api, doc);
      }
    }),
  );

  // ── Health polling ─────────────────────────────────────
  healthTimer = setInterval(() => updateHealthStatus(api), 30000);

  console.log('Raven AI extension activated');
}

export function deactivate() {
  panel?.dispose();
  if (healthTimer) clearInterval(healthTimer);
  getDiagnosticCollection().dispose();
  console.log('Raven AI extension deactivated');
}

async function updateHealthStatus(api: RavenApi) {
  if (!statusBarItem) return;
  try {
    const ok = await api.health();
    statusBarItem.text = ok ? '$(hubot) Raven' : '$(hubot) Raven (offline)';
    statusBarItem.tooltip = ok ? 'Raven AI — Connected' : 'Raven AI — Gateway not running. Click to start.';
    statusBarItem.backgroundColor = ok ? undefined : new vscode.ThemeColor('statusBarItem.warningBackground');
  } catch {
    statusBarItem.text = '$(hubot) Raven (offline)';
    statusBarItem.tooltip = 'Raven AI — Gateway not running. Click to start.';
    statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
  }
}

async function setGatewayToken(context: vscode.ExtensionContext) {
  const token = await vscode.window.showInputBox({
    title: 'Raven: Set Gateway Token',
    prompt: 'The key the gateway authenticates with. Leave empty to forget the stored token.',
    password: true,
    ignoreFocusOut: true,
    placeHolder: 'WEB_SECRET_KEY, or a session token from /api/auth/login',
  });
  if (token === undefined) return;
  if (token === '') {
    await context.secrets.delete(TOKEN_SECRET);
    void vscode.window.showInformationMessage('Raven: gateway token cleared.');
  } else {
    await context.secrets.store(TOKEN_SECRET, token);
    void vscode.window.showInformationMessage('Raven: gateway token stored for this machine.');
  }
  await panel?.pushToken();
}

async function showStatus(api: RavenApi, context: vscode.ExtensionContext) {
  const ok = await api.health();
  const token = await context.secrets.get(TOKEN_SECRET);
  const items: vscode.QuickPickItem[] = [
    { label: ok ? '$(check) Gateway: Running' : '$(error) Gateway: Stopped', description: `Endpoint: ${getConfig().endpoint}` },
    {
      label: token ? '$(check) Gateway token: stored' : '$(error) Gateway token: not set',
      description: token
        ? 'Stored on this machine -- click to replace or clear'
        : 'Click to store one; a call without it answers 401',
    },
    { label: '$(terminal) Open REPL', description: 'Open Raven REPL in terminal' },
    { label: '$(terminal) Open TUI', description: 'Open Raven TUI dashboard' },
    { label: '$(play) Start Gateway', description: 'Start Raven gateway' },
    { label: '$(stop) Stop Gateway', description: 'Stop Raven gateway' },
  ];
  const pick = await vscode.window.showQuickPick(items, { placeHolder: 'Raven AI Status' });
  if (!pick) return;
  if (pick.label.includes('Gateway token')) await setGatewayToken(context);
  else if (pick.label.includes('REPL')) openRepl();
  else if (pick.label.includes('TUI')) openTui();
  else if (pick.label.includes('Start')) startGateway();
  else if (pick.label.includes('Stop')) stopGateway();
}
