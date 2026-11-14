import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Vite matches these keys in order, so the socket's own prefix has to come first: written as a
      // bare string, `/api` proxies plain calls and answers a WebSocket upgrade with 426, which the
      // editor retries forever in dev while the same page works in production, where the gateway
      // serves it itself.
      "/api/collab": {
        target: "http://localhost:18888",
        ws: true,
      },
      "/api": "http://localhost:18888",
      "/aios": {
        // The agent socket is mounted at /aios/ws/agent, so this prefix carries WebSocket upgrades as
        // well as plain calls. Written as a bare string, vite proxies HTTP only and the socket
        // reconnect-loops against a 426 in dev while working in production, where the gateway itself
        // serves the page.
        target: "http://localhost:18888",
        ws: true,
      },
      "/ws": {
        target: "ws://localhost:18888",
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 500,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "vendor",
              test: /node_modules[\/](react|react-dom|react-router|react-router-dom|framer-motion|@tanstack[\/]react-query)[\/]/,
            },
            { name: "editor", test: /node_modules[\/]@monaco-editor[\/]react[\/]/ },
            { name: "charts", test: /node_modules[\/]recharts[\/]/ },
          ],
        },
      },
    },
  },
});