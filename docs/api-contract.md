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
- Curated synthetic flood-depth polygons for every timeline frame, for display
  and situational awareness only.
- Ordered timeline frame summaries.
- Available injected events.
- Plan A/B/C definitions and assignments.
- `impact_model`, a research-only model summary with training-event count,
  grouped-evaluation metrics, feature policy, and limitations.

The bootstrap response intentionally excludes flood edge readings and derived
results. Those come from a versioned world-state endpoint. `flood_polygons` is
static display geometry and must not be used to infer route safety in the
browser.

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
one immutable state version. It also contains `prediction_signals`, ten
time-adjusted operational POIs spanning the model's four impact targets.

Each prediction signal includes the frozen `base_probability` from the event
model and a displayed localized score adjusted for the current scenario frame.
The adjustment combines absolute flood depth on the declared `anchor_edge_id`,
its closure threshold and current status, route criticality, and the population
of `exposure_asset_id`. The signal also includes `priority_score`,
`priority_rank`, `priority_level`, local flood depth, activation state, the
reason the location was flagged, and a recommended action.

`score_type` is `prototype_localized_risk_score`. Neither that score nor the
priority rank is a calibrated hourly probability or validated dispatch rule.
The model still predicts whole-event impacts, not street-level depth.

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

## Incident Copilot hybrid chat

`POST /intelligence/chat`

The Copilot follows a strict routing boundary:

- Supported road/bridge blockage observations are parsed deterministically and
  returned as tentative updates requiring operator confirmation.
- Exact questions about mapped road, bridge, facility, or community status are
  answered deterministically from the requested `WorldStateSnapshot`.
- Other questions are sent to Claude with a bounded, read-only grounding
  bundle. Claude cannot mutate the world state.

The Claude bundle contains the canonical world state, mapped assets, routed
network, timeline metadata, available events, plan definitions, field
intelligence, the responder-simulation fixture, the latest saved full-horizon
map report, and the latest persisted validated MiroFish proposal result when
one exists. Raw basemap imagery and flood-polygon coordinates are omitted
because they are visual-only; routed-edge depths and consequences remain in the
canonical state.

Claude uses constrained JSON-schema output, a no-outside-knowledge system
instruction, and evidence IDs validated against the supplied bundle. This
reduces unsupported output but does not turn generated prose into physical
truth; safety-critical status lookups remain deterministic.

Set `ANTHROPIC_API_KEY` on the API process. `ANTHROPIC_MODEL` defaults to the
active `claude-sonnet-4-6`. Missing configuration returns `503`; provider or grounding
validation failure returns `502`.

## Incident Copilot map briefing

`POST /intelligence/map-summary`

Accepts a `frame_id` plus the active scenario-event and confirmed
field-intelligence report IDs. The API rebuilds that canonical world state and
builds deterministic facts and asks Claude to phrase a grounded
`MapSummaryResponse` containing:

- A headline and plain-language overview of route, community, hospital,
  hazard, event, and plan status.
- Prioritized actions derived from isolation timing, route state, and the
  highest-ranked model signal.
- The strongest currently evaluated response plan using the existing plan
  metrics.
- Machine-readable counts and explicit limitations.

Claude cannot change the machine-readable facts or mutate the simulation. The
source world-state version is returned so the frontend can discard a briefing
as soon as the operator changes frames or events.

## Injected event

`POST /scenarios/kantipur-river/events/{event_id}`

Returns `EventRecomputeResponse`, containing:

- The applied event.
- The previous and updated world-state versions.
- Retained prior plan results marked `stale` with an invalidation reason.
- Recomputed `current` results against the updated state.

The MVP endpoint is deterministic and stateless. Repeating the same request
replays the same named event rather than mutating server-global state.

## Simulation runs and reports

`POST /scenarios/kantipur-river/runs`

Accepts an optional ordered `event_ids` array. The service validates the IDs,
freezes the inputs, evaluates every frame, persists the complete run, and
returns `SimulationRun`. A run receives a unique `run_id` and `report_id`; the
SHA-256 `input_fingerprint` remains stable when the scenario fixtures and event
set are identical.

Ordinary frame reads and timeline playback do not create runs or reports.

- `GET /scenarios/kantipur-river/runs` returns newest-first summaries.
- `GET /scenarios/kantipur-river/runs/{run_id}` returns the frozen snapshots and
  report for one run.
- `GET /reports/{report_id}` returns the immutable report.
- `GET /reports/{report_id}/export?format=json|csv|html` renders the stored
  report without recomputing its findings. The HTML export is print-styled for
  browser PDF output.

Reports contain headline metrics, deterministic narrative, adjacent-frame
changes, event-versus-baseline effects, community impact, plan analysis,
assumptions, limitations, and provenance. The historical impact prior is marked
`impact_prior_used: false`; external news is not part of report calculation.

Persistence defaults to `data/runtime/the-ark.sqlite3`. Override it with
`THE_ARK_REPORT_DB_PATH`.

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
