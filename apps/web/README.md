# The Ark web dashboard

The frontend is a Vite, React, and TypeScript operations shell for the Kantipur
River scenario. It consumes only backend-derived domain results.

## Run locally

Install the pinned dependencies once:

```bash
npm install --prefix apps/web
```

Start the API from the repository root:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/pycache-the-ark npm run dev:api
```

In a second terminal, start the frontend:

```bash
npm run dev:web
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` requests to
`http://127.0.0.1:8000`.

## Verify

```bash
npm run typecheck:web
npm run build:web
```

Set `VITE_API_BASE_URL` when the API is hosted at another origin.

## Basemap

Keyless. From the repository root, fetch the tile archive once:

```bash
npm run basemap
```

Everything in `.env.example` is optional. Without the archive the dashboard
renders the SVG schematic instead and explains why.

## Map architecture

- `src/map/basemap.ts` — basemap endpoints and attribution. No credentials.
- `src/map/scenarioSources.ts` — pure API-payload-to-GeoJSON derivation. No
  domain logic lives here.
- `src/map/layers.ts` — MapLibre layer specifications and the operator-facing
  toggle groups.
- `src/map/MapLibreScenarioMap.tsx` — map lifecycle, data updates, layer
  visibility, satellite and 3D terrain.
- `src/components/SchematicMap.tsx` — token-free fallback renderer.
- `src/components/ScenarioMap.tsx` — picks between the two and lazy-loads
  MapLibre.

All rendered state comes from the API. The map recomputes nothing.

### Notes

- `optimizeDeps.exclude: ["maplibre-gl"]` in `vite.config.ts` is required:
  Vite's dependency pre-bundling breaks MapLibre's module-worker handshake in
  dev, and the style then never loads.
- MapLibre defers style loading to `requestAnimationFrame`. Where that never
  runs (hidden tab, throttled webview, headless browser) the map cannot start,
  so a 15s watchdog trips the schematic fallback rather than spinning forever.
