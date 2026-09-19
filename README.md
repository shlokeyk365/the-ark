# the ark

the ark is a map-centric, real-time disaster-response world model for flood
emergencies. The MVP is a deterministic, replayable Kantipur River scenario
that derives infrastructure status, safe routes, community isolation, hazards,
and comparable response-plan outcomes from one canonical world state.

The fixture is synthetic demonstration data and is not operational guidance.

## Current backend slice

- Five communities, two bridges, one hospital, and two shelters.
- Flood frames for now, +6h, +12h, and +24h.
- Deterministic edge closures and travel penalties.
- Safe-path, access, and time-to-isolation calculations.
- Plan A/B/C evaluation against a frozen state.
- An injected East River Bridge failure with stale-result retention and
  recomputation.
- FastAPI endpoints returning frontend-ready state.
- Any frame viewable with injected events held active, with time-to-isolation
  recomputed for that event set.

## Verify

```bash
PYTHONPYCACHEPREFIX=/private/tmp/pycache-the-ark python3 -m pytest -q
```

## Run the API

```bash
PYTHONPYCACHEPREFIX=/private/tmp/pycache-the-ark \
python3 -m uvicorn apps.api.main:app --reload
```

## Run the dashboard

Install the pinned frontend dependencies once:

```bash
npm install --prefix apps/web
```

Keep the API running, then start the Vite frontend in a second terminal:

```bash
npm run dev:web
```

Open `http://127.0.0.1:5173`. The development server proxies `/api` requests to
the local FastAPI process on port `8000`.

The dashboard loads every modeled frame on start, so scrubbing the timeline and
frame playback are instant and the sparklines plot real per-frame values. All
domain results come from the API; the browser derives no routing or plan logic.

### Basemap

The map renders on **MapLibre GL JS** over a **Protomaps PMTiles** vector
basemap, with optional satellite imagery and 3D terrain. There is no access
token, no account, and no metered tile API.

Fetch the Kantipur basemap once:

```bash
npm run basemap
```

That extracts the scenario's bounding box from the Protomaps daily planet build
over HTTP range requests — about 20 MB transferred for an 18 MB archive, rather
than the 138 GB planet — and writes
`apps/web/public/basemap/kantipur.pmtiles`. The archive is git-ignored and
regenerable; the script pins the bbox, max zoom, and pmtiles CLI version.

Serving it is just static file hosting with range-request support, so in
production point `VITE_BASEMAP_PMTILES` at S3, R2, or any CDN.

| Layer | Source | Cost |
| --- | --- | --- |
| Vector basemap | Protomaps PMTiles from OpenStreetMap, self-hosted | free (ODbL attribution) |
| Terrain DEM | AWS Open Data terrain tiles, Terrarium-encoded | free, no key |
| Satellite imagery | Esri World Imagery | free with attribution — confirm terms for your deployment |
| Glyphs & sprites | Protomaps basemap assets | free; self-hostable |

If the archive is missing or the basemap fails to start, the dashboard falls
back to a self-contained SVG schematic of the same derived state and says why,
so the scenario stays inspectable offline and in CI. MapLibre is code-split, so
that path stays light.

Map layers follow the operator list: modeled depth bands, 24h forecast extent,
roads, evacuation routes, hospitals and shelters, bridges, river
gauges, alerts, community labels, and administrative context — plus satellite
and 3D terrain toggles. River gauges are listed but disabled: the fixture has no
gauge observations yet.

The administrative boundaries are Kathmandu and Lalitpur Metropolitan City,
visual context only — see `data/scenarios/kantipur-river/SOURCES.md` for
provenance and licensing. The flood surface is a curated synthetic depth-band
fixture, not a hydraulic solve or operational forecast. Route safety still
comes from the canonical per-edge flood conditions; see
`docs/scenario-contract.md` for the separation of concerns.

Useful endpoints:

- `GET /health`
- `GET /scenarios/kantipur-river/bootstrap`
- `GET /scenarios/kantipur-river/baseline`
- `GET /scenarios/kantipur-river/frames/ktp-frame-plus-12h`
- `GET /scenarios/kantipur-river/frames/ktp-frame-plus-24h?events=ktp-event-bridge-02-failure`
- `POST /scenarios/kantipur-river/events/ktp-event-bridge-02-failure`
- `GET /docs`
- `GET /openapi.json`

See `docs/api-contract.md`, `docs/world-state-contract.md`, and
`docs/scenario-contract.md` for payload semantics.
