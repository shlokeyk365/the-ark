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

The Reports tab creates explicit full-horizon runs. Browsing or scrubbing a
frame does not create a report. Every completed run freezes its event set and
fixture digest, persists all four world-state snapshots in SQLite, and creates
one report from those stored results. Set `THE_ARK_REPORT_DB_PATH` to override
the default `data/runtime/the-ark.sqlite3` location.

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

Map layers follow the operator list: flood depth (current), the modeled +24h
extent, roads and closures, active response routes, alternate plan routes,
shelters and the hospital, bridges, river gauges, hazards, community labels, and
administrative context. The basemap itself is a radio choice between the
operational vector style and satellite imagery, with 3D terrain as a separate
toggle. River gauges are listed but disabled: the fixture has no gauge
observations yet, and alternate plan routes are off by default.

The visual grammar is consistent across every layer:

- **Shape carries entity type, colour carries status.** Communities are circles,
  shelters houses, the hospital a cross, hazards triangles, closures a crossed
  circle. A shelter that cannot be reached is still a house, just muted.
- **Solid is current, dashed is modeled.** The current flood extent, the active
  route and confirmed closures are solid; the +24h envelope and alternate plans
  are dashed. Operator-injected state is amber, so an event the operator caused
  never reads as an observation.
- **Hazards are drawn on the thing that is hazardous.** A blocked road is
  restyled along its own geometry with a heavier casing and a status label; a
  failed bridge is marked on that span, not on a marker beside it.
- **Detail arrives with zoom.** Far out you see the flood extent, the network,
  communities and critical hazards; closer in, facility labels, closures and
  routes; closest, depth bands, population and per-segment status.

The OpenStreetMap basemap is deliberately restyled for operations: POI and
address symbols are dropped, minor roads fade back and hold until z13, buildings
wait for z15, and waterways are brightened rather than suppressed — the flood
story is a river story. Place names stay legible throughout.

Two things on the map move, and both move because the world state changed.
Response teams travel the selected plan's routes, staggered so they do not run
in lockstep, with their destination and ETA shown only for the focused route; a
route that crosses a failed edge carries no team, because no team is driving it.
Separately, a hazard that has just escalated to critical pulses for about five
seconds and then stops — one at a time, never on first load, and cancelled early
if the operator selects it. Hazard ids carry the world-state version and so
change every frame; escalation is therefore tracked per asset, which across a
full nine-frame baseline fires twice. Both effects share one animation frame
loop that parks itself when idle, and neither runs under
`prefers-reduced-motion` — teams are placed but held still.

Clicking a community, road, bridge or hazard — on the map or in either rail —
enters incident focus. The camera frames the affected area, everything outside
the incident dims, and a panel states the affected population, the nearest
reachable facility, the route time and what has become unreachable. "Exit focus"
restores the full picture.

The administrative boundaries are Kathmandu and Lalitpur Metropolitan City,
visual context only — see `data/scenarios/kantipur-river/SOURCES.md` for
provenance and licensing.

The flood surface is generated from public elevation data rather than drawn.
`npm run flood:generate` decodes AWS Terrarium DEM tiles over the scenario
extent, fills depressions, routes D8 flow to find the channel, computes height
above nearest drainage, and contours the resulting depth field into the four
contract depth bands. Terrain gives the bands their shape; the canonical
per-edge depths in `flood-frames.json` give them their depths and their growth
curve, so every frame carries a surface and the water spreads along the valley
instead of blinking between hand-drawn stills. It is still a synthetic
demonstration surface, not a hydraulic solve or operational forecast.

The previous hand-authored surface is kept at
`flood-polygons.curated-v1.geojson`; `npm run flood:restore` puts it back, and
both pass the fixture contract and test suite.

The road network is reshaped the same way. `npm run network:snap` reads the
OpenStreetMap `roads` layer out of the basemap archive and routes each scenario
edge along real street centrelines, so the network follows the city instead of
drawing a rectangle over it; bridges take only the ~200 m of their route that
crosses the water. Topology, travel times and every domain result are unchanged
— routing never reads geometry. `npm run network:restore` brings the authored
straight lines back. Route safety still
comes from the canonical per-edge flood conditions; see
`docs/scenario-contract.md` for the separation of concerns.

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
