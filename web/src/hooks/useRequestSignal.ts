import { useEffect,useRef } from "react";

export function useRequestSignal(): AbortSignal {
  const controllerRef = useRef(new AbortController());

  useEffect(() => {
    const ctrl = controllerRef.current;
    return () => ctrl.abort();
  }, []);

  return controllerRef.current.signal;
}
