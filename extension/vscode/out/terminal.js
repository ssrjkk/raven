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
exports.openRepl = openRepl;
exports.openTui = openTui;
exports.startGateway = startGateway;
exports.stopGateway = stopGateway;
const vscode = __importStar(require("vscode"));
const config_1 = require("./config");
const TERMINAL_NAME = 'Raven AI';
function getOrCreateTerminal() {
    const existing = vscode.window.terminals.find(t => t.name === TERMINAL_NAME);
    if (existing)
        return existing;
    return vscode.window.createTerminal(TERMINAL_NAME);
}
function openRepl() {
    const cfg = (0, config_1.getConfig)();
    const terminal = getOrCreateTerminal();
    terminal.show(true);
    const cmd = cfg.pythonPath === 'python'
        ? cfg.replCommand
        : `${cfg.pythonPath} -m ${cfg.replCommand.replace(/^python\s+-m\s+/, '')}`;
    terminal.sendText(cmd);
}
function openTui() {
    const cfg = (0, config_1.getConfig)();
    const terminal = getOrCreateTerminal();
    terminal.show(true);
    const cmd = cfg.pythonPath === 'python'
        ? cfg.tuiCommand
        : `${cfg.pythonPath} -m ${cfg.tuiCommand.replace(/^python\s+-m\s+/, '')}`;
    terminal.sendText(cmd);
}
async function startGateway() {
    const cfg = (0, config_1.getConfig)();
    const terminal = getOrCreateTerminal();
    terminal.show(true);
    terminal.sendText(`${cfg.pythonPath} -m raven start`);
}
async function stopGateway() {
    const cfg = (0, config_1.getConfig)();
    const terminal = getOrCreateTerminal();
    terminal.show(true);
    terminal.sendText(`${cfg.pythonPath} -m raven stop`);
}
