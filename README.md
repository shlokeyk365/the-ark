# the ark

the ark is a map-centric, real-time disaster-response world model for flood
emergencies. The MVP is a deterministic, replayable Nakkhu River scenario
that derives infrastructure status, safe routes, community isolation, hazards,
and comparable response-plan outcomes from one canonical world state.

The fixture is synthetic demonstration data and is not operational guidance.

## Current backend slice

- Five communities, two bridges, one hospital, and two shelters.
- Nine flood frames at 3-hour intervals from now through +24h. The original
  now/+6h/+12h/+24h depths remain anchors; intervening frames are explicitly
  labeled linear interpolations for smoother demonstration playback.
- Deterministic edge closures and travel penalties.
- Safe-path, access, and time-to-isolation calculations.
- Plan A/B/C evaluation against a frozen state.
- An injected East River Bridge failure with stale-result retention and
  recomputation.
- FastAPI endpoints returning frontend-ready state.
- Any frame viewable with injected events held active, with time-to-isolation
  recomputed for that event set.
- A frozen CatBoost impact prior trained on 4,869 historical Nepal flood events,
  projected across ten research-only operational POIs on the timeline and map.
- Durable full-horizon simulation runs with one immutable analysis report per
  run, including timeline and event-counterfactual changes.
- Report archive with JSON, CSV, and printable HTML/PDF exports.

## Verify

```bash
npm test
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
Playback advances one 3-hour frame every 2.4 seconds.

The Reports tab creates explicit full-horizon runs. Browsing or scrubbing a
frame does not create a report. Every completed run freezes its event set and
fixture digest, persists all four world-state snapshots in SQLite, and creates
one report from those stored results. Set `THE_ARK_REPORT_DB_PATH` to override
the default `data/runtime/the-ark.sqlite3` location.

### Basemap

The map renders on **MapLibre GL JS** over a **Protomaps PMTiles** vector
basemap, with optional satellite imagery and 3D terrain. There is no access
token, no account, and no metered tile API.

Fetch the Nakkhu/Kantipur Colony basemap once:

```bash
npm run basemap
```

`npm run dev` also performs this fetch automatically when the archive is
missing, so a fresh clone starts with the geographic map without an extra setup
step.

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
gauges, alerts, model prediction pings, community labels, and administrative
context — plus satellite and 3D terrain toggles. River gauges are listed but
disabled: the fixture has no gauge observations yet.

Prediction pings are clickable. Each explanation card separates current
timeline risk from the shared event prior and shows nearby modeled flood depth,
exposed population, location-specific responder priority, the reason the POI
was flagged, and the recommended action. These rankings are research-only and
not validated for live dispatch.

The administrative boundaries are Kathmandu and Lalitpur Metropolitan City,
visual context only — see `data/scenarios/kantipur-river/SOURCES.md` for
provenance and licensing. The flood surface is a curated synthetic depth-band
fixture, not a hydraulic solve or operational forecast. Its 0/6/12/24h
keyframes are cross-faded across the three-hour playback frames; route safety
still comes from canonical per-edge conditions. Each timeline percentage is a
deterministic adjustment of a frozen event-level impact prior using
absolute nearby depth, infrastructure thresholds/status, route criticality, and
synthetic exposed population. Map coordinates remain visualization anchors,
not building-level forecasts.

Useful endpoints:

- `GET /health`
- `GET /scenarios/kantipur-river/bootstrap`
- `GET /scenarios/kantipur-river/baseline`
- `GET /scenarios/kantipur-river/frames/ktp-frame-plus-12h`
- `GET /scenarios/kantipur-river/frames/ktp-frame-plus-24h?events=ktp-event-bridge-02-failure`
- `POST /scenarios/kantipur-river/events/ktp-event-bridge-02-failure`
- `POST /scenarios/kantipur-river/runs`
- `GET /scenarios/kantipur-river/runs`
- `GET /scenarios/kantipur-river/runs/{run_id}`
- `GET /reports/{report_id}`
- `GET /reports/{report_id}/export?format=json|csv|html`
- `GET /docs`
- `GET /openapi.json`

See `docs/api-contract.md`, `docs/world-state-contract.md`, and
`docs/scenario-contract.md` for payload semantics.
