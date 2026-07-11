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
exports.reviewSelection = reviewSelection;
exports.explainSelection = explainSelection;
exports.fixSelection = fixSelection;
exports.suggestImprovements = suggestImprovements;
exports.generateTests = generateTests;
exports.writeCommitMessage = writeCommitMessage;
const vscode = __importStar(require("vscode"));
const diagnostics_1 = require("./diagnostics");
function getSelection() {
    const editor = vscode.window.activeTextEditor;
    if (!editor)
        return '';
    return editor.document.getText(editor.selection);
}
function getEditorOrWarn() {
    const editor = vscode.window.activeTextEditor;
    if (!editor)
        vscode.window.showWarningMessage('No active editor');
    return editor;
}
async function apiCall(api, action, code, context = '') {
    return vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `Raven is ${action}...` }, async () => api.call(action, code, context));
}
async function showResultInDoc(content, language = 'markdown', preview = true) {
    const doc = await vscode.workspace.openTextDocument({ content, language });
    await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside, preview });
}
async function reviewSelection(api) {
    const editor = getEditorOrWarn();
    if (!editor)
        return;
    const code = getSelection() || editor.document.getText();
    const filename = editor.document.fileName;
    const result = await apiCall(api, 'reviewing', code, filename);
    // Try to parse structured diagnostics
    const lines = result.split('\n');
    const diagnostics = [];
    let summaryLines = [];
    for (const line of lines) {
        const m = line.match(/^Line\s+(\d+)(?::(\d+))?\s*-\s*(\d+)(?::(\d+))?\s+\[(\w+)\]\s+(.+)$/);
        if (m) {
            const d = {
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
        }
        else {
            summaryLines.push(line);
        }
    }
    if (diagnostics.length > 0) {
        (0, diagnostics_1.getDiagnosticCollection)().set(editor.document.uri, diagnostics);
        vscode.window.showInformationMessage(`Raven found ${diagnostics.length} issue(s) — see Problems tab`);
    }
    showResultInDoc(result, 'markdown');
}
async function explainSelection(api) {
    const editor = getEditorOrWarn();
    if (!editor)
        return;
    const code = getSelection() || editor.document.getText();
    const result = await apiCall(api, 'explaining', code, editor.document.fileName);
    showResultInDoc(result, 'markdown');
}
async function fixSelection(api) {
    const editor = getEditorOrWarn();
    if (!editor)
        return;
    const code = getSelection() || editor.document.getText();
    const result = await apiCall(api, 'fixing', code, editor.document.fileName);
    await editor.edit((editBuilder) => {
        const selection = editor.selection.isEmpty
            ? new vscode.Range(0, 0, editor.document.lineCount, 0)
            : editor.selection;
        editBuilder.replace(selection, result);
    });
    (0, diagnostics_1.getDiagnosticCollection)().delete(editor.document.uri);
    vscode.window.showInformationMessage('Raven applied fixes');
}
async function suggestImprovements(api) {
    const editor = getEditorOrWarn();
    if (!editor)
        return;
    const code = getSelection() || editor.document.getText();
    const result = await apiCall(api, 'suggesting improvements for', code, editor.document.fileName);
    showResultInDoc(result, 'markdown');
}
async function generateTests(api) {
    const editor = getEditorOrWarn();
    if (!editor)
        return;
    const code = getSelection() || editor.document.getText();
    const result = await apiCall(api, 'writing tests for', code, editor.document.fileName);
    showResultInDoc(result, editor.document.languageId, false);
}
async function writeCommitMessage(api) {
    const gitRoot = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!gitRoot)
        return vscode.window.showWarningMessage('No workspace folder');
    // Collect git diff
    let diff = '';
    try {
        const { execSync } = require('child_process');
        diff = execSync('git diff --cached', { cwd: gitRoot.fsPath, encoding: 'utf-8' }).slice(0, 3000);
    }
    catch {
        diff = '(no staged changes)';
    }
    const result = await apiCall(api, 'writing commit message for', diff, gitRoot.fsPath);
    showResultInDoc(result, 'text');
}
