import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
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
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
