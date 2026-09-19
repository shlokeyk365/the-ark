# Ark API

One modular FastAPI application on Python 3.12. From this directory:

```powershell
uv sync --locked
uv run uvicorn ark_api.main:app --reload
```

`GET /health` returns `{"status":"ok","service":"ark-api"}`. The deterministic
engine is available as a Python function; no simulation HTTP endpoint exists yet.

Development checks:

```powershell
uv run ruff format .
uv run ruff check .
uv run pytest
```

## Contract decisions

- Models reject unknown fields, scalar coercion (such as string or boolean
  counts), nonfinite numbers, and blank identifiers. Enum values are lowercase
  strings; JSON arrays are accepted for capability sets. Metadata contains JSON
  values only. Collections and metadata use independent default factories.
- Times are absolute nonnegative minutes on the scenario clock. Optional closure
  and isolation times may be historical, current, future, or unknown (`null`).
  A request can be reported after isolation. No speculative ordering constraint
  is imposed between observation time, isolation time, and snapshot time.
- IDs are unique per world collection; action IDs are unique per plan. World
  node references and distinct route endpoints are checked during validation.
- Shelter occupancy describes initial state and cannot exceed capacity. Peak
  overflow is a separate result metric. Future runtime state may need a distinct
  model if simulated occupancy is permitted to exceed capacity.
- `ScenarioResult.status` uses `PlanStatus`. `ActionStatus` is reserved for future
  execution records; proposals deliberately have no execution status field.
  Violations are explanatory strings. Counts are required in metric reports;
  response averages and scores may be unknown (`null`).
- Contracts alone do not authorize actions. The engine validates every action
  against authoritative route state and current execution ledgers at dispatch.
  Model construction checks are not a replacement for that execution boundary.
- Enum vocabularies are an initial contract, not an imported external schema.
  Plans are resolved against the isolated world at execution time. Existing
  responder assignments make responders unavailable; they are not simulated.

`tests/conftest.py` supplies a generic two-node world with every entity type for
future tests. Framework behavior follows the official
[Pydantic validation documentation](https://docs.pydantic.dev/latest/concepts/strict_mode/)
and [uv project workflow](https://docs.astral.sh/uv/concepts/projects/sync/).

## Deterministic execution

Call `ark_api.simulation.engine.simulate_plan(world_state, plan, duration_minutes=60)`
to receive a `ScenarioResult`. The engine deep-copies both inputs. Public input
models are never mutated; private dataclass ledgers hold positions, assignments,
reservations, counts, and statuses. No schema changes or dependencies were needed.

The clock uses absolute minutes from `world_state.current_minute` through
`current_minute + duration_minutes`, inclusive. Each minute applies authoritative
closures, processes arrivals, and then dispatches actions ordered by start minute,
responder ID, and action ID. Arrivals free resources before same-minute dispatch.
Zero-distance actions complete immediately. Earlier actions are rejected at the
initial minute; future actions beyond the horizon are pending. A successful call
always returns terminal status `completed` at the horizon, even with unfinished
actions or when all actions were rejected. This status describes completion of
the bounded simulation run, not completion of every action.

Each action still in progress receives a `SIMULATION_COMPLETED` horizon observation
with `phase=incomplete_at_horizon`, `action_status=in_progress`, its `action_id`,
and responder `actor_id`. These observations are ordered by responder ID then
action ID, before the final summary. They are neither action completions nor
failures. The final summary lists future, undispatched `pending_action_ids`.
Unfinished rescue service does not increase rescued totals; unfinished evacuation
does not increase evacuated totals or shelter occupancy. Existing reservations
and in-transit state remain visible in the final ledger.

Every accepted action emits acceptance, dispatch, arrival, and completion events
as those transitions occur. `ACTION_STARTED` events carry a `phase` distinguishing
dispatch, arrival, pickup, service, and shelter admission. Rejections emit a stable
`ReasonCode` in event metadata and in `violations`. Events have monotonically
assigned IDs. The final event contains an auditable execution ledger. In transit,
a responder has `node_id=null`, one route ID, one assignment, and a bounded load.

### Routing and the physics boundary

- Dijkstra routing minimizes the sum of `ceil(base_travel_minutes / speed_multiplier)`
  per edge, with minimum one minute per edge. Decimal-rational arithmetic avoids
  floating-point rounding ambiguity. Equal-cost paths prefer lexicographically
  smaller route-ID sequences, then node-ID sequences.
- One-way edges, closed status, capability restrictions, and scheduled closures
  apply to both legs of an evacuation. An edge must be exited **strictly before**
  its closure minute: entry, traversal, or arrival at/after closure is forbidden.
  Full projected traversal is checked at dispatch; known future closures cannot
  strand an accepted trip midway. No waiting/reopening is modeled.
- `allowed_capabilities` describes alternative permitted capabilities, not an
  all-of requirement. An empty set permits any traveler. `restricted` edges still
  require a matching allowed capability; `closed` edges are always unavailable.
- Civilian reachability uses only road/foot capabilities, speed 1.0, and the same
  temporal routing rules. Water-only routes never count as civilian paths.
  A safe node is reachable from itself without a route. With no safe nodes,
  nobody at a node can reach safety.
- Physics remains authoritative over hazards and routes. The engine applies
  supplied closure times to its private closed-route ledger; it never modifies
  hazard observations, calculates water movement, or reopens routes. The input
  snapshot and its closure schedule are fixed for the run.
- Future MiroFish integration may propose actions through the same validator;
  it cannot mutate physical state or bypass deterministic admission checks.

### Supported actions and population accounting

- `MOVE` also serves prepositioning: target node only, no people/references.
- `RESCUE` requires a request, people count, matching target node, `RESCUE`, and
  all request capabilities (`MEDICAL` additionally for medical priority). Service
  is instantaneous at arrival; this action does not transport people to shelter.
  Partial service updates remaining people; first service time is recorded once.
- `EVACUATE` requires a community, shelter, people count, matching pickup node,
  and `EVACUATION`. Pickup is instantaneous, followed by transport and admission.
  Evacuated totals and shelter occupancy increase only on shelter arrival.
- Counts above capacity or remaining population are rejected, not silently
  truncated. Partial service means explicitly requesting a smaller valid count.
  Outstanding actions reserve people and shelter space at dispatch, preventing
  concurrent duplicate service or overbooking. Shelter overflow records the
  largest rejected admission excess, including existing reservations.
- **Input population assumption:** each request and community represents a
  disjoint cohort, including when they share a node. Do not represent the same
  people in multiple records. The schemas contain no person IDs or cohort links,
  so cross-record identity cannot be inferred. Within each cohort, service and
  reservations prevent double counting. Completed requests start fully served;
  for other request statuses, `people_count` is the initially unserved cohort
  (historical partial service is not separately represented).
- Initial evacuated counts and shelter occupancy are preserved. Rescued/evacuated
  metrics count only new work in this run. Critical-call metrics describe final
  complete/unresolved urgency-4/5 requests, excluding cancelled/unreported calls.
  Response time is the mean reported-to-first-service-arrival delay per serviced
  request; it is null without service.
- Isolation counts unserved request people and community members still awaiting
  pickup at unreachable nodes. People aboard an active trip are not at the pickup
  node and are not yet counted as evacuated. Stranding counts responders at nodes
  unable to reach a safe node; responders on validated trips are not stranded.
  Reachability uses final simulation time, not the descriptive isolation fields.

### Intentionally unimplemented

Other action types produce `unsupported_action` rejections. No random behavior,
optimized dispatch, weighted scoring (`score=null`, `score_breakdown=[]`), MiroFish,
LLM calls, real flood physics, live hazard updates, persistence, background jobs,
or frontend changes. Results are not resumable checkpoints. No type checker is
configured. Run `uv run pytest` for contracts, health, routing, validation,
execution, metric, determinism, and conservation tests.

## Candidate response plans

Call `ark_api.simulation.plans.generate_candidate_plans(world_state)` to obtain
exactly three independent `ready` plans in the order below. These are auditable
baseline policies, not optimized or AI-generated plans. Generation never runs a
simulation or calculates scores, and never mutates the input snapshot.

1. **`immediate-rescue`**: rescue only. Requests are ordered by descending urgency,
   ascending isolation minute (missing last), ascending reported minute, then
   request ID. Assign the feasible responder with the earliest projected arrival,
   breaking ties by responder ID. Assign up to its capacity or the remaining
   request population; use additional responders only while people remain.
2. **`balanced-response`**: aim for half rescue and half evacuation, with the odd
   extra responder assigned to rescue. Initial feasibility includes capabilities,
   routes, people, and shelter capacity. Preserve rescue-only and evacuation-only
   responders in their respective categories; divide flexible responders by ID
   to fill the rescue quota first. The quota uses the number of responders with
   some feasible work. Capability constraints can override the numerical split.
   Apply rescue priority within the rescue pool, then community priority within
   the evacuation pool. Reconsider unused responders for remaining rescue work,
   then remaining evacuation work, rather than forcing an unproductive split.
3. **`preventive-evacuation`**: communities are ordered by ascending isolation
   minute (missing last), descending initially unevacuated population, then
   community ID. For each community choose the responder/shelter pair carrying
   the most people in one trip, then earliest shelter arrival, earliest pickup,
   responder ID, and shelter ID. The count is the minimum of responder capacity,
   remaining community population, and unreserved shelter capacity. Use further
   responders only while population remains. Unused responders may then rescue
   urgency-4/5 requests using the rescue priority above.

Each responder receives **at most one primary service action per plan**, starting
at the current scenario minute. Actions are returned in engine execution order
(start minute, responder ID, action ID). IDs encode strategy, responder, target,
and assignment sequence; components are percent-encoded to avoid ambiguity.
Generation order establishes allocation priorities; returned execution order
does not imply a different target priority. Each plan has its own people/shelter
reservations and responder assignment ledger.

Every proposal passes the existing deterministic validator, which uses the
existing shortest-path router to check capabilities, both evacuation legs,
projected times, and strict closure boundaries. Arrival exactly at closure is
rejected. Only available, unassigned, positive-capacity responders are considered.
Completed, cancelled, and not-yet-reported requests are skipped. Fully evacuated
communities, unusable shelters, and unreachable targets produce no invalid
actions. Empty or infeasible worlds still produce three valid empty plans.
There is no plan metadata field; skipped-target behavior is documented here and
tested in `tests/test_plans.py`, rather than adding a schema field for diagnostics.

Limitations: this is greedy allocation, not global optimization or a repeated-trip
schedule. Isolation times set priority; authoritative route availability decides
feasibility. The generator has no simulation-duration argument, so feasible trips
may extend beyond a later caller-selected horizon. The existing disjoint-cohort
population assumption still applies. Engine execution always revalidates actions;
planning feasibility cannot bypass that boundary. MiroFish can later be another
proposal source behind the same deterministic validator, without permission to
change physical state.
