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
exports.RavenCodeActionProvider = void 0;
const vscode = __importStar(require("vscode"));
class RavenCodeActionProvider {
    api;
    static providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];
    constructor(api) {
        this.api = api;
    }
    provideCodeActions(document, range, context, token) {
        const actions = [];
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
exports.RavenCodeActionProvider = RavenCodeActionProvider;
