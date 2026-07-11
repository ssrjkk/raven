import * as vscode from 'vscode';
import { RavenApi } from './api';

export class RavenInlineValuesProvider implements vscode.InlineValuesProvider {
  onDidChangeInlineValues?: vscode.Event<void> | undefined;

  constructor(private api: RavenApi) {}

  async provideInlineValues(
    document: vscode.TextDocument,
    viewPort: vscode.Range,
    context: vscode.InlineValueContext,
    token: vscode.CancellationToken,
  ): Promise<vscode.InlineValue[]> {
    const values: vscode.InlineValue[] = [];
    const maxLines = Math.min(viewPort.end.line, document.lineCount);

    for (let line = viewPort.start.line; line < maxLines; line++) {
      if (token.isCancellationRequested) break;
      const text = document.lineAt(line).text.trim();

      if (text.startsWith('def ') || text.startsWith('async def ')) {
        const range = new vscode.Range(line, 0, line, 0);
        values.push(new vscode.InlineValueText(range, '🔍 Explain with Raven'));
      } else if (text.startsWith('class ')) {
        const range = new vscode.Range(line, 0, line, 0);
        values.push(new vscode.InlineValueText(range, '🔍 Review with Raven'));
      } else if (text.startsWith('fn ') || text.startsWith('pub fn ')) {
        const range = new vscode.Range(line, 0, line, 0);
        values.push(new vscode.InlineValueText(range, '🔍 Explain with Raven'));
      } else if (text.startsWith('function ') || text.startsWith('export function ') || text.startsWith('export async function ')) {
        const range = new vscode.Range(line, 0, line, 0);
        values.push(new vscode.InlineValueText(range, '🔍 Explain with Raven'));
      }
    }

    return values;
  }
}
