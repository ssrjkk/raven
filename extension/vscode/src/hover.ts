import * as vscode from 'vscode';
import { RavenApi } from './api';

export class RavenHoverProvider implements vscode.HoverProvider {
  private _debounce: Map<string, { timer: NodeJS.Timeout; promise: Promise<string> }> = new Map();

  constructor(private api: RavenApi) {}

  async provideHover(
    document: vscode.TextDocument,
    position: vscode.Position,
    token: vscode.CancellationToken,
  ): Promise<vscode.Hover | null> {
    const range = document.getWordRangeAtPosition(position);
    if (!range) return null;
    const word = document.getText(range);
    if (!word || word.length < 2 || word.length > 80) return null;

    const line = document.lineAt(position.line).text;
    const code = line.slice(Math.max(0, range.start.character - 20), range.end.character + 20);
    const key = `${document.uri.toString()}:${word}`;

    if (token.isCancellationRequested) return null;

    try {
      const result = await this.api.call('explain', `${word} — context: ${code}`, document.fileName);
      if (!result || result.startsWith('Error') || result.startsWith('Connection error')) return null;
      const markdown = new vscode.MarkdownString();
      markdown.appendMarkdown(`**Raven:** ${result.slice(0, 500)}`);
      markdown.isTrusted = true;
      return new vscode.Hover(markdown, range);
    } catch {
      return null;
    }
  }
}
