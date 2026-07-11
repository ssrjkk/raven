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
exports.RavenCompletionProvider = void 0;
const vscode = __importStar(require("vscode"));
class RavenCompletionProvider {
    async provideCompletionItems(document, position, token, context) {
        if (context.triggerKind !== vscode.CompletionTriggerKind.TriggerCharacter)
            return [];
        const linePrefix = document.lineAt(position).text.slice(0, position.character);
        if (!linePrefix.endsWith('@'))
            return [];
        const items = [];
        // Add file references from workspace
        const files = await vscode.workspace.findFiles('**/*.{py,ts,tsx,js,jsx,go,rs,rb,java,kt,swift,c,cpp,h,hpp,cs,fs,scala,ex,exs}', '**/{node_modules,__pycache__,.git,dist,build,target,vendor,venv,.venv}/**');
        const MAX_FILES = 50;
        const count = Math.min(files.length, MAX_FILES);
        for (let i = 0; i < count; i++) {
            if (token.isCancellationRequested)
                break;
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
            if (token.isCancellationRequested)
                break;
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
exports.RavenCompletionProvider = RavenCompletionProvider;
