# The Arc physics and historical modeling service

This service contains The Arc's event-level Nepal flood impact prior. It learns
from 5,349 historical flood records spanning 1971–2023 and predicts the
probability of casualty reports, housing damage, transport disruption, and
severe reported impact.

It is not yet a street-level inundation model. Flood extent and water depth need
a separate spatial training set built from rainfall, terrain, and satellite
flood masks.

The predictor matrix uses coordinates, terrain, census exposure, rainfall,
month, region, and reported cause. City and district identity are excluded.
Evaluation holds out complete years and, separately, complete districts. A
validation gate labels the current model `research_only` unless every target
reaches ROC-AUC 0.65 and improves on baseline MSE under both tests.

## Reproduce the model

```bash
PYTHONPATH=services/physics/src .venv/bin/python -m the_arc_physics.cli benchmark \
  --data data/historical/nepal_flood_events_enriched.csv \
  --output data/models/nepal_flood_model_benchmark.json

PYTHONPATH=services/physics/src .venv/bin/python -m the_arc_physics.cli \
  train-ensemble \
  --data data/historical/nepal_flood_events_enriched.csv \
  --benchmark data/models/nepal_flood_model_benchmark.json \
  --model data/models/nepal_flood_impact_ensemble.pkl.gz

PYTHONPATH=services/physics/src .venv/bin/python -m the_arc_physics.cli train \
  --data data/historical/nepal_flood_events_enriched.csv \
  --model data/models/nepal_flood_impact_model.json \
  --report data/models/nepal_flood_impact_report.json

PYTHONPATH=services/physics/src .venv/bin/python -m the_arc_physics.cli \
  evaluate-holdout \
  --model data/models/nepal_flood_impact_ensemble.pkl.gz \
  --holdout data/holdouts/nakkhu-2024.json \
  --output data/models/nakkhu_2024_holdout_report.json
```

## Run tests

```bash
PYTHONPATH=services/physics/src .venv/bin/python -m unittest discover \
  -s services/physics/tests -v
```
