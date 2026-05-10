import * as vscode from 'vscode';
import { RavenPanel } from './panel';
import { reviewSelection, explainSelection, fixSelection, suggestImprovements, generateTests, writeCommitMessage } from './commands';

let panel: RavenPanel | undefined;

export function activate(context: vscode.ExtensionContext) {
  console.log('Raven AI extension activating...');

  const apiEndpoint = vscode.workspace.getConfiguration('raven').get<string>('endpoint') || 'http://localhost:18888';

  panel = new RavenPanel(context.extensionUri, apiEndpoint);

  context.subscriptions.push(
    vscode.commands.registerCommand('raven.chat', () => panel?.reveal()),
    vscode.commands.registerCommand('raven.review', () => reviewSelection(apiEndpoint)),
    vscode.commands.registerCommand('raven.explain', () => explainSelection(apiEndpoint)),
    vscode.commands.registerCommand('raven.fix', () => fixSelection(apiEndpoint)),
    vscode.commands.registerCommand('raven.suggest', () => suggestImprovements(apiEndpoint)),
    vscode.commands.registerCommand('raven.tests', () => generateTests(apiEndpoint)),
    vscode.commands.registerCommand('raven.commit', () => writeCommitMessage(apiEndpoint)),
  );

  // Auto-review on save (opt-in via setting)
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument(async (doc) => {
      const config = vscode.workspace.getConfiguration('raven');
      if (config.get<boolean>('autoReviewOnSave')) {
        reviewSelection(apiEndpoint, doc.uri);
      }
    })
  );

  console.log('Raven AI extension activated');
}

export function deactivate() {
  panel?.dispose();
}
