import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ToastProvider } from "./components/Toast";
import "./styles/index.css";

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>
);