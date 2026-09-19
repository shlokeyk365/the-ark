# Generated model artifacts

- `nepal_flood_model_benchmark.json`: year-held-out and district-held-out
  results for logistic regression, histogram gradient boosting, random forest,
  extra trees, CatBoost, and the soft-voting ensemble. The Nakkhu holdout was
  not used to select the winner.
- `nepal_flood_impact_ensemble.pkl.gz`: selected fitted ensemble used by the
  simulation integration. Only load this pickle from the trusted repository.
- `nepal_flood_impact_ensemble.pkl.manifest.json`: inspectable model type,
  encoder, training data, holdout policy, and validation-gate metadata.
- `nepal_flood_impact_model.json`: transparent logistic-regression baseline.
- `nepal_flood_impact_report.json`: full baseline cross-validation report.
- `nakkhu_2024_holdout_report.json`: one-time evaluation of the selected model
  against the locked September 2024 Nakkhu outcomes.

The selected model remains `research_only`. It beats the fold-specific
prevalence MSE baseline for every target in both split strategies, but it does
not meet the gate requiring every target to achieve ROC-AUC of at least 0.65 in
both unseen-year and unseen-district evaluation.
