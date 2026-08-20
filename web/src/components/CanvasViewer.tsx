import { memo, type ReactNode,useCallback, useEffect, useRef, useState } from "react";

import { getToken } from "../api/client";



interface ComponentDef {
  id: string;
  type: string;
  props: Record<string, unknown>;
  children?: ComponentDef[];
}

interface CanvasState {
  session_id: string;
  root: ComponentDef | null;
  events: { component_id: string; action: string; data: unknown; timestamp: number }[];
}

const BLOCKED_SCHEME_PREFIXES = ["javascript:", "vbscript:", "file:"];
const ALLOWED_HTTP_PREFIXES = ["http://", "https://"];

function safeResourceUrl(raw: string, kind: "image" | "link"): string | null {
  const lower = raw.toLowerCase();
  if (BLOCKED_SCHEME_PREFIXES.some((scheme) => lower.startsWith(scheme))) {
    return null;
  }
  if (lower.startsWith("data:")) {
    if (kind === "image" && raw.startsWith("data:image/")) {
      return raw;
    }
    return null;
  }
  if (!ALLOWED_HTTP_PREFIXES.some((prefix) => raw.startsWith(prefix))) {
    return null;
  }
  return `/api/canvas/${kind}?url=${encodeURIComponent(raw)}`;
}

function renderComponent(node: ComponentDef, onAction: (id: string, action: string, data?: Record<string, unknown>) => void): ReactNode {
  const { id, type, props, children } = node;
  const childNodes = children?.map((c) => renderComponent(c, onAction)) ?? [];

  switch (type) {
    case "box":
      return (
        <div key={id} className={props.className as string || ""} style={props.style as Record<string, string> || {}}>
          {childNodes}
        </div>
      );

    case "text": {
      const as = (props.as as string) || "p";
      const Tag = as === "h1" ? "h1" : as === "h2" ? "h2" : as === "h3" ? "h3" : as === "h4" ? "h4" : as === "span" ? "span" : "p";
      return <Tag key={id} className={`text-primary ${Tag !== "p" ? "font-bold" : ""}`} style={{ color: props.color as string }}>{props.content as string}</Tag>;
    }

    case "button": {
      const variant = (props.variant as string) || "default";
      let variantStyle: Record<string, string> = {
        backgroundColor: "var(--dt-colors-accent-default)",
        color: "#fff",
      };
      if (variant === "danger") {
        variantStyle = { backgroundColor: "var(--dt-colors-status-error)", color: "#fff" };
      } else if (variant === "success") {
        variantStyle = { backgroundColor: "var(--dt-colors-status-success)", color: "#fff" };
      } else if (variant === "outline") {
        variantStyle = {
          backgroundColor: "transparent",
          color: "var(--dt-colors-text-primary)",
          border: "1px solid var(--dt-colors-border-default)",
        };
      }
      return (
        <button
          key={id}
          onClick={() => onAction(id, props.action as string, props.data as Record<string, unknown> || {})}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition hover:brightness-110 active:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed ${
            variant === "outline" ? "hover:bg-[var(--dt-colors-bg-hover)]" : ""
          } ${props.className as string || ""}`}
          disabled={props.disabled as boolean}
          style={{ ...variantStyle, ...(props.style as Record<string, string> || {}) }}
        >
          {props.label as string}
        </button>
      );
    }

    case "input":
      const label = props.label as string | undefined;
      return (
        <div key={id} className="flex flex-col gap-1">
          {label && <label className="text-xs text-tertiary">{label}</label>}
          <input
            name={props.name as string}
            placeholder={(props.placeholder as string) || ""}
            defaultValue={props.defaultValue as string}
            type={(props.inputType as string) || "text"}
            className="input-base"
          />
        </div>
      );

    case "select":
      const selectLabel = props.label as string | undefined;
      return (
        <div key={id} className="flex flex-col gap-1">
          {selectLabel && <label className="text-xs text-tertiary">{selectLabel}</label>}
          <select
            name={props.name as string}
            defaultValue={props.defaultValue as string}
            className="input-base"
          >
            {(props.options as Array<{ value: string; label: string }>)?.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      );

    case "card":
      const title = props.title as string | undefined;
      return (
        <div key={id} className="card-bordered p-4 space-y-3" style={props.style as Record<string, string> || {}}>
          {title && <h3 className="text-sm font-semibold text-primary">{title}</h3>}
          {childNodes}
        </div>
      );

    case "table":
      return (
        <div key={id} className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-default">
                {(props.headers as string[])?.map((h: string, i: number) => (
                  <th key={i} className="px-3 py-2 text-left text-tertiary font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(props.rows as string[][])?.map((row: string[], ri: number) => (
                <tr key={ri} className="border-b border-default hover:bg-[var(--dt-colors-bg-hover)]">
                  {row.map((cell: string, ci: number) => (
                    <td key={ci} className="px-3 py-2 text-secondary">{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "badge":
      const badgeVariants: Record<string, Record<string, string>> = {
        default: { backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-secondary)" },
        success: { backgroundColor: "var(--dt-colors-status-success-bg)", color: "var(--dt-colors-status-success)" },
        warning: { backgroundColor: "var(--dt-colors-status-warning-bg)", color: "var(--dt-colors-status-warning)" },
        danger: { backgroundColor: "var(--dt-colors-status-error-bg)", color: "var(--dt-colors-status-error)" },
        info: { backgroundColor: "var(--dt-colors-status-info-bg)", color: "var(--dt-colors-status-info)" },
      };
      return (
        <span key={id} className="inline-block px-2 py-0.5 rounded-full text-xs font-medium" style={badgeVariants[(props.variant as string) || "default"]}>
          {props.text as string}
        </span>
      );

    case "code":
      return (
        <pre key={id} className="bg-tertiary rounded-lg p-3 overflow-x-auto text-sm">
          <code className={props.language ? `language-${props.language as string}` : ""}>{props.content as string}</code>
        </pre>
      );

    case "image": {
      const imgUrl = props.url as string;
      const src = safeResourceUrl(imgUrl, "image");
      if (!src) {
        return <span key={id} className="text-tertiary text-sm">Blocked image URL</span>;
      }
      return (
        <img key={id} src={src} alt={props.alt as string || ""}
          className={`rounded-lg max-w-full ${props.className as string || ""}`}
          style={{ maxHeight: props.maxHeight as string || "300px", ...(props.style as Record<string, string> || {}) }}
        />
      );
    }

    case "progress":
      const pct = ((props.value as number || 0) / (props.max as number || 1)) * 100;
      return (
        <div key={id} className="w-full bg-tertiary rounded-full h-2">
          <div className="h-2 rounded-full transition-all duration-300" style={{ width: `${Math.min(pct, 100)}%`, backgroundColor: "var(--dt-colors-accent-default)" }} />
        </div>
      );

    case "columns":
      const cols = children?.length || 2;
      return (
        <div key={id} className="grid gap-4" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {childNodes.map((child, i) => <div key={i}>{child}</div>)}
        </div>
      );

    case "link": {
      const href = props.href as string;
      const safeHref = safeResourceUrl(href, "link");
      if (!safeHref) {
        return <span key={id} className="text-tertiary text-sm">{props.text as string} (blocked)</span>;
      }
      return (
        <a key={id} href={safeHref} target="_blank" rel="noopener noreferrer"
          className="text-accent hover:text-[var(--dt-colors-accent-hover)] underline text-sm">
          {props.text as string}
        </a>
      );
    }

    case "list":
      return (
        <ul key={id} className="space-y-1 list-disc list-inside">
          {(props.items as Array<{ text: string; sub?: string }>)?.map((item, i) => (
            <li key={i} className="text-sm text-secondary">
              {item.text}
              {item.sub && <span className="text-tertiary text-xs ml-2">{item.sub}</span>}
            </li>
          ))}
        </ul>
      );

    case "spacer":
      return <div key={id} style={{ height: props.size as string || "1rem" }} />;

    case "tabs":
      return (
        <div key={id} className="space-y-2">
          {(props.tabs as Array<{ label: string; content: ComponentDef }>)?.map((tab, i) => (
            <div key={i}>
              <h4 className="text-sm font-medium text-secondary mb-1">{tab.label}</h4>
              <div className="pl-3 border-l-2 border-default">
                {renderComponent(tab.content, onAction)}
              </div>
            </div>
          ))}
        </div>
      );

    default:
      return <div key={id} className="text-tertiary text-sm">Unknown: {type}</div>;
  }
}

const CanvasViewer = memo(function CanvasViewer({ sessionId, className }: { sessionId: string; className?: string }) {
  const [canvas, setCanvas] = useState<CanvasState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const sock = new WebSocket(`${proto}//${window.location.host}/api/canvas/ws/${sessionId}`);
    sock.onopen = () => {
      const token = getToken();
      if (token) {
        sock.send(JSON.stringify({ type: "auth", token }));
      }
    };
    sock.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data) as CanvasState;
        setCanvas(data);
        setError(null);
      } catch (e) {
        console.error("Canvas fetch failed:", e);
      }
    };
    sock.onerror = (e) => {
      console.error("Canvas WS error:", e);
      setError("Canvas connection lost");
    };
    sock.onclose = () => {
      if (ws.current) return;
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
      resetTimerRef.current = setTimeout(() => {
        setCanvas(null);
        resetTimerRef.current = null;
      }, 3000);
    };
    ws.current = sock;
    return () => {
      if (resetTimerRef.current) {
        clearTimeout(resetTimerRef.current);
        resetTimerRef.current = null;
      }
      sock.close();
    };
  }, [sessionId]);

  const onAction = useCallback((componentId: string, action: string, data?: Record<string, unknown>) => {
    const token = getToken();
    fetch(`/api/canvas/action/${sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { "Authorization": `Bearer ${token}` } : {}) },
      body: JSON.stringify({ component_id: componentId, action, data }),
    }).catch((e) => console.error("Canvas action fetch failed:", e));
  }, [sessionId]);

  if (error) {
    return <div className="text-danger text-sm p-4 bg-danger-muted rounded-lg">{error}</div>;
  }

  if (!canvas?.root) {
    return (
      <div className="flex items-center justify-center h-48 text-tertiary text-sm">
        Canvas is empty — tell the agent to render something
      </div>
    );
  }

  return (
    <div className={`card p-3 space-y-3 ${className || ""}`}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-tertiary font-mono uppercase tracking-wider">Live Canvas</span>
        <span className="text-[10px] text-tertiary">{canvas.session_id.slice(0, 16)}</span>
      </div>
      <div className="space-y-3 canvas-root">
        {renderComponent(canvas.root, onAction)}
      </div>
    </div>
  );
});

export default CanvasViewer;
