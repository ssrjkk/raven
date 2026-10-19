import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:18888",
      "/aios": "http://localhost:18888",
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