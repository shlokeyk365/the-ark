# Counterfactual scenario contract

Status: MVP contract

Schema version: `1.0.0`

## Evaluation model

Each plan is evaluated against the same frozen canonical world-state snapshot.
The evaluator clones the snapshot for each plan and never mutates the baseline.
Plan actions can select evacuation priority, shelter assignments, departure
offsets, and route preferences, but cannot override closed edges or capacity
constraints.

For the MVP, an evacuation assignment contains:

- `community_id` and `shelter_id`.
- `people` targeted by the assignment.
- `departure_offset_minutes` from the snapshot time.
- An optional route preference, initially `shortest_safe`.

People are counted as evacuated when their assigned shelter is reachable and
their departure offset plus route travel time is within the plan's evaluation
deadline. Hospital access is scored separately and never counts as evacuation.

## Result identity and lifecycle

Every result records:

| Field | Meaning |
| --- | --- |
| `result_id` | Unique evaluation result identifier. |
| `plan_id` | Evaluated plan. |
| `source_world_state_version` | Frozen input snapshot. |
| `status` | `current`, `stale`, or `superseded`. |
| `calculated_at` | Calculation timestamp. |
| `assumptions` | Exact plan and routing assumptions. |
| `invalidation_reason` | Why a prior result became stale, if applicable. |

When a flood frame or event changes an edge used by a result, the previous
result is retained and marked `stale`. Recalculation produces a new `current`
result referencing the new world-state version. The old result is not deleted.

The static MVP may conservatively invalidate all three plans after its injected
bridge event. Selective dependency-based invalidation can be introduced without
changing the payload shape.

## Metrics

All plans use the same definitions and evaluation deadline:

- `people_isolated`: population of graph-isolated communities.
- `people_evacuated_by_deadline`: people in successful assignments.
- `evacuation_completion_minutes`: latest successful arrival; `null` when no
  assignment succeeds.
- `critical_routes_lost`: number of critical routing edges that are closed.
- `hospital_accessible`: whether every community has a route to the hospital.
- `hospital_accessible_communities`: number of communities with such a route.
- `shelter_overload`: people assigned beyond combined per-shelter capacity.
- `plan_viable`: `true` only when all assignments are reachable, no shelter is
  overloaded, and every successful trip meets the deadline.

Metrics describe the synthetic scenario only. There is no generic AI confidence
score. The separately labeled impact probabilities are outputs from the frozen
historical-event model and are not plan-viability metrics.

## Frontend payload

The API returns already-derived results:

- Snapshot identity and recomputation status.
- Asset and edge status with closure reasons.
- Community shelter/hospital access and time-to-isolation.
- Prioritized hazards with originating edge, frame, or event IDs.
- Plan actions, comparable metrics, lifecycle status, and invalidation reason.

The frontend may sort, filter, and visualize these fields but must not recompute
routing, isolation, capacity, or plan viability.

## Historical impact prediction pings

`model-impact-prior.json` stores the frozen Nakkhu 2024 event input and four
probabilities produced by the CatBoost model. `prediction-pings.json` supplies
display anchors, nearby network edges, activation hours, explanation text, and
recommended actions. Multiple POIs may share one target's event prior; their
displayed risks differ because they are adjusted by different anchor-edge flood
depths. The scenario service joins them by target and returns the result as
`prediction_signals`.

The base percentages stay constant because the trained model is an event-level
impact classifier. The displayed percentage is a monotonic prototype localized
risk score. It combines five normalized components: absolute depth relative to
the scenario-wide maximum, depth relative to the edge closure threshold,
open/restricted/closed status, route criticality, and exposed population. The
weights differ by impact target: housing and casualty emphasize population,
while transport emphasizes thresholds, status, and route criticality.

| Target | Absolute depth | Closure threshold | Edge status | Critical route | Exposed population |
| --- | ---: | ---: | ---: | ---: | ---: |
| Casualty or missing | 35% | 25% | 15% | 5% | 20% |
| Housing damage | 35% | 25% | 10% | 0% | 30% |
| Transport disruption | 30% | 30% | 20% | 15% | 5% |
| Severe impact | 35% | 25% | 15% | 10% | 15% |

The displayed score is `base_probability * (0.10 + 0.90 * local_danger)`.
Responder priority is `70% local_danger + 30% base_probability`, ranked across
all POIs for the current frame. This prevents every location in a category from
converging to the same value merely because it reached its own local maximum.
The timeline separately marks a signal `active` at its configured activation
hour.

Priority levels are `critical` at 70 or above, `high` at 55–69, `elevated` at
35–54, and `low` below 35. These cutoffs are presentation assumptions, not an
incident-command standard.

A ping means “surface this evolving scenario risk near the relevant asset”; it
is not a claim that the exact point or building has that risk. This deterministic
adjustment is labeled `scenario_adjusted_model_prior` with score type
`prototype_localized_risk_score`; it must not be described as a new hourly ML
prediction or a validated live-dispatch rule. Its separation of hazard and
exposure follows the conceptual framing in
[UNDRR terminology](https://www.undrr.org/terminology/exposure), but the weights
are hackathon assumptions requiring emergency-management validation.

The prediction layer cannot close roads, alter flood depth, change routing, or
modify plan results. Those continue to come from the deterministic world state.

## Current visualization and planned flood inundation polygons

Status: placeholder animated envelope implemented; hydraulic polygons are not.
This section is the handoff contract for
`services/physics`, so the map layer can be swapped without frontend rework.

The scenario currently carries flood depth **per network edge** only. The map's
inundation layers therefore render a placeholder envelope — the channel
centreline widened in proportion to the frame's peak modeled depth. It conveys
extent and growth and nothing more. It is generated in
`apps/web/src/map/scenarioSources.ts` and marked
`provenance: "modeled_envelope_placeholder"` on every feature.

When the solver can publish a surface, add `flood-polygons.geojson` to
`data/scenarios/kantipur-river/` and reference it from `scenario.json`'s
`fixture_files`. Expected shape:

```json
{
  "type": "FeatureCollection",
  "scenario_id": "kantipur-river-v1",
  "data_classification": "modeled_synthetic_demo",
  "operational_use": false,
  "source": { "source_type": "modeled_input", "model_name": "...", "model_version": "..." },
  "features": [
    {
      "type": "Feature",
      "id": "ktp-flood-ktp-frame-plus-12h-0",
      "properties": {
        "frame_id": "ktp-frame-plus-12h",
        "depth_band_m_min": 0.3,
        "depth_band_m_max": 0.6,
        "provenance": "modeled_input"
      },
      "geometry": { "type": "Polygon", "coordinates": [[[85.31, 27.69], "..."]] }
    }
  ]
}
```

Requirements:

- One or more polygons per `frame_id`, banded by depth so the map can shade by
  severity rather than drawing a single flat extent.
- Every `frame_id` must exist in `flood-frames.json`; validation should reject
  polygons that reference an unknown frame.
- Polygons are a **rendering and situational-awareness input**. Edge closure and
  travel penalties continue to derive from `edge_conditions`, not from polygon
  containment, unless the routing contract is changed deliberately.
- Serve the collection through the bootstrap response next to
  `context_boundaries`, and the frontend replaces the placeholder source data
  with it.

Animation of the inundation layers (dash offset on the channel, growth
transitions between frames) belongs to the same phase and should use MapLibre
runtime styling — `setPaintProperty` on a `requestAnimationFrame` loop — so the
geometry stays declarative. See <https://maplibre.org/maplibre-gl-js/docs/>.
