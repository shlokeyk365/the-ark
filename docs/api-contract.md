# Frontend API contract

Status: MVP contract

The FastAPI response models in `apps/api/models.py` are the executable source of
truth for the frontend wire format. They reject undeclared fields, validate all
responses, and publish JSON Schema through `GET /openapi.json`.

All domain payloads use `snake_case`, stable IDs, and schema version `1.0.0`.
Numbers may be serialized as integers or decimals and should be consumed as
JavaScript `number` values.

## Bootstrap

`GET /scenarios/kantipur-river/bootstrap`

Returns static data needed to initialize the frontend:

- Scenario identity, classification, initial frame, and evaluation horizon.
- Asset GeoJSON for communities, shelters, hospital, and bridges.
- Routing-network GeoJSON with explicit node references and thresholds.
- Administrative context boundaries for map background only.
- Ordered timeline frame summaries.
- Available injected events.
- Plan A/B/C definitions and assignments.
- `impact_model`, a research-only model summary with training-event count,
  grouped-evaluation metrics, feature policy, and limitations.

The bootstrap response intentionally excludes flood edge readings and derived
results. Those come from a versioned world-state endpoint.

### Administrative context

`context_boundaries` is a `ContextBoundaryCollection` of Kathmandu and Lalitpur
Metropolitan City polygons, classified `external_reference`. It exists so the
map can outline the two municipalities over the basemap.

It is **not** a domain input. Every feature carries `routing_enabled: false` and
`flood_model_input: false`, and fixture validation rejects the collection if
those flags flip or if a context ID collides with a routed asset or edge ID.
Provenance and licensing are recorded in
`data/scenarios/kantipur-river/SOURCES.md`.

## World state

- `GET /scenarios/kantipur-river/baseline`
- `GET /scenarios/kantipur-river/frames/{frame_id}`

Both return `WorldStateSnapshot`. The payload contains derived edge status,
community access, routes, hazards, time-to-isolation, and Plan A/B/C results for
one immutable state version. It also contains `prediction_signals`, four
time-adjusted risk indicators used by the dashboard pings.

Each prediction signal includes the frozen `base_probability` from the event
model and a displayed `probability` adjusted for the current scenario frame.
The adjustment combines flood depth on the ping's declared `anchor_edge_id`
with elapsed simulation time. The signal also includes its rounded percentages,
local flood depth, map anchor, activation hour, timeline state (`forecast` or
`active`), and a recommended action.

The adjusted value is a scenario risk projection, not a second ML inference or
a calibrated hourly forecast. The model still predicts whole-event impacts,
not street-level depth.

The frame endpoint accepts a repeatable `events` query parameter so a caller can
inspect any frame with injected events held active:

```text
GET /scenarios/kantipur-river/frames/ktp-frame-plus-24h?events=ktp-event-bridge-02-failure
```

`time_to_isolation_hours` is recomputed for the supplied event set, so an
isolated community never reports a future isolation time.

Status codes:

- `404` — unknown frame or event ID.
- `409` — the event exists but is not yet effective at the requested frame.

## Injected event

`POST /scenarios/kantipur-river/events/{event_id}`

Returns `EventRecomputeResponse`, containing:

- The applied event.
- The previous and updated world-state versions.
- Retained prior plan results marked `stale` with an invalidation reason.
- Recomputed `current` results against the updated state.

The MVP endpoint is deterministic and stateless. Repeating the same request
replays the same named event rather than mutating server-global state.

## Health and discovery

- `GET /health`
- `GET /docs` for interactive API documentation.
- `GET /openapi.json` for the machine-readable contract.

## Local frontend access

The API allows `http://localhost:3000` and `http://localhost:5173` by default.
Override the comma-separated list with `THE_ARK_CORS_ORIGINS`.

The TypeScript declarations in `packages/shared-types/src/index.ts` mirror the
wire format. OpenAPI remains authoritative until automated type generation is
added.
