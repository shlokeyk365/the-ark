# MVP architecture

## Data flow

```text
curated flood frame + injected event
                  |
                  v
       canonical world-state version
                  |
        +---------+----------+
        |                    |
        v                    v
 edge status / routing   hazards / access
        |                    |
        +---------+----------+
                  |
                  v
     frozen Plan A/B/C evaluation
                  |
                  v
        frontend-ready API payload
```

The world state is the shared source of truth. Physics inputs publish flood
conditions; routing translates them into infrastructure consequences; scenarios
branch and score immutable snapshots; the API returns the derived result. The
frontend does not recalculate domain logic.

## Current modules

- `data/scenarios/kantipur-river/`: deterministic topology, flood, plan, event,
  and context fixtures.
- `services/routing/`: edge derivation, graph construction, safe paths, access,
  and time-to-isolation.
- `services/scenarios/`: fixture validation, plan scoring, invalidation, and
  event recomputation.
- `apps/api/`: strict Pydantic wire models plus FastAPI endpoints for bootstrap,
  baseline, named frames, and event flow.
- `apps/web/`: React operations shell with a projected SVG map, timeline,
  hazards, community access, and counterfactual plan comparison.
- `packages/shared-types/`: TypeScript wire contracts for frontend consumers.

## Stable boundaries

- Flood producers provide normalized edge-level depths and do not mutate route
  or plan results.
- Routing consumes the canonical frame and optional active events.
- Scenario evaluation consumes a frozen derived state.
- Future agents may explain completed results but cannot alter safety fields or
  scores.
- Administrative context boundaries are visual reference data only and are not
  loaded by routing or scenario services.

## Frontend integration

The dashboard loads bootstrap geometry and the baseline state in parallel. It
requests named frames from the timeline and replaces the current state with the
event recomputation response when the bridge failure is injected. It highlights
the selected plan's returned route IDs but does not calculate routing or scoring
inside the browser.
