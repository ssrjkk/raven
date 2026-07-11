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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const api_1 = require("./api");
const config_1 = require("./config");
const panel_1 = require("./panel");
const codeAction_1 = require("./codeAction");
const hover_1 = require("./hover");
const inlineValues_1 = require("./inlineValues");
const completions_1 = require("./completions");
const diagnostics_1 = require("./diagnostics");
const terminal_1 = require("./terminal");
const commands_1 = require("./commands");
let panel;
let statusBarItem;
let healthTimer;
function activate(context) {
    const cfg = (0, config_1.getConfig)();
    const api = new api_1.RavenApi(cfg.endpoint);
    panel = new panel_1.RavenPanel(context.extensionUri);
    // ── Status bar ──────────────────────────────────────────
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.text = '$(hubot) Raven';
    statusBarItem.tooltip = 'Raven AI — Click to open chat';
    statusBarItem.command = 'raven.chat';
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);
    updateHealthStatus(api);
    // ── Commands ────────────────────────────────────────────
    context.subscriptions.push(vscode.commands.registerCommand('raven.chat', () => panel?.reveal()), vscode.commands.registerCommand('raven.review', () => (0, commands_1.reviewSelection)(api)), vscode.commands.registerCommand('raven.explain', () => (0, commands_1.explainSelection)(api)), vscode.commands.registerCommand('raven.fix', () => (0, commands_1.fixSelection)(api)), vscode.commands.registerCommand('raven.suggest', () => (0, commands_1.suggestImprovements)(api)), vscode.commands.registerCommand('raven.tests', () => (0, commands_1.generateTests)(api)), vscode.commands.registerCommand('raven.commit', () => (0, commands_1.writeCommitMessage)(api)), vscode.commands.registerCommand('raven.terminal', () => (0, terminal_1.openRepl)()), vscode.commands.registerCommand('raven.terminalTui', () => (0, terminal_1.openTui)()), vscode.commands.registerCommand('raven.start', () => (0, terminal_1.startGateway)()), vscode.commands.registerCommand('raven.stop', () => (0, terminal_1.stopGateway)()), vscode.commands.registerCommand('raven.status', () => showStatus(api)));
    // ── Providers ───────────────────────────────────────────
    if (cfg.enableCodeActions) {
        context.subscriptions.push(vscode.languages.registerCodeActionsProvider({ scheme: 'file' }, new codeAction_1.RavenCodeActionProvider(api), { providedCodeActionKinds: codeAction_1.RavenCodeActionProvider.providedCodeActionKinds }));
    }
    if (cfg.enableHover) {
        context.subscriptions.push(vscode.languages.registerHoverProvider({ scheme: 'file' }, new hover_1.RavenHoverProvider(api)));
    }
    if (cfg.enableInlineValues) {
        context.subscriptions.push(vscode.languages.registerInlineValuesProvider({ scheme: 'file' }, new inlineValues_1.RavenInlineValuesProvider(api)));
    }
    context.subscriptions.push(vscode.languages.registerCompletionItemProvider({ scheme: 'file' }, new completions_1.RavenCompletionProvider(), '@'));
    // ── Auto-review on save ────────────────────────────────
    context.subscriptions.push(vscode.workspace.onDidSaveTextDocument(async (doc) => {
        const config = (0, config_1.getConfig)();
        if (config.autoReviewOnSave && config.enableDiagnostics) {
            await (0, diagnostics_1.runReview)(api, doc);
        }
    }));
    // ── Health polling ─────────────────────────────────────
    healthTimer = setInterval(() => updateHealthStatus(api), 30000);
    console.log('Raven AI extension activated');
}
function deactivate() {
    panel?.dispose();
    if (healthTimer)
        clearInterval(healthTimer);
    (0, diagnostics_1.getDiagnosticCollection)().dispose();
    console.log('Raven AI extension deactivated');
}
async function updateHealthStatus(api) {
    if (!statusBarItem)
        return;
    try {
        const ok = await api.health();
        statusBarItem.text = ok ? '$(hubot) Raven' : '$(hubot) Raven (offline)';
        statusBarItem.tooltip = ok ? 'Raven AI — Connected' : 'Raven AI — Gateway not running. Click to start.';
        statusBarItem.backgroundColor = ok ? undefined : new vscode.ThemeColor('statusBarItem.warningBackground');
    }
    catch {
        statusBarItem.text = '$(hubot) Raven (offline)';
        statusBarItem.tooltip = 'Raven AI — Gateway not running. Click to start.';
        statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
    }
}
async function showStatus(api) {
    const ok = await api.health();
    const items = [
        { label: ok ? '$(check) Gateway: Running' : '$(error) Gateway: Stopped', description: `Endpoint: ${(0, config_1.getConfig)().endpoint}` },
        { label: '$(terminal) Open REPL', description: 'Open Raven REPL in terminal' },
        { label: '$(terminal) Open TUI', description: 'Open Raven TUI dashboard' },
        { label: '$(play) Start Gateway', description: 'Start Raven gateway' },
        { label: '$(stop) Stop Gateway', description: 'Stop Raven gateway' },
    ];
    const pick = await vscode.window.showQuickPick(items, { placeHolder: 'Raven AI Status' });
    if (!pick)
        return;
    if (pick.label.includes('REPL'))
        (0, terminal_1.openRepl)();
    else if (pick.label.includes('TUI'))
        (0, terminal_1.openTui)();
    else if (pick.label.includes('Start'))
        (0, terminal_1.startGateway)();
    else if (pick.label.includes('Stop'))
        (0, terminal_1.stopGateway)();
}
