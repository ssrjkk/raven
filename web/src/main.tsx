import "./styles/index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { ToastProvider } from "./components/Toast";

// The tracer configures itself on import, so it is only pulled in when the bundle was
// built with an endpoint. Without this the OpenTelemetry packages sit in node_modules
// and no span is ever produced.
const otelEndpoint = import.meta.env.VITE_OTEL_ENDPOINT;
if (otelEndpoint) {
  void import("./instrumentation");
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(e => console.error("sw:", e));
  });
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>
);