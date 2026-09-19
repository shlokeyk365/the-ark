# Ark API

One modular FastAPI application on Python 3.12. From this directory:

```powershell
uv sync --locked
uv run uvicorn ark_api.main:app --reload
```

`GET /health` returns `{"status":"ok","service":"ark-api"}`. The deterministic
pipeline is exposed through `POST /api/v1/simulate-response` and Python functions.

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
optimized dispatch, robustness/Monte Carlo runs, MiroFish,
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

## Transparent scoring and ranking

Use `score_scenario_result(result)` to score one terminal result,
`rank_scenario_results(results)` to return independent scored copies in rank order,
and `recommend_plan_id(results)` to choose the first viable plan or return `None`.
All are in `ark_api.simulation.scoring`. The recommendation helper defensively
recomputes ranking; caller-provided order, scores, breakdowns, and viability flags
are never trusted. Engine execution itself still returns an unscored result.

The immutable default `ScoringPolicy` is `ark-response-priorities`, version
`1.0.0`. Nested weights and hard-constraint settings are also immutable. Create a
new policy for custom priorities; use a new policy ID/version when changing
operating priorities. Versions must be numeric `major.minor.patch` strings.
Unknown configuration fields, nonfinite weights, and invalid versions are errors.

| Metric | Default weight | Meaning |
| --- | ---: | --- |
| `people_rescued` | +10 | People newly serviced by completed rescue service in this run. |
| `people_evacuated` | +6 | Community members newly admitted to shelters in this run. |
| `people_isolated` | -15 | Unserved people at final nodes without civilian access to safety. |
| `responders_stranded` | -100 | Responders at final nodes without capability-valid access to safety. |
| `critical_calls_completed` | +25 | Fully completed urgency-4/5 calls at the horizon. |
| `critical_calls_unanswered` | -40 | Partially or completely unresolved urgency-4/5 calls. |
| `average_response_minutes` | -0.5 | Mean reported-to-first-service-arrival delay per serviced request. |
| `shelter_peak_overflow` | -20 | Largest attempted admission excess, including reservations. |
| `rejected_actions` | -5 | Plan actions rejected by deterministic validation. |

These weights express configurable operating priorities, **not scientifically
validated constants**. The score is a weighted comparison of simulated outcomes,
not AI confidence, statistical confidence, or a probability. It establishes no
optimality or safety guarantee and makes no claim about lives definitely saved.
Always display individual metrics and signed contributions alongside the total:
different outcomes can produce the same total, and a positive score can still
belong to a nonviable plan. Null response time remains null in metrics and in the
contribution's `raw_value`; it contributes zero without inventing a response time.

Each of the nine contributions includes its raw value, configured weight, signed
contribution, and deterministic explanation including policy ID/version. Arithmetic
uses exact rational values of the inputs' decimal representations. Only conversion
to the existing public float fields rounds to IEEE-754; there is no intermediate
rounding or rounding to a fixed number of decimal places. Consequently summing
serialized floats may show ordinary last-bit differences from the once-converted
exact total. Ranking uses the returned numeric score. Unrepresentably large
outputs raise `ValueError`; infinity and NaN are never returned as scores.

### Viability is separate from numerical score and run status

`ScenarioResult` adds `viable: bool | None` (default `None` means unevaluated) and
`nonviable_reasons: list[str]` (default empty). Scoring always sets these explicitly.
`ScoreContribution.raw_value` now permits `None` to faithfully represent an unknown
response time. These are the only public schema changes. A completed run can have
nonviable outcomes; scoring preserves its terminal `status`, metrics, timeline,
and original violations. Nonviable results still receive the full finite score.

The default hard constraints mark a result nonviable if any responders are
stranded or an explicit hard-safety failure uses one of these existing stable
validator codes: `capacity_exceeded`, `shelter_capacity_exceeded`, `shelter_closed`,
`missing_capability`, `no_route`.

An explicit failure means an **exact standalone code** in `violations`, or an
`ACTION_FAILED` timeline event with that exact `metadata.reason_code`. Producers
must reserve standalone codes for actual hard failures. The engine's ordinary
`action-id: reason-code: explanation` rejection strings and `ACTION_REJECTED`
events do not qualify, even when they contain one of these codes. Unknown codes,
free-text messages, and substring matches never create a hard failure. The current
engine prevents unsafe actions rather than emitting these execution failures.
Reason strings are stable, deduplicated, and sorted. Policies can change the
stranding threshold or the explicit-code allowlist; such changes alter viability.

Failed/cancelled terminal runs can be scored for inspection but are nonviable for
recommendation (`run_status:failed` / `run_status:cancelled`), independently of
safety failures. Draft, ready, and running results cannot be scored or ranked.
An action merely unfinished at a successfully reached simulation horizon does
not itself create a hard failure. Viable means it passed these configured checks,
not that it is guaranteed safe or that every action completed.

### Exact ranking order

1. Viable before nonviable.
2. Higher total score.
3. Fewer people isolated.
4. Fewer responders stranded.
5. Fewer critical calls unanswered.
6. Lower average response time, with null last.
7. Lexicographically smaller plan ID.

To explain relative ranks, use the first differing item in this ordered list.
Duplicate plan IDs are rejected. Empty input returns an empty ranking and no
recommendation; all-nonviable input also has no recommendation. Negative scores
are valid, including for the recommended viable plan. Results are compared only
under the supplied policy, with no mutation of the caller's list or objects.
Tests include the generic world -> candidate plans -> independent simulations ->
scoring -> ranking -> recommendation pipeline and serialization in
`SimulationResponse`.

## Synchronous simulation API

From `apps/api`, run `uv sync --locked`, then
`uv run uvicorn ark_api.main:app --reload`. The local API is at
`http://127.0.0.1:8000`; interactive documentation is at `/docs` and the generated
OpenAPI schema at `/openapi.json`.

`POST /api/v1/simulate-response` executes the complete pipeline **synchronously**
for the hackathon MVP: validate the request, generate or accept plans, simulate
each independently from the same world, score with the default policy, rank, and
recommend a viable plan. It does not create a background job. The route delegates
to `run_response_simulation`; existing domain functions implement all planning,
simulation, scoring, ranking, and recommendation behavior.

Request rules:

- `world_state` is required and uses the existing strict world contract.
- Omitted or null `plans` generates the three baseline strategies with their
  existing IDs. An explicitly empty list is an error.
- Supplied plans retain their IDs. IDs must be unique, statuses must be `ready`,
  and at most **20 plans** may be submitted. Empty-action ready plans are valid.
- `duration_minutes` defaults to 60 and must be an integer from **1 to 1,440**,
  inclusive. Limits bound accidental plan-count/time-horizon expansion, not the
  size of an arbitrary world graph or a wall-clock execution deadline.
- `random_seed` defaults to 42. It is accepted but unused by this deterministic
  engine, reserved for later robustness work. Changing it does not change results.
- Request objects, worlds, and supplied plans are not mutated.

The response contains ranked `ScenarioResult` objects with metrics, signed score
breakdowns, timelines, violations, viability flags/reasons, and terminal run status.
Poor outcomes and individual rejected actions still produce HTTP 200. A null
`recommended_plan_id` means no result passed the configured viability checks;
it is not a server failure. Model version is the fixed
`ark-response-simulator/0.1.0`, defined with the disclaimer and limits in
`routes/simulations.py`, not derived from timestamps or Git state.

Every successful response carries this fixed disclaimer:

> Ark provides experimental decision support. Results depend on supplied data,
> assumptions, and simplified simulation rules. Human incident command retains
> operational authority.

### Errors

Malformed JSON, unknown fields, invalid nested models, and nonpositive/noninteger
durations retain FastAPI's standard **422** `detail` response. A malformed plan
rejects the entire request before execution. Request-policy/domain failures use
**400**, and unexpected internal errors use **500**, with this consistent envelope:

```json
{"error":{"code":"DUPLICATE_PLAN_ID","message":"Plan IDs must be unique.","details":{}}}
```

| Code | HTTP | Meaning |
| --- | --- | --- |
| `EMPTY_PLANS` | 400 | Explicit empty submitted-plan list. |
| `DUPLICATE_PLAN_ID` | 400 | Submitted plan IDs repeat. |
| `TOO_MANY_PLANS` | 400 | More than 20 submitted plans; details includes `max_plans`. |
| `PLAN_NOT_READY` | 400 | A submitted plan is not ready. |
| `DURATION_LIMIT_EXCEEDED` | 400 | Duration exceeds 1,440; details includes `max_duration_minutes`. |
| `DOMAIN_VALIDATION_FAILED` | 400 | Planning or ranking rejects the supplied scenario/results. |
| `INTERNAL_ERROR` | 500 | Unexpected internal failure. |

Client messages are fixed and sanitized. Unexpected exceptions are logged through
standard Python logging; no exception details or stack traces enter the response.
Internal Pydantic construction failures are treated as server bugs, not malformed
client requests. Normal validation rejection of a PlanAction stays in its result.

### Compact example

Send this complete minimal request as JSON to `POST /api/v1/simulate-response`:

```json
{
  "world_state": {"scenario_id":"demo","current_minute":0,"nodes":[]},
  "duration_minutes":60,
  "random_seed":42
}
```

The response contains three empty-work results with score 0. The following shows
selected response fields only; the actual results also contain all nine metrics
and contributions, timeline events, violations, and nonviability reasons:

```json
{
  "recommended_plan_id":"balanced-response",
  "results":[
    {"plan_id":"balanced-response","status":"completed","score":0.0,"viable":true},
    {"plan_id":"immediate-rescue","status":"completed","score":0.0,"viable":true},
    {"plan_id":"preventive-evacuation","status":"completed","score":0.0,"viable":true}
  ],
  "model_version":"ark-response-simulator/0.1.0",
  "disclaimer":"Ark provides experimental decision support. Results depend on supplied data, assumptions, and simplified simulation rules. Human incident command retains operational authority."
}
```

Here the recommendation follows the plan-ID tie-breaker, not superior outcomes.
Scores remain operating-priority comparisons, never confidence or probabilities.

## Nepal Nakkhu demonstration

The versioned fixture is
`data/scenarios/kantipur-river/nepal_nakkhu_demo_v1.json`. From the repository root:

```powershell
& .\apps\api\.venv\Scripts\python.exe .\apps\api\scripts\run_nepal_demo.py
```

This offline runner calls the same orchestration function as the API, without a
live service. Add `--output PATH` to save the full response. See the
[scenario README](../../data/scenarios/kantipur-river/README.md) for historical
sources, explicit synthetic assumptions, ranked demo output, and API commands.

This scenario is a synthetic operational reconstruction inspired by the September
2024 Nakkhu River flood near Kantipur Colony and Nakhipot, Lalitpur, Nepal. Exact
responder positions, population counts, routes, travel times, closure times, and
outcomes are demonstration assumptions rather than verified historical records.

## Bounded agent proposals (Step 8B)

Agent proposals are untrusted until admitted by Ark's existing deterministic
validator. MiroFish never controls physics, routes, capacities, time, execution,
or scoring. The public simulation API is unchanged.

The inspected upstream is [666ghj/MiroFish](https://github.com/666ghj/MiroFish),
commit `39d849138ef254f6c737ab4c4705e5545dbe31d4`, licensed GNU AGPL v3.
Stock MiroFish is a Flask/Vue social simulation application using OASIS, model
providers and Zep Cloud. It has no native rescue actions, typed live Ark state
synchronization, or supported external Python SDK. Interview responses are
free-form: JSON adherence, deterministic behavior, calibrated human behavior,
offline operation and interactive latency are not guaranteed.

Ark uses an optional separate HTTP service boundary, not imported upstream
source. This is not production or legal approval: review AGPL obligations and
deployment/data handling with counsel before distribution or operational use.
The expected commit is a configured compatibility assertion, not remotely
attested by the interview endpoint.

### Configuration and admission

`agents/contracts.py` defines extra-field-forbidding contracts with strict scalar
counts and booleans. Requests allow only MOVE, RESCUE and EVACUATE, default to five
actions and permit at most ten. Trusted configuration supplies fixture paths and
service URLs; neither comes from a public request. HTTPX is a runtime dependency.

`RuleBasedProviderConfig.strategy` selects an existing candidate plan:
`immediate-rescue`, `balanced-response`, or `preventive-evacuation` (default:
balanced). No planner logic is reimplemented. Fixture configuration can require
request/scenario identity; scenario and snapshot identity are always checked.

The snapshot is SHA-256 of canonical UTF-8 JSON: sorted dictionary keys, sorted
sets, compact separators, and explicit schema version 1. It includes WorldState
except free-form metadata, simulation minute, duration, action allowlist/limit,
objectives and responder selection. List order is preserved, except allowlist
and responder selection are sorted. Request IDs, paths, credentials and wall-clock
metadata are excluded. Recompute fixtures whenever relevant inputs change.

Admission uses `ExecutionState.from_world` and `validate_action`, including the
existing closure-aware router. Private reservation ledgers prevent population
reuse and shelter overbooking. One assignment per responder per proposal batch
is deliberately conservative, including later scheduled assignments. The service
does not execute or score; accepted batches convert to normal READY ResponsePlans,
which the simulator validates again. Rescue-request populations and community
populations remain assumed disjoint; they must not describe the same people.

### Experimental live mode and fallback

`MiroFishProviderConfig` requires a trusted credential-free HTTP(S) origin,
simulation ID, platform, and bounded one-to-one responder/agent mapping. Defaults
are 2 seconds connect, 20 seconds total batch, five agents/actions, and 64 KiB
prompt/response limits. Queries run serially in responder-ID order, requesting at
most one action per responder. Only `data.result.response` in a successful,
identity-matched interview envelope is parsed. Extra fields, prose/Markdown,
unknown IDs, stale hashes and invalid scalar values are rejected without repair.

No redirects, environment proxies, or interview retries are enabled. A local
timeout does not cancel remote model work; late responses are ignored. Raw output
is omitted by default; explicitly enable `retain_raw_output` only with appropriate
data handling. Audit records hashes, provenance, rejection codes and fallback
origin without logging complete incident payloads, prompts or credentials.

Configure provider order in `AgentProposalService`: live development uses
MiroFish HTTP → fixture → rule-based; demos use fixture → rule-based. Typed provider
failures and zero accepted proposals trigger fallback by default. Disable via
`AgentProposalServiceConfig.fallback_enabled` or live config `fallback_enabled`;
`fallback_on_zero_accepted` controls empty admission. Exhaustion returns a failed
batch with `fallback_exhausted`. Failed attempts remain in audit, and each provider
receives a private copy of the original request.

### Demo commands and provenance

From the repository root:

```powershell
& .\apps\api\.venv\Scripts\python.exe .\apps\api\scripts\run_agent_proposals.py
```

The default loads the Nepal scenario and the clearly **synthetic** balanced-action
fixture at `apps/api/tests/fixtures/mirofish/interview_success.json`, validates it,
executes the normal simulator, and scores the result. No network, Zep or model
credentials are required. Synthetic fixtures are not live MiroFish results and
make no claim that MiroFish computed flood physics. `recorded` is reserved for
actual captured output; `live` and `rule_based` identify those distinct sources.
An exhausted chain reports provenance `unavailable` and exits nonzero.

To attempt an already running, separately provisioned MiroFish service, set
`ARK_MIROFISH_BASE_URL`, `ARK_MIROFISH_SIMULATION_ID`, `ARK_MIROFISH_PLATFORM`
(`twitter` or `reddit`), and `ARK_MIROFISH_AGENT_MAPPING` (JSON mapping Ark responder
IDs to integer upstream agent IDs), then add `--live` to the command above. Ark
does not start MiroFish, create its simulations, or manage model/Zep API keys.
The live provider is experimental; fixture mode is the hackathon default.

## Deterministic robustness and sensitivity (Step 9)

Robustness tests how already constructed response plans behave under changed
scenario assumptions. It does not predict future events. Robustness rates and
recommendation stability are not probabilities or AI confidence. Synthetic Nepal
variations are not historical reconstructions. MiroFish and other agent/model
providers are never called during robustness trials; generate/admit plans first.

The baseline is simulated and ranked normally, separately from the configured
number of perturbed trials. Every plan receives exactly the same perturbed world
in each trial. The existing engine validates every action, enforces physics,
routes and reservations, and records rejected actions; the original plans are
neither edited nor regenerated to improve trial outcomes. The existing scorer
and viability/ranking rules remain authoritative. Input worlds, plans, policies
and baseline results are not mutated. Trial contracts are frozen, with tuple
collections and frozen nested metrics/audits.

### Configuration and API

`POST /api/v1/simulate-response` accepts an optional `robustness` configuration.
Omitting it or setting `enabled: false` performs no trials, preserves baseline
values and returns a documented `robustness: null` response field. All existing
20-plan/1,440-minute limits and 400/422/500 error behavior remain in place. Invalid
physical plans still produce normal outcomes, not request failures.

Add this member to an existing valid SimulationRequest JSON object:

```json
"robustness": {
  "enabled": true,
  "trial_count": 20,
  "seed": 42,
  "route_closure_shift_minutes": [-15, 15],
  "travel_time_increase_percent": [0, 40],
  "responder_unavailability_count": 1,
  "shelter_capacity_reduction_percent": [0, 40],
  "request_reporting_delay_minutes": [0, 15],
  "additional_request_count": 1
}
```

Defaults are disabled, 20 trials, seed 42, the ranges shown above, **zero**
unavailable responders and **zero** additional requests. Ranges are inclusive
integer pairs `[minimum, maximum]`. Set both endpoints equal for a fixed change.
Trial counts must be 1–100, including disabled configurations; seeds must be
integers from 0 through 2^63−1. Closure shifts are within −15..15 minutes, travel
and capacity percentages within 0..40, and reporting delays within 0..15 minutes.
Unavailability is 0–20 and cannot exceed currently available, unassigned
responders (structured 400 when it does). Additional requests are limited to 0–3.
Unknown fields, coercible strings/booleans, inverted ranges and out-of-bound
values are rejected. No new dependency is required.

### Variations and reproducibility

Each integer draw comes from SHA-256 of compact UTF-8 JSON containing algorithm
version `ark-robustness-v1`, seed, zero-based trial index, category and entity ID;
the hash integer is mapped modulo the inclusive range width. This is a repeatable
sensitivity sampling convention, not a calibrated distribution. Global random
state is unused. Trial IDs are scoped to scenario ID, seed and trial index.
Audits and output plans/reasons are sorted deterministically. Identical inputs
produce identical JSON, independent of submitted plan order.

| Variation | Rule |
|---|---|
| Closure timing | Shift future scheduled closures; clamp to the snapshot minute. Missing/past/already closed routes are audited as skipped. |
| Travel time | Increase durations using exact integer ceiling: `(minutes * (100 + percent) + 99) // 100`. Never faster. |
| Responder availability | Select by stable hashed priority, then mark unavailable. Keep actions intact so existing admission records `responder_unavailable`. |
| Shelter capacity | Floor `capacity * (100 - percent) / 100`, clamped to existing occupancy and the schema minimum of one; record clamps. |
| Reporting delay | Delay pending requests reported at/after the snapshot. Previously reported or non-pending requests are skipped; never move a report earlier. |
| New requests | Add one-person, urgency-four hypothetical cohorts at distinct unused non-safe nodes, reported within the horizon. IDs and provenance are deterministic. |

Additional cohorts are explicitly assumed disjoint from every existing request
and community population. Nodes occupied by any request, community or shelter
are excluded, as are safe nodes. The schema has no individual-person registry,
so this is a conservative synthetic assumption, not verified identity matching.
If no eligible node exists, skip with `no_disjoint_non_safe_node`; ID collisions
are skipped with `synthetic_id_collision`. No populations are cloned or reduced
to fabricate new people. Synthetic provenance lives in the audit and private
world metadata because RescueRequest has no metadata field. The Nepal fixture
has no eligible additional-request nodes, so its requested additions are skipped.

### Interpreting output

The separate `robustness` block includes per-trial audits, terminal per-plan
outcomes, structured action failure/rejection reasons and trial rankings.
Summaries count every completed terminal trial, including failed/cancelled and
nonviable outcomes. They expose viable/nonviable counts, viable-trial fraction,
score ranges/mean/median, rescue/evacuation ranges, worst isolation/unanswered
calls/stranding, reason counts and best/worst numeric trial IDs.

Negative and nonviable scores remain in distributions. Missing numeric scores
remain null with `numeric_score_unavailable`; numeric summaries exclude only
those missing values and become null if none exist. Means and medians use exact
Fraction arithmetic on decimal score representations and convert to floats once.
An even median averages the two middle values. Numeric ties for best/worst trial
use the lexicographically smallest trial ID. Reason counts count events plus
explicit nonviability/missing-score reasons, not unique failed trials.

`robustness_order` is informational: higher viable fraction, then higher median,
higher minimum score, higher baseline score, then ascending plan ID. Missing
scores sort last at the applicable tie-breaker. This never overwrites the normal
`recommended_plan_id`. `first_place_trial_count` uses the existing ranking in each
trial, even if its first plan is nonviable. Recommendation stability is the number
of matched trials where the baseline-recommended plan ranks first divided by
completed matched trials; it is null when no baseline recommendation exists.
High viability alone can coexist with poor rescue/evacuation outcomes: read the
metrics and scores alongside the rate.

### Nepal robustness demo and runtime limits

```powershell
& .\apps\api\.venv\Scripts\python.exe .\apps\api\scripts\run_nepal_robustness_demo.py
```

This explicitly runs 20 matched trials at seed 42 with one responder unavailable
and one attempted synthetic addition per trial. It prints baseline ranks/scores,
trial viability, median/worst score, first-place counts, sensitivity ranking,
recommendation stability and the synthetic-sensitivity disclaimer. Repeated runs
produce identical output. The ordinary Nepal demo remains baseline-only.

Execution is synchronous: cost scales with plans × trials × duration, in addition
to baseline cost. The maximum permits 2,000 trial simulations at 1,440 minutes
each and can be expensive; use small trials for interactive demonstrations.
Audits/outcomes also increase response size. There is no background job system,
model call, timing guarantee or operational approval. Expected action failures
do not stop other plans/trials; unexpected programming errors use the existing
sanitized 500 response.
