# the ark Agent Guide

## Project at a glance

the ark is a map-centric, real-time disaster-response world model for flood emergencies. It is **not** a generic flood-prediction dashboard. The product should help an incident commander answer:

- What infrastructure or community becomes unreachable next?
- Which community will be isolated first?
- What happens under each available response plan?
- How should the plan change when rainfall, flood conditions, or infrastructure status changes?

The system combines a flood-state input, an infrastructure/routing graph, and a counterfactual scenario engine. The UI is a consumer of this shared state; it is not a separate source of truth.

## MVP scope: Kantipur River

Build one deterministic, replayable scenario around the **Kantipur River**. The MVP should be small, coherent, and demonstrable rather than geographically complete or operationally accurate.

The scenario target is:

- One river basin / valley.
- Five communities.
- A small road network with two bridges.
- One hospital and two shelters.
- Three response plans: Plan A, Plan B, and Plan C.
- Time-indexed flood conditions: now, +6h, +12h, and +24h.
- At least one injected disruption: bridge failure or increased rainfall.

Scenario assets belong in `data/scenarios/kantipur-river/`. Keep the initial data curated and deterministic so all results are repeatable.

## Product boundaries

### In scope for the MVP

- Display and serve a canonical incident/world state.
- Determine whether roads and bridges are traversable from a supplied flood state.
- Compute safe paths between communities, shelters, and the hospital.
- Compute community time-to-isolation.
- Compare Plan A/B/C under the same baseline state.
- Recompute affected routes, isolation results, and plan results after an event.
- Provide API data that the frontend can render as a map, timeline, hazard queue, and plan comparison.

### Explicitly out of scope initially

- Government-grade flood forecasting or real evacuation orders.
- Nationwide or multi-basin coverage.
- Fully live data integrations; start with fixtures.
- A live numerical hydrodynamic solver; accept precomputed or simplified flood-state inputs.
- Authentication, RBAC, dispatch, SMS, mobile apps, and 3D terrain.
- MiroFish or LLM agents as a dependency of the core path.
- Claims that simulated human behavior predicts how real people will act.

## Canonical system model

Every subsystem must read from or update one versioned, timestamped world state. Do not let the map, routing engine, scenario engine, or agents maintain competing versions of reality.

The canonical state must be able to represent:

- **Incident metadata:** scenario ID, world-state version, timestamp, simulation time, model/source metadata.
- **Hydrology:** flood depth, flood arrival time, rainfall assumption, and frame/time index.
- **Infrastructure:** roads, bridges, hospital, shelters, accessibility status, and closure reason.
- **Communities:** population estimate, vulnerable-population proxy if used, evacuation state, and time-to-isolation.
- **Resources:** only if a plan needs them; include available capacity, assigned route, and ETA.
- **Intelligence/events:** source, timestamp, reliability, and the state change caused by an observation or injected event.
- **Scenarios:** baseline snapshot, actions, assumptions, metrics, status, and invalidation/recompute reason.

Use `packages/shared-types/` for shared TypeScript-facing contracts. The backend may mirror them with Pydantic models, but the two representations must carry the same semantic fields.

## Person B ownership: integration and counterfactual engine

Your work is the middle layer that makes the product behave like one system. You own the interfaces and orchestration between flood-state inputs, infrastructure consequences, routing, scenario evaluation, and frontend-ready results.

### Primary responsibilities

1. Define the world-state contract and API-facing schemas.
2. Model the road/bridge/hospital/shelter network as a graph.
3. Convert flood state and events into road/bridge closures or penalties using deterministic rules.
4. Recalculate routes and time-to-isolation when infrastructure changes.
5. Branch a frozen baseline state into Plan A/B/C and score each plan consistently.
6. Invalidate stale plan results and recompute only affected results after an event.
7. Expose backend data and event payloads the frontend can consume without reproducing domain logic.
8. Preserve stable handoff points so physics, frontend, and future MiroFish/agent work can progress independently.

### Do not own initially

- Visual layout, map styling, or frontend component implementation.
- Building the flood solver or choosing/calibrating physical flood equations.
- Live-feed provider implementation beyond agreeing on normalized input payloads.
- LLM-generated recommendations or MiroFish behavior modeling.

## Integration contracts

### Required input from the physics/world owner

The integration layer needs a deterministic flood-state input for each time step. It must identify the relevant time/frame and enough geometry or asset-level values to decide whether a road or bridge is safe.

The physics side must not mutate routing or scenario results directly. It publishes an updated flood-state frame; Person B translates that into infrastructure consequences.

### Required output for the frontend owner

The frontend should receive already-derived domain results, not rebuild routing or plan logic in the browser. Provide:

- Current world-state version and simulation time.
- Asset status and closure/failure reason.
- Community access status and time-to-isolation.
- Prioritized hazards with the originating state/asset IDs.
- Plan A/B/C actions, status, and comparable metrics.
- Event/recompute status so the UI can show a plan becoming stale and then updated.

### Future agents and MiroFish

Agents may read the canonical state and completed scenario results to summarize hazards, explain tradeoffs, or propose candidate actions. They may not directly change flood depth, safety constraints, asset status, routes, or plan scores.

MiroFish, if added, is a scenario-assumption provider for stress testing. It is not physical truth and must not block or override deterministic routing and safety rules.

## First implementation milestone: static end-to-end flow

The first goal is not realism. It is a working full chain for one fixed Kantipur River baseline and one injected event.

1. Define the Kantipur River assets, baseline flood frames, and Plan A/B/C fixture data.
2. Define shared entities and a versioned world-state snapshot.
3. Load the baseline state through the API.
4. Build the infrastructure graph and find safe routes.
5. Apply deterministic flood/asset closure rules.
6. Calculate time-to-isolation per community.
7. Evaluate all three plans against the same frozen snapshot.
8. Return comparable plan metrics to the frontend.
9. Apply one disruption event.
10. Recompute closures, routes, isolation, hazards, and all affected plans.
11. Confirm the frontend can render both the baseline and changed result from API data.

## Counterfactual rules

- Freeze the canonical world state at a named version before evaluating a plan.
- Clone that snapshot once per plan; never mutate the baseline in-place.
- Plan actions may include evacuation priority, shelter opening/closing, route preference, resource assignment, or a stated contingency.
- Each plan must be measured with the same metric definitions and time horizon.
- When an input assumption changes, mark impacted plans stale, retain the prior result for audit/display, and calculate a new result against the new state version.
- Every result must record the source state version, plan ID, assumptions, and calculation timestamp.

Initial plan metrics:

- People isolated.
- People evacuated by the evaluation deadline.
- Evacuation completion time.
- Critical routes lost.
- Hospital accessibility.
- Shelter overload.
- Plan viability: whether hard access/capacity constraints are satisfied.

Do not show an unsupported generic AI confidence score. Robustness across perturbed scenarios is a later feature.

## Repository map

```text
apps/web/                         Frontend application
apps/api/                         Backend/API application
packages/shared-types/            Shared API and world-state contracts
packages/ui/                      Shared presentation components
services/ingest/                  Future source adapters and normalization
services/physics/                 Flood-state producer/replay interface
services/routing/                 Graph, closures, paths, isolation logic
services/scenarios/               Plan branching and evaluation
services/agents/                  Future LLM/MiroFish adapters
data/scenarios/kantipur-river/    Fixed MVP scenario fixtures
infra/                            Local service configuration and migrations
docs/                             Architecture and contract documentation
```

Place code according to domain ownership. Do not create duplicate routing, scenario, or shared-type logic inside the frontend.

## Engineering rules for agents

- Inspect existing contracts and teammate changes before editing shared interfaces.
- Keep functions deterministic for the same fixture inputs.
- Use IDs and references between assets, communities, events, and plans; avoid display-name matching.
- Keep domain logic on the backend/services layer, not in frontend components.
- Prefer fixtures and unit tests before live APIs or external services.
- Fail visibly on missing/contradictory scenario data; do not invent safety-critical values.
- Label observed input, modeled output, operator-injected event, and AI interpretation separately.
- Do not expose secrets, API tokens, or personally identifying data in fixtures or commits.
- Preserve unrelated teammate changes. Do not reset, overwrite, or reformat files outside the active task.
- Update the relevant contract documentation whenever a shared payload changes.

## Definition of done for Person B's first milestone

The milestone is complete when a caller can load the Kantipur River baseline, inspect all community access states and time-to-isolation values, compare Plan A/B/C metrics, inject a defined bridge/rainfall event, and receive an updated world-state version with recalculated routes, hazards, isolation results, and plan results.

Tests must at minimum cover a reachable baseline, a road/bridge closure, an isolated community, distinct plan outcomes, and plan invalidation/recomputation after the injected event.
