import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";

type ToastType = "success" | "error" | "info";

interface ToastItem {
  id: string;
  message: string;
  type: ToastType;
  leaving?: boolean;
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextValue>({ toast: () => {} });

export function useToast() {
  return useContext(ToastContext);
}

const AUTO_DISMISS_MS = 4000;
const EXIT_MS = 220;

const TOAST_STYLE: Record<ToastType, { icon: typeof Info; border: string; bg: string; color: string; bar: string }> = {
  success: {
    icon: CheckCircle2,
    border: "var(--dt-colors-status-success)",
    bg: "var(--dt-colors-status-success-bg)",
    color: "var(--dt-colors-status-success)",
    bar: "var(--dt-colors-status-success)",
  },
  error: {
    icon: XCircle,
    border: "var(--dt-colors-status-error)",
    bg: "var(--dt-colors-status-error-bg)",
    color: "var(--dt-colors-status-error)",
    bar: "var(--dt-colors-status-error)",
  },
  info: {
    icon: Info,
    border: "var(--dt-colors-border-default)",
    bg: "var(--dt-colors-bg-secondary)",
    color: "var(--dt-colors-text-primary)",
    bar: "var(--dt-colors-accent-default)",
  },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  useEffect(() => {
    return () => {
      timersRef.current.forEach((t) => clearTimeout(t));
    };
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
    timersRef.current.delete(id);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, EXIT_MS);
  }, []);

  const toast = useCallback((message: string, type: ToastType = "info") => {
    const id = crypto.randomUUID();
    setToasts((prev) => [...prev.slice(-4), { id, message, type }]);
    const timer = setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    timersRef.current.set(id, timer);
  }, [dismiss]);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {toasts.map((t) => {
          const s = TOAST_STYLE[t.type];
          const Icon = s.icon;
          return (
            <div
              key={t.id}
              role="status"
              className={`overflow-hidden rounded-xl border shadow-lg backdrop-blur ${t.leaving ? "toast-exit" : "toast-enter"}`}
              style={{ backgroundColor: s.bg, borderColor: s.border }}
            >
              <div className="flex items-start gap-2.5 px-3.5 py-3">
                <Icon size={16} className="mt-0.5 shrink-0" style={{ color: s.color }} />
                <p className="flex-1 text-sm font-medium" style={{ color: "var(--dt-colors-text-primary)" }}>
                  {t.message}
                </p>
                <button
                  type="button"
                  onClick={() => dismiss(t.id)}
                  className="shrink-0 opacity-50 hover:opacity-100 transition-opacity"
                  aria-label="Dismiss notification"
                >
                  <X size={14} style={{ color: "var(--dt-colors-text-tertiary)" }} />
                </button>
              </div>
              <div className="toast-progress" style={{ backgroundColor: s.bar, animationDuration: `${AUTO_DISMISS_MS}ms` }} />
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
