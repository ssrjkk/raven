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
exports.RavenInlineValuesProvider = void 0;
const vscode = __importStar(require("vscode"));
class RavenInlineValuesProvider {
    api;
    onDidChangeInlineValues;
    constructor(api) {
        this.api = api;
    }
    async provideInlineValues(document, viewPort, context, token) {
        const values = [];
        const maxLines = Math.min(viewPort.end.line, document.lineCount);
        for (let line = viewPort.start.line; line < maxLines; line++) {
            if (token.isCancellationRequested)
                break;
            const text = document.lineAt(line).text.trim();
            if (text.startsWith('def ') || text.startsWith('async def ')) {
                const range = new vscode.Range(line, 0, line, 0);
                values.push(new vscode.InlineValueText(range, '🔍 Explain with Raven'));
            }
            else if (text.startsWith('class ')) {
                const range = new vscode.Range(line, 0, line, 0);
                values.push(new vscode.InlineValueText(range, '🔍 Review with Raven'));
            }
            else if (text.startsWith('fn ') || text.startsWith('pub fn ')) {
                const range = new vscode.Range(line, 0, line, 0);
                values.push(new vscode.InlineValueText(range, '🔍 Explain with Raven'));
            }
            else if (text.startsWith('function ') || text.startsWith('export function ') || text.startsWith('export async function ')) {
                const range = new vscode.Range(line, 0, line, 0);
                values.push(new vscode.InlineValueText(range, '🔍 Explain with Raven'));
            }
        }
        return values;
    }
}
exports.RavenInlineValuesProvider = RavenInlineValuesProvider;
