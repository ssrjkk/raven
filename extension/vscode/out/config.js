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
exports.getConfig = getConfig;
exports.getWsUrl = getWsUrl;
const vscode = __importStar(require("vscode"));
function getConfig() {
    const cfg = vscode.workspace.getConfiguration('raven');
    return {
        endpoint: cfg.get('endpoint', 'http://localhost:18888'),
        stateless: cfg.get('stateless', false),
        autoReviewOnSave: cfg.get('autoReviewOnSave', false),
        enableDiagnostics: cfg.get('enableDiagnostics', true),
        enableHover: cfg.get('enableHover', true),
        enableCodeActions: cfg.get('enableCodeActions', true),
        enableInlineValues: cfg.get('enableInlineValues', false),
        replCommand: cfg.get('replCommand', 'raven repl'),
        tuiCommand: cfg.get('tuiCommand', 'raven tui'),
        pythonPath: cfg.get('pythonPath', 'python'),
    };
}
function getWsUrl(endpoint) {
    try {
        const url = new URL(endpoint);
        return `ws://${url.hostname}:${url.port || 18888}/ws`;
    }
    catch {
        return 'ws://localhost:18888/ws';
    }
}
