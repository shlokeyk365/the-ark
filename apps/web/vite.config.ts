import { existsSync, statSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const webRoot = path.dirname(fileURLToPath(import.meta.url));
const BASEMAP_ARCHIVE = path.join(webRoot, "public/basemap/kantipur.pmtiles");

/** Fail the production build if the Kantipur PMTiles archive is missing. */
function requireBasemap(): Plugin {
  return {
    name: "require-basemap",
    apply: "build",
    buildStart() {
      if (!existsSync(BASEMAP_ARCHIVE) || statSync(BASEMAP_ARCHIVE).size < 1_000) {
        throw new Error(
          "Missing public/basemap/kantipur.pmtiles. Run `npm run basemap` from the repo root so the deployed map is not the schematic fallback.",
        );
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), requireBasemap()],
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
