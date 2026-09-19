# Generated model artifacts

- `nepal_flood_model_benchmark.json`: results for six model families under
  unseen-year, unseen-district, unseen-basin, and unseen-storm validation. The
  Nakkhu holdout is not used in selection.
- `nepal_flood_impact_selected.pkl.gz`: selected CatBoost model used by the
  simulation integration. Only load this pickle from the trusted repository.
- `nepal_flood_impact_selected.pkl.manifest.json`: inspectable encoder,
  provenance, feature policy, and validation-gate metadata.
- `nepal_flood_impact_model.json`: transparent logistic-regression baseline.
- `nepal_flood_impact_report.json`: complete baseline evaluation report.
- `nakkhu_2024_holdout_report.json`: locked September 2024 Nakkhu evaluation.

The selected model remains `research_only`. All 16 target/split combinations
have positive MSE skill over a fold-specific prevalence baseline, but housing
and severe-impact prediction do not reach ROC-AUC 0.65 in unseen-year testing.
