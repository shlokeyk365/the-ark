# Ark API

One modular FastAPI application on Python 3.12. From this directory:

```powershell
uv sync --locked
uv run uvicorn ark_api.main:app --reload
```

`GET /health` returns `{"status":"ok","service":"ark-api"}`. No simulation
endpoint or execution engine is implemented yet.

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
- These contracts do not authorize actions or calculate physics, movement,
  scoring, or decisions. Future execution must deterministically validate every
  action against authoritative physics state, regardless of decision provider.
  Model construction checks are not a replacement for that execution boundary.
- Enum vocabularies are an initial contract, not an imported external schema.
  Plans and assignments are not resolved against the world in this step.

`tests/conftest.py` supplies a generic two-node world with every entity type for
future tests. Framework behavior follows the official
[Pydantic validation documentation](https://docs.pydantic.dev/latest/concepts/strict_mode/)
and [uv project workflow](https://docs.astral.sh/uv/concepts/projects/sync/).
