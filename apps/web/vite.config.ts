import process from "node:process";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // npm workspaces can leave React both at the repository root and inside the
  // web workspace. Force every dependency (including lucide-react) to use the
  // same React instance so hooks share one dispatcher at runtime.
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  // MapLibre spawns its own module worker. Vite's dependency pre-bundling
  // rewrites the worker entry in a way that breaks that handshake in dev, so
  // the style never loads. Serving MapLibre's own ESM keeps it intact.
  optimizeDeps: {
    exclude: ["maplibre-gl"],
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        // Overridable so a second worktree's API can run alongside the default
        // one instead of both fighting over port 8000.
        target: process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
