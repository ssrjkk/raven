import * as vscode from 'vscode';
import { RavenApi, RavenDiagnostic } from './api';
import { getDiagnosticCollection, runReview } from './diagnostics';

function getSelection(): string {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return '';
  return editor.document.getText(editor.selection);
}

function getEditorOrWarn(): vscode.TextEditor | undefined {
  const editor = vscode.window.activeTextEditor;
  if (!editor) vscode.window.showWarningMessage('No active editor');
  return editor;
}

async function apiCall(api: RavenApi, action: string, code: string, context = ''): Promise<string> {
  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: `Raven is ${action}...` },
    async () => api.call(action, code, context),
  );
}

async function showResultInDoc(content: string, language = 'markdown', preview = true) {
  const doc = await vscode.workspace.openTextDocument({ content, language });
  await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside, preview });
}

export async function reviewSelection(api: RavenApi) {
  const editor = getEditorOrWarn();
  if (!editor) return;
  const code = getSelection() || editor.document.getText();
  const filename = editor.document.fileName;

  const result = await apiCall(api, 'reviewing', code, filename);

  // Try to parse structured diagnostics
  const lines = result.split('\n');
  const diagnostics: vscode.Diagnostic[] = [];
  let summaryLines: string[] = [];

  for (const line of lines) {
    const m = line.match(/^Line\s+(\d+)(?::(\d+))?\s*-\s*(\d+)(?::(\d+))?\s+\[(\w+)\]\s+(.+)$/);
    if (m) {
      const d: RavenDiagnostic = {
        line: parseInt(m[1]) - 1,
        column: m[2] ? parseInt(m[2]) - 1 : 0,
        endLine: parseInt(m[3]) - 1,
        endColumn: m[4] ? parseInt(m[4]) - 1 : 100,
        message: m[6],
        severity: m[5] === 'error' ? 'error' : m[5] === 'warning' ? 'warning' : 'info',
        category: 'Raven Review',
      };
      const range = new vscode.Range(d.line, d.column, d.endLine, d.endColumn);
      const severity = d.severity === 'error'
        ? vscode.DiagnosticSeverity.Error
        : d.severity === 'warning'
          ? vscode.DiagnosticSeverity.Warning
          : vscode.DiagnosticSeverity.Information;
      diagnostics.push(new vscode.Diagnostic(range, `[Raven] ${d.message}`, severity));
    } else {
      summaryLines.push(line);
    }
  }

  if (diagnostics.length > 0) {
    getDiagnosticCollection().set(editor.document.uri, diagnostics);
    vscode.window.showInformationMessage(`Raven found ${diagnostics.length} issue(s) — see Problems tab`);
  }

  showResultInDoc(result, 'markdown');
}

export async function explainSelection(api: RavenApi) {
  const editor = getEditorOrWarn();
  if (!editor) return;
  const code = getSelection() || editor.document.getText();
  const result = await apiCall(api, 'explaining', code, editor.document.fileName);
  showResultInDoc(result, 'markdown');
}

export async function fixSelection(api: RavenApi) {
  const editor = getEditorOrWarn();
  if (!editor) return;
  const code = getSelection() || editor.document.getText();
  const result = await apiCall(api, 'fixing', code, editor.document.fileName);

  await editor.edit((editBuilder) => {
    const selection = editor.selection.isEmpty
      ? new vscode.Range(0, 0, editor.document.lineCount, 0)
      : editor.selection;
    editBuilder.replace(selection, result);
  });

  getDiagnosticCollection().delete(editor.document.uri);
  vscode.window.showInformationMessage('Raven applied fixes');
}

export async function suggestImprovements(api: RavenApi) {
  const editor = getEditorOrWarn();
  if (!editor) return;
  const code = getSelection() || editor.document.getText();
  const result = await apiCall(api, 'suggesting improvements for', code, editor.document.fileName);
  showResultInDoc(result, 'markdown');
}

export async function generateTests(api: RavenApi) {
  const editor = getEditorOrWarn();
  if (!editor) return;
  const code = getSelection() || editor.document.getText();
  const result = await apiCall(api, 'writing tests for', code, editor.document.fileName);
  showResultInDoc(result, editor.document.languageId, false);
}

export async function writeCommitMessage(api: RavenApi) {
  const gitRoot = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!gitRoot) return vscode.window.showWarningMessage('No workspace folder');

  // Collect git diff
  let diff = '';
  try {
    const { execSync } = require('child_process');
    diff = execSync('git diff --cached', { cwd: gitRoot.fsPath, encoding: 'utf-8' }).slice(0, 3000);
  } catch {
    diff = '(no staged changes)';
  }

  const result = await apiCall(api, 'writing commit message for', diff, gitRoot.fsPath);
  showResultInDoc(result, 'text');
}
