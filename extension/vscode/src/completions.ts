import * as vscode from 'vscode';

export class RavenCompletionProvider implements vscode.CompletionItemProvider {
  async provideCompletionItems(
    document: vscode.TextDocument,
    position: vscode.Position,
    token: vscode.CancellationToken,
    context: vscode.CompletionContext,
  ): Promise<vscode.CompletionItem[] | vscode.CompletionList> {
    if (context.triggerKind !== vscode.CompletionTriggerKind.TriggerCharacter) return [];

    const linePrefix = document.lineAt(position).text.slice(0, position.character);
    if (!linePrefix.endsWith('@')) return [];

    const items: vscode.CompletionItem[] = [];

    // Add file references from workspace
    const files = await vscode.workspace.findFiles(
      '**/*.{py,ts,tsx,js,jsx,go,rs,rb,java,kt,swift,c,cpp,h,hpp,cs,fs,scala,ex,exs}',
      '**/{node_modules,__pycache__,.git,dist,build,target,vendor,venv,.venv}/**',
    );

    const MAX_FILES = 50;
    const count = Math.min(files.length, MAX_FILES);

    for (let i = 0; i < count; i++) {
      if (token.isCancellationRequested) break;
      const file = files[i];
      const relativePath = vscode.workspace.asRelativePath(file.fsPath);
      const item = new vscode.CompletionItem(relativePath, vscode.CompletionItemKind.File);
      item.detail = 'Raven file reference';
      item.insertText = relativePath;
      item.range = new vscode.Range(position.translate(0, -1), position);
      items.push(item);
    }

    // Add line-number variants
    for (let i = 0; i < Math.min(count, 10); i++) {
      if (token.isCancellationRequested) break;
      const file = files[i];
      const relativePath = vscode.workspace.asRelativePath(file.fsPath);
      const item = new vscode.CompletionItem(`${relativePath}#L1-50`, vscode.CompletionItemKind.File);
      item.detail = 'Raven file reference with line range';
      item.insertText = `${relativePath}#L1-50`;
      item.range = new vscode.Range(position.translate(0, -1), position);
      items.push(item);
    }

    return items;
  }
}
