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
exports.RavenHoverProvider = void 0;
const vscode = __importStar(require("vscode"));
class RavenHoverProvider {
    api;
    _debounce = new Map();
    constructor(api) {
        this.api = api;
    }
    async provideHover(document, position, token) {
        const range = document.getWordRangeAtPosition(position);
        if (!range)
            return null;
        const word = document.getText(range);
        if (!word || word.length < 2 || word.length > 80)
            return null;
        const line = document.lineAt(position.line).text;
        const code = line.slice(Math.max(0, range.start.character - 20), range.end.character + 20);
        const key = `${document.uri.toString()}:${word}`;
        if (token.isCancellationRequested)
            return null;
        try {
            const result = await this.api.call('explain', `${word} — context: ${code}`, document.fileName);
            if (!result || result.startsWith('Error') || result.startsWith('Connection error'))
                return null;
            const markdown = new vscode.MarkdownString();
            markdown.appendMarkdown(`**Raven:** ${result.slice(0, 500)}`);
            markdown.isTrusted = true;
            return new vscode.Hover(markdown, range);
        }
        catch {
            return null;
        }
    }
}
exports.RavenHoverProvider = RavenHoverProvider;
