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
      return <Tag key={id} className={`text-gray-200 ${Tag !== "p" ? "font-bold" : ""}`} style={{ color: props.color as string }}>{props.content as string}</Tag>;
    }

    case "button":
      return (
        <button
          key={id}
          onClick={() => onAction(id, props.action as string, props.data as Record<string, unknown> || {})}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
            (props.variant as string) === "danger" ? "bg-red-700 hover:bg-red-600 text-white" :
            (props.variant as string) === "success" ? "bg-green-700 hover:bg-green-600 text-white" :
            (props.variant as string) === "outline" ? "border border-gray-600 hover:bg-gray-800 text-gray-200" :
            "bg-violet-700 hover:bg-violet-600 text-white"
          } ${props.className as string || ""}`}
          disabled={props.disabled as boolean}
          style={props.style as Record<string, string> || {}}
        >
          {props.label as string}
        </button>
      );

    case "input":
      const label = props.label as string | undefined;
      return (
        <div key={id} className="flex flex-col gap-1">
          {label && <label className="text-xs text-gray-500">{label}</label>}
          <input
            name={props.name as string}
            placeholder={(props.placeholder as string) || ""}
            defaultValue={props.defaultValue as string}
            type={(props.inputType as string) || "text"}
            className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-violet-500/50"
          />
        </div>
      );

    case "select":
      const selectLabel = props.label as string | undefined;
      return (
        <div key={id} className="flex flex-col gap-1">
          {selectLabel && <label className="text-xs text-gray-500">{selectLabel}</label>}
          <select
            name={props.name as string}
            defaultValue={props.defaultValue as string}
            className="bg-gray-800/60 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-violet-500/50"
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
        <div key={id} className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4 space-y-3" style={props.style as Record<string, string> || {}}>
          {title && <h3 className="text-sm font-semibold text-gray-200">{title}</h3>}
          {childNodes}
        </div>
      );

    case "table":
      return (
        <div key={id} className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800/50">
                {(props.headers as string[])?.map((h: string, i: number) => (
                  <th key={i} className="px-3 py-2 text-left text-gray-500 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(props.rows as string[][])?.map((row: string[], ri: number) => (
                <tr key={ri} className="border-b border-gray-800/30 hover:bg-gray-800/20">
                  {row.map((cell: string, ci: number) => (
                    <td key={ci} className="px-3 py-2 text-gray-300">{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "badge":
      const variantMap: Record<string, string> = {
        default: "bg-gray-700 text-gray-200",
        success: "bg-green-900/50 text-green-300",
        warning: "bg-amber-900/50 text-amber-300",
        danger: "bg-red-900/50 text-red-300",
        info: "bg-blue-900/50 text-blue-300",
      };
      return (
        <span key={id} className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${variantMap[props.variant as string] || variantMap.default}`}>
          {props.text as string}
        </span>
      );

    case "code":
      return (
        <pre key={id} className="bg-black/40 rounded-lg p-3 overflow-x-auto text-sm">
          <code className={props.language ? `language-${props.language as string}` : ""}>{props.content as string}</code>
        </pre>
      );

    case "image": {
      const imgUrl = props.url as string;
      const allowedUrl = imgUrl.startsWith("http://") || imgUrl.startsWith("https://") || imgUrl.startsWith("data:image/");
      if (!allowedUrl) {
        return <span key={id} className="text-gray-500 text-sm">Blocked image URL</span>;
      }
      return (
        <img key={id} src={imgUrl} alt={props.alt as string || ""}
          className={`rounded-lg max-w-full ${props.className as string || ""}`}
          style={{ maxHeight: props.maxHeight as string || "300px", ...(props.style as Record<string, string> || {}) }}
        />
      );
    }

    case "progress":
      const pct = ((props.value as number || 0) / (props.max as number || 1)) * 100;
      return (
        <div key={id} className="w-full bg-gray-800 rounded-full h-2">
          <div className="bg-violet-600 h-2 rounded-full transition-all duration-300" style={{ width: `${Math.min(pct, 100)}%` }} />
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
      const allowed = href.startsWith("http://") || href.startsWith("https://") || href.startsWith("mailto:") || href.startsWith("/");
      const noXss = !href.includes("javascript:") && !href.includes("data:") && !href.includes("vbscript:");
      if (!allowed || !noXss) {
        return <span key={id} className="text-gray-500 text-sm">{props.text as string} (blocked)</span>;
      }
      return (
        <a key={id} href={href} target="_blank" rel="noopener noreferrer"
          className="text-violet-400 hover:text-violet-300 underline text-sm">
          {props.text as string}
        </a>
      );
    }

    case "list":
      return (
        <ul key={id} className="space-y-1 list-disc list-inside">
          {(props.items as Array<{ text: string; sub?: string }>)?.map((item, i) => (
            <li key={i} className="text-sm text-gray-300">
              {item.text}
              {item.sub && <span className="text-gray-500 text-xs ml-2">{item.sub}</span>}
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
              <h4 className="text-sm font-medium text-gray-300 mb-1">{tab.label}</h4>
              <div className="pl-3 border-l-2 border-gray-700">
                {renderComponent(tab.content, onAction)}
              </div>
            </div>
          ))}
        </div>
      );

    default:
      return <div key={id} className="text-gray-500 text-sm">Unknown: {type}</div>;
  }
}

const CanvasViewer = memo(function CanvasViewer({ sessionId, className }: { sessionId: string; className?: string }) {
  const [canvas, setCanvas] = useState<CanvasState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/api/canvas/ws/${sessionId}`;
    const sock = new WebSocket(url);
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
      setTimeout(() => {
        setCanvas(null);
      }, 3000);
    };
    ws.current = sock;
    return () => sock.close();
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
    return <div className="text-red-400 text-sm p-4 bg-red-900/10 rounded-lg">{error}</div>;
  }

  if (!canvas?.root) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-600 text-sm">
        Canvas is empty — tell the agent to render something
      </div>
    );
  }

  return (
    <div className={`space-y-3 p-3 bg-gray-950/50 rounded-xl border border-gray-800/30 ${className || ""}`}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-gray-700 font-mono uppercase tracking-wider">Live Canvas</span>
        <span className="text-[10px] text-gray-600">{canvas.session_id.slice(0, 16)}</span>
      </div>
      <div className="space-y-3 canvas-root">
        {renderComponent(canvas.root, onAction)}
      </div>
    </div>
  );
});

export default CanvasViewer;
