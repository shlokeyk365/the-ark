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
score.

## Frontend payload

The API returns already-derived results:

- Snapshot identity and recomputation status.
- Asset and edge status with closure reasons.
- Community shelter/hospital access and time-to-isolation.
- Prioritized hazards with originating edge, frame, or event IDs.
- Plan actions, comparable metrics, lifecycle status, and invalidation reason.

The frontend may sort, filter, and visualize these fields but must not recompute
routing, isolation, capacity, or plan viability.

## Flood depth polygons

`flood-polygons.geojson` provides a curated, synthetic depth surface for every
timeline frame. It is referenced by `scenario.json`, validated during scenario
load, and served in the bootstrap response as `flood_polygons`.

The collection is a **rendering and situational-awareness input**. Routing,
closures, isolation, and plan scoring continue to derive from the frame's
`edge_conditions`; the polygon geometry is never used as a safety constraint.
This boundary keeps the deterministic engine authoritative while allowing the
map to show a coherent surface.

Shape:

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
        "simulation_time_hours": 12,
        "depth_min_m": 0.3,
        "depth_max_m": 0.5,
        "band_label": "0.30–0.50 m",
        "surface_kind": "curated_synthetic_surface",
        "source_type": "modeled_input"
      },
      "geometry": { "type": "Polygon", "coordinates": [[[85.31, 27.69], "..."]] }
    }
  ]
}
```

Validation guarantees:

- One or more polygons per `frame_id`, banded by depth so the map can shade by
  severity rather than drawing a single flat extent.
- Every frame has a surface, and every referenced `frame_id` exists in
  `flood-frames.json`.
- Bands begin at zero, are contiguous, and cover the frame's peak edge depth.
- Rings are closed and remain within the scenario's Nepal coordinate bounds.
- Classification remains synthetic/modelled and `operational_use` remains
  `false`.

The frontend renders the selected frame with a shared depth ramp, overlays the
last horizon frame as a faint dashed extent, exposes provenance on hover, and
uses a short opacity transition when the frame changes. The surface is labeled
as curated synthetic data and not as a hydraulic solve or operational forecast.
