import * as vscode from 'vscode';
import { RavenApi } from './api';

export class RavenCodeActionProvider implements vscode.CodeActionProvider {
  public static readonly providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];

  constructor(private api: RavenApi) {}

  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext,
    token: vscode.CancellationToken,
  ): vscode.ProviderResult<(vscode.CodeAction | vscode.Command)[]> {
    const actions: vscode.CodeAction[] = [];

    if (context.diagnostics.length > 0) {
      const fix = new vscode.CodeAction('Fix with Raven', vscode.CodeActionKind.QuickFix);
      fix.command = { command: 'raven.fix', title: 'Fix with Raven', arguments: [] };
      fix.diagnostics = [...context.diagnostics];
      actions.push(fix);

      const explain = new vscode.CodeAction('Explain with Raven', vscode.CodeActionKind.QuickFix);
      explain.command = { command: 'raven.explain', title: 'Explain with Raven', arguments: [] };
      explain.diagnostics = [...context.diagnostics];
      actions.push(explain);
    }

    const selected = document.getText(range);
    if (selected.trim()) {
      const explain = new vscode.CodeAction('Explain Selection with Raven', vscode.CodeActionKind.RefactorExtract);
      explain.command = { command: 'raven.explain', title: 'Explain Selection with Raven', arguments: [] };
      actions.push(explain);

      const review = new vscode.CodeAction('Review Selection with Raven', vscode.CodeActionKind.RefactorRewrite);
      review.command = { command: 'raven.review', title: 'Review Selection with Raven', arguments: [] };
      actions.push(review);

      const tests = new vscode.CodeAction('Generate Tests with Raven', vscode.CodeActionKind.RefactorRewrite);
      tests.command = { command: 'raven.tests', title: 'Generate Tests with Raven', arguments: [] };
      actions.push(tests);
    }

    return actions;
  }
}
