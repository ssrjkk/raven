import { useCallback, useEffect, useRef,useState } from "react";

interface AsyncDataState<T> {
  data: T | null;
  loading: boolean;
  error: string;
}

export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
): AsyncDataState<T> & { refresh: () => void } {
  const [state, setState] = useState<AsyncDataState<T>>({ data: null, loading: true, error: "" });
  const mountedRef = useRef(true);
  const [version, setVersion] = useState(0);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    mountedRef.current = true;
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: "" }));
    fetcher()
      .then((result) => {
        if (!cancelled && mountedRef.current) {
          setState({ data: result, loading: false, error: "" });
        }
      })
      .catch((e: unknown) => {
        if (!cancelled && mountedRef.current) {
          setState({ data: null, loading: false, error: e instanceof Error ? e.message : String(e) });
        }
      });
    return () => { cancelled = true; };
  }, [version, ...deps]);

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  return { ...state, refresh };
}
