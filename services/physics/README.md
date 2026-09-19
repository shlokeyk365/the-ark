# The Arc physics and historical modeling service

This service currently contains the first trained component for The Arc: an
event-level Nepal flood impact prior. It learns from multiple historical flood
records and predicts the probability of casualty reports, housing damage,
transport disruption, and severe reported impact.

It is not yet a street-level inundation model. Flood extent and water depth need
a separate spatial training set built from rainfall, terrain, and satellite
flood masks.

The generated evaluation report includes year-grouped ROC-AUC confidence
intervals, MSE, RMSE, Brier score, log loss, and comparisons against a
fold-specific prevalence baseline. A validation gate labels the current model
`research_only` unless every target reaches ROC-AUC 0.65 and improves on the
baseline MSE.

## Reproduce the model

```bash
PYTHONPATH=services/physics/src python3 -m the_arc_physics.cli \
  ingest-desinventar \
  --source /path/to/DI_export_npl.zip \
  --output data/historical/nepal_flood_events.csv

PYTHONPATH=services/physics/src python3 -m the_arc_physics.cli train \
  --data data/historical/nepal_flood_events.csv \
  --model data/models/nepal_flood_impact_model.json \
  --report data/models/nepal_flood_impact_report.json

PYTHONPATH=services/physics/src python3 -m the_arc_physics.cli \
  evaluate-holdout \
  --model data/models/nepal_flood_impact_model.json \
  --holdout data/holdouts/nakkhu-2024.json \
  --output data/models/nakkhu_2024_holdout_report.json
```

## Run tests

```bash
PYTHONPATH=services/physics/src python3 -m unittest discover \
  -s services/physics/tests -v
```
