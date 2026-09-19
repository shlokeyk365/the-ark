# Flood model evaluation

The September 2024 Nakkhu event is a locked holdout. Its known outcomes are not
permitted in training, feature selection, threshold selection, or tuning.

## Current trained component

The first trained component is a multi-label event impact prior based on 3,953
historical Nepal flood records. It predicts probabilities for:

- casualty or missing person reports;
- housing damage;
- transport disruption; and
- severe reported impact.

Cross-validation groups complete years into folds. Random row splits are not
used because events from the same flood season can otherwise leak into both
training and validation.

## Accuracy language

The generated report contains:

- cross-validated ROC-AUC with year-grouped 95% bootstrap intervals;
- MSE, RMSE, Brier score, log loss, average precision, accuracy, precision,
  recall, and F1 for each impact label;
- a leakage-safe baseline that predicts only the training fold's prevalence;
- MSE skill relative to that baseline and an explicit `not_guessing` result;
- macro F1 across labels;
- classification accuracy on the locked Nakkhu label set; and
- a probability-sensitive holdout match score.

These metrics must be identified as event-level impact metrics. They do not
measure flood extent, water depth, road-level arrival time, or the truth of a
counterfactual response plan.

## Current result

The current metadata-only model is not deployment-ready. Its year-grouped
macro ROC-AUC is 0.5957, where 0.5 is random ranking and 1.0 is perfect. The
per-target results are:

| Target | ROC-AUC | 95% interval | MSE | RMSE | MSE skill vs baseline | Signal assessment |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Casualty or missing | 0.6258 | 0.5915–0.6654 | 0.2155 | 0.4642 | 0.0345 | weak signal |
| Housing damage | 0.5806 | 0.5226–0.6519 | 0.2451 | 0.4951 | 0.0125 | weak signal |
| Transport disruption | 0.6322 | 0.5793–0.6843 | 0.0703 | 0.2651 | 0.0195 | weak signal |
| Severe impact | 0.5442 | 0.4712–0.6228 | 0.2306 | 0.4802 | -0.0087 | no demonstrated signal |

The first three targets beat both random-ranking and prevalence-error checks,
but only slightly. Severe impact fails both checks. The validation gate requires
every target to reach ROC-AUC 0.65 and positive MSE skill, so the model is marked
`research_only`. An AUC close to 1 is not expected from month, region, district,
and cause metadata; a value that high here would warrant a leakage audit.

MSE and Brier score are the same quantity for binary probabilistic predictions.
Lower is better for MSE/RMSE/Brier; higher is better for ROC-AUC and MSE skill.
The 0.5 classification threshold is intentionally not tuned on the Nakkhu
holdout.

## Required spatial model

A later flood-extent model requires multiple historical events with aligned:

- pre-event rainfall and river observations;
- terrain, slope, drainage, and land-cover features;
- satellite-derived flood and non-flood cell labels; and
- complete-event train/validation splits.

The 2024 UNOSAT Nakkhu/Kathmandu flood extent remains evaluation-only.
