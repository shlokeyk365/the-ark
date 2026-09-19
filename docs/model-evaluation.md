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

- cross-validated accuracy, precision, recall, F1, and Brier score for each
  impact label;
- macro F1 across labels;
- classification accuracy on the locked Nakkhu label set; and
- a probability-sensitive holdout match score.

These metrics must be identified as event-level impact metrics. They do not
measure flood extent, water depth, road-level arrival time, or the truth of a
counterfactual response plan.

## Required spatial model

A later flood-extent model requires multiple historical events with aligned:

- pre-event rainfall and river observations;
- terrain, slope, drainage, and land-cover features;
- satellite-derived flood and non-flood cell labels; and
- complete-event train/validation splits.

The 2024 UNOSAT Nakkhu/Kathmandu flood extent remains evaluation-only.
