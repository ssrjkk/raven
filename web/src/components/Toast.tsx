import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

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

const TOAST_ICON: Record<ToastType, typeof Info> = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
};

/** Written as names, not as values: the pair a toast ships with is the pair the sheet publishes, and a
 *  class list is something the design gates can read. */
const TOAST_TONE: Record<ToastType, string> = {
  success: "toast-success",
  error: "toast-error",
  info: "toast-info",
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
    const existing = timersRef.current.get(id);
    if (existing) clearTimeout(existing);
    const exitTimer = setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
      timersRef.current.delete(id);
    }, EXIT_MS);
    timersRef.current.set(id, exitTimer);
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
          const Icon = TOAST_ICON[t.type];
          return (
            <div
              key={t.id}
              role="status"
              className={`toast overflow-hidden rounded-xl border backdrop-blur ${TOAST_TONE[t.type]} ${t.leaving ? "toast-exit" : "toast-enter"}`}
            >
              <div className="flex items-start gap-2.5 px-3.5 py-3">
                <Icon size={16} className="toast-icon mt-0.5 shrink-0" />
                <p className="flex-1 text-sm font-medium text-primary">
                  {t.message}
                </p>
                <button
                  type="button"
                  onClick={() => dismiss(t.id)}
                  className="shrink-0 opacity-50 hover:opacity-100 transition-opacity"
                  aria-label="Dismiss notification"
                >
                  <X size={14} className="text-tertiary" />
                </button>
              </div>
              <div className="toast-progress" style={{ animationDuration: `${AUTO_DISMISS_MS}ms` }} />
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
