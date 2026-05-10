import * as vscode from 'vscode';

async function apiCall(endpoint: string, action: string, code: string, context?: string): Promise<string> {
  try {
    const resp = await fetch(`${endpoint}/api/raven`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, code, context }),
    });
    if (!resp.ok) return `Error: ${resp.statusText}`;
    const data = await resp.json();
    return data.response || '(no response)';
  } catch (e: any) {
    return `Connection error: ${e.message}. Is Raven running on ${endpoint}?`;
  }
}

function getSelection(): string {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return '';
  return editor.document.getText(editor.selection);
}

export async function reviewSelection(endpoint: string, uri?: vscode.Uri) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return vscode.window.showWarningMessage('No active editor');

  const code = uri
    ? (await vscode.workspace.openTextDocument(uri)).getText()
    : getSelection() || editor.document.getText();

  const filename = editor.document.fileName;
  vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Raven is reviewing code...' }, async () => {
    const result = await apiCall(endpoint, 'review', code, filename);
    const doc = await vscode.workspace.openTextDocument({ content: result, language: 'markdown' });
    await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside, preview: true });
  });
}

export async function explainSelection(endpoint: string) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return vscode.window.showWarningMessage('No active editor');

  const code = getSelection() || editor.document.getText();
  vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Raven is explaining...' }, async () => {
    const result = await apiCall(endpoint, 'explain', code);
    const doc = await vscode.workspace.openTextDocument({ content: result, language: 'markdown' });
    await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside, preview: true });
  });
}

export async function fixSelection(endpoint: string) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return vscode.window.showWarningMessage('No active editor');

  const code = getSelection() || editor.document.getText();
  vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Raven is fixing issues...' }, async () => {
    const result = await apiCall(endpoint, 'fix', code);

    editor.edit((editBuilder) => {
      const selection = editor.selection.isEmpty
        ? new vscode.Range(0, 0, editor.document.lineCount, 0)
        : editor.selection;
      editBuilder.replace(selection, result);
    });
    vscode.window.showInformationMessage('✅ Raven applied fixes');
  });
}

export async function suggestImprovements(endpoint: string) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return vscode.window.showWarningMessage('No active editor');

  const code = getSelection() || editor.document.getText();
  vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Raven is suggesting improvements...' }, async () => {
    const result = await apiCall(endpoint, 'suggest', code);
    const doc = await vscode.workspace.openTextDocument({ content: result, language: 'markdown' });
    await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside, preview: true });
  });
}

export async function generateTests(endpoint: string) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return vscode.window.showWarningMessage('No active editor');

  const code = getSelection() || editor.document.getText();
  vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Raven is writing tests...' }, async () => {
    const result = await apiCall(endpoint, 'tests', code);
    const doc = await vscode.workspace.openTextDocument({ content: result, language: editor.document.languageId });
    await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside, preview: false });
  });
}

export async function writeCommitMessage(endpoint: string) {
  const gitRoot = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!gitRoot) return vscode.window.showWarningMessage('No workspace folder');

  vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Raven is writing commit message...' }, async () => {
    const result = await apiCall(endpoint, 'commit', '', gitRoot.fsPath);
    const doc = await vscode.workspace.openTextDocument({ content: result, language: 'text' });
    await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside, preview: true });
  });
}
