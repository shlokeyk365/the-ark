# Canonical world-state contract

Status: MVP contract

Schema version: `1.0.0`

## Purpose

The canonical world state is the single timestamped description of an incident
used by routing, scenario evaluation, the API, and the frontend. Flood inputs do
not directly mutate routes or plan results. They produce a new world-state
version, and derived services calculate consequences from that immutable input.

The Nakkhu/Kantipur Colony fixtures are modeled, synthetic demonstration data. They are not
operational flood guidance.

## Snapshot identity

Every snapshot contains:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | string | Payload contract version. |
| `scenario_id` | string | Stable scenario identifier. |
| `world_state_version` | string | Unique immutable state version. |
| `observed_at` | ISO-8601 string | Timestamp attached to the modeled input. |
| `calculated_at` | ISO-8601 string | Time derived results were calculated. |
| `simulation_time_hours` | number | Hours from the scenario baseline. |
| `frame_id` | string | Flood frame used to derive the snapshot. |
| `data_classification` | string | `modeled_synthetic_demo` for this MVP. |
| `operational_use` | boolean | Always `false` for the Kantipur demo. |

Every snapshot also carries `prediction_signals`. These are separately labeled
`scenario_adjusted_model_prior` interpretations. Each retains the frozen
event-impact `base_probability`, while its displayed probability increases with
the anchor edge's modeled flood-stage progress and elapsed scenario time. Its
`forecast`/`active` state changes separately at the configured activation hour.

World-state versions are append-only. Applying an event creates a new version;
it never edits an earlier snapshot in place.

## Flood input

A flood frame supplies one deterministic `flood_depth_m` reading for every
routing edge. Each frame also records its rainfall assumption and source type.
Missing or duplicate edge readings are invalid fixture data.

Routing derives edge status using the thresholds stored on the edge:

1. `closed` when `flood_depth_m >= closure_depth_m`.
2. `restricted` when it is below the closure threshold but
   `flood_depth_m >= penalty_depth_m`.
3. `open` otherwise.

A restricted edge uses `baseline_travel_minutes * penalty_multiplier`. An
operator-injected `force_close_edge` event overrides the flood-derived status.

## Infrastructure and routes

Each derived edge state contains:

- `edge_id`, `status`, and `closure_reason`.
- `flood_depth_m` and the threshold values used.
- `effective_travel_minutes`, which is `null` when closed.
- `source_frame_id` and any `originating_event_id`.

Routes are derived outputs. A route contains ordered node and edge IDs, total
travel minutes, and source and destination IDs. It is nested in a versioned
world-state or plan result and inherits that payload's world-state reference.
GeoJSON geometry is for display; only `from_node_id` and `to_node_id` establish
graph connectivity.

## Community access and isolation

Shelter access and hospital access are calculated independently.

A community is `isolated` only when it has no traversable path to any open
shelter and no traversable path to the hospital. An assignment to a full shelter
may make a plan non-viable, but shelter capacity does not change the graph-level
isolation definition.

`time_to_isolation_hours` is the first supplied flood-frame time at which the
community is isolated. It is `null` when the community remains connected through
the fixture horizon.

The forecast is computed for the snapshot's own active event set, with each
event applied only to the frames at or after its effective hour. An injected
disruption therefore pulls the value forward instead of leaving the baseline
forecast in place, and a community reporting `isolated: true` can never also
report a future isolation time.

## Events and provenance

Every event records:

- A stable `event_id` and `event_type`.
- `effective_at_hours` and an ISO-8601 timestamp.
- `source_type`: `operator_injected` for the MVP disruption.
- A reliability label and human-readable description.
- A typed list of state changes.

Observed input, modeled input, operator-injected events, derived results, and AI
interpretation must remain separately labeled. AI output cannot change this
contract's physical or safety fields.

The prediction pings therefore cannot change an edge state, route, isolation
result, hazard, or counterfactual plan score. Their coordinates are map anchors
for operational attention, not localized model outputs.

## Validation behavior

Loaders must fail visibly when:

- IDs are duplicated or references do not resolve.
- A flood frame omits or duplicates a routing edge.
- A threshold is contradictory or negative.
- A plan references an unknown community or shelter.
- Frames are not in increasing simulation-time order.
- An event targets an unknown asset or edge.
