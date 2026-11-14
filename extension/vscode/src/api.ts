import * as vscode from 'vscode';
import { getConfig, TOKEN_SECRET } from './config';

export interface RavenResponse {
  response: string;
}

export interface RavenDiagnostic {
  line: number;
  column: number;
  endLine: number;
  endColumn: number;
  message: string;
  severity: 'error' | 'warning' | 'info';
  category: string;
}

export interface RavenReviewResult {
  diagnostics: RavenDiagnostic[];
  summary: string;
}

function describe(value: unknown): string {
  return value instanceof Error ? value.message : String(value);
}

export class RavenApi {
  constructor(private secrets: vscode.SecretStorage) {}

  // Read at call time: a setting VS Code applies without a window reload has to reach the socket and
  // the URL of the next request, not the ones captured when the extension activated.
  private get urlBase(): string {
    return getConfig().endpoint.replace(/\/+$/, '');
  }

  private async headers(): Promise<Record<string, string>> {
    const token = await this.secrets.get(TOKEN_SECRET);
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }

  async call(action: string, code: string, context = ''): Promise<string> {
    try {
      const resp = await fetch(`${this.urlBase}/api/raven`, {
        method: 'POST',
        headers: await this.headers(),
        body: JSON.stringify({ action, code: code.slice(0, 2000), context: context.slice(0, 500) }),
      });
      if (resp.status === 401 || resp.status === 403) {
        // Without this split a refused call renders the FastAPI body inside the editor, and the
        // operator reads it as a model failure rather than a missing credential.
        return (
          `Error ${resp.status}: the gateway at ${this.urlBase} refused this call. ` +
          'Run "Raven: Set Gateway Token" with a token that holds the admin:write right.'
        );
      }
      if (!resp.ok) {
        const text = await resp.text();
        return `Error ${resp.status}: ${text}`;
      }
      const data = (await resp.json()) as RavenResponse;
      return data.response || '(no response)';
    } catch (e: unknown) {
      return `Connection error: ${describe(e)}. Ensure Raven gateway is running on ${this.urlBase}. Try: raven start`;
    }
  }

  async review(code: string, filename: string): Promise<RavenReviewResult> {
    const text = await this.call('review', code, filename);
    const diagnostics: RavenDiagnostic[] = [];
    const lines = text.split('\n');
    for (const line of lines) {
      const m = line.match(/^Line\s+(\d+)(?::(\d+))?\s*-\s*(\d+)(?::(\d+))?\s*\[(\w+)\]\s*(.+)$/);
      if (m) {
        diagnostics.push({
          line: parseInt(m[1]) - 1,
          column: m[2] ? parseInt(m[2]) - 1 : 0,
          endLine: parseInt(m[3]) - 1,
          endColumn: m[4] ? parseInt(m[4]) - 1 : 100,
          message: m[6],
          severity: m[5] === 'error' ? 'error' : m[5] === 'warning' ? 'warning' : 'info',
          category: 'Raven Review',
        });
      }
    }
    return { diagnostics, summary: text };
  }

  /** Liveness of the gateway, answered only by the body it returns.
   *
   * `/api/health/live` is public and says `{"status":"ok"}`. `resp.ok` alone cannot carry the signal:
   * the gateway mounts the built SPA on a catch-all that answers any unrouted path -- `/health` among
   * them -- with index.html and a 200, so a probe that trusts the status line reports a healthy
   * gateway against a wrong server on the port and stays green until a call actually fails.
   */
  async health(): Promise<boolean> {
    try {
      const resp = await fetch(`${this.urlBase}/api/health/live`, {
        method: 'GET',
        signal: AbortSignal.timeout(3000),
      });
      if (!resp.ok) return false;
      const body = (await resp.json()) as { status?: unknown };
      return body.status === 'ok';
    } catch {
      return false;
    }
  }
}
