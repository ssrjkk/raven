import * as vscode from 'vscode';
import { RavenApi, type RavenDiagnostic } from './api';

const diagnosticCollection = vscode.languages.createDiagnosticCollection('raven');

export function getDiagnosticCollection() {
  return diagnosticCollection;
}

export async function runReview(api: RavenApi, document: vscode.TextDocument) {
  const code = document.getText();
  const filename = document.fileName;

  const result = await api.review(code, filename);
  const diagnostics: vscode.Diagnostic[] = [];

  for (const d of result.diagnostics) {
    const range = new vscode.Range(
      Math.max(0, d.line),
      Math.max(0, d.column),
      Math.min(d.endLine, document.lineCount - 1),
      d.endColumn,
    );
    const severity = d.severity === 'error'
      ? vscode.DiagnosticSeverity.Error
      : d.severity === 'warning'
        ? vscode.DiagnosticSeverity.Warning
        : vscode.DiagnosticSeverity.Information;
    diagnostics.push(new vscode.Diagnostic(range, `[Raven] ${d.message}`, severity));
  }

  if (diagnostics.length > 0) {
    diagnosticCollection.set(document.uri, diagnostics);
  }
}

export function clearDiagnostics(uri?: vscode.Uri) {
  if (uri) {
    diagnosticCollection.delete(uri);
  } else {
    diagnosticCollection.clear();
  }
}
