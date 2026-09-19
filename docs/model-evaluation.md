# Flood model evaluation

The September 2024 Nakkhu event is a locked holdout. Its known outcomes were
not used in training, feature selection, model selection, threshold selection,
or tuning.

## What the model predicts

The trained component is an event-level impact prior learned from 5,349 Nepal
flood records spanning 1971–2023. It predicts probabilities for:

- casualty or missing-person reports;
- housing damage;
- transport disruption; and
- severe reported impact.

The inputs combine event date and cause with coordinates, district-scale
terrain, 2011 census exposure, and antecedent rainfall. City and district names
are deliberately excluded from the predictor matrix so the model cannot simply
memorize a place's historical rate.

## Evaluation design

Two complementary grouped tests are used:

1. **Unseen years:** complete years are held out, testing temporal transfer.
2. **Unseen districts:** complete normalized districts are held out, testing
   whether the model transfers to places it did not train on.

Each validation event is also compared with a leakage-safe baseline that knows
only its training fold's target prevalence. Unknown target labels are excluded
per target. Model selection uses the mean of the two macro ROC-AUC scores,
subject to mean RMSE staying within 2% of logistic regression. Nakkhu is never
part of that selection.

## Selected model

The soft-voting ensemble combines logistic regression, Extra Trees, and
CatBoost. It had the strongest allowed selection score:

| Candidate | Mean macro ROC-AUC | Mean RMSE |
| --- | ---: | ---: |
| Logistic regression | 0.6271 | 0.4211 |
| Histogram gradient boosting | 0.6324 | 0.4241 |
| Random forest | 0.6310 | 0.4206 |
| Extra Trees | 0.6379 | 0.4193 |
| CatBoost | 0.6402 | 0.4194 |
| **Soft-voting ensemble** | **0.6471** | **0.4168** |

The selected model's detailed results are:

| Target | Unseen-year AUC | Year RMSE | Year MSE skill | Unseen-district AUC | District RMSE | District MSE skill |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Casualty or missing | 0.6227 | 0.4678 | 0.0495 | 0.6591 | 0.4607 | 0.0713 |
| Housing damage | 0.6276 | 0.4734 | 0.0736 | 0.6842 | 0.4576 | 0.1246 |
| Transport disruption | 0.6384 | 0.2644 | 0.0251 | 0.6918 | 0.2622 | 0.0378 |
| Severe impact | 0.6083 | 0.4783 | 0.0447 | 0.6450 | 0.4703 | 0.0772 |

Macro ROC-AUC is 0.6242 for unseen years and 0.6700 for unseen districts. All
eight target/split checks have positive MSE skill over the prevalence baseline,
so the model is learning real but modest signal rather than merely replaying
the common class. The unseen-district score is encouraging for transfer to
other cities; the weaker unseen-year score is the more important warning.

The deployment gate requires every target to reach ROC-AUC 0.65 and positive
MSE skill in both split strategies. The model therefore remains
`research_only`. AUC values close to 1 would be implausible with these coarse
event-level inputs and would trigger a leakage audit, not confidence.

MSE and Brier score are the same quantity for binary probabilistic predictions.
Lower is better for MSE/RMSE/Brier; higher is better for ROC-AUC and MSE skill.

## Locked Nakkhu result

After selection was frozen, the selected ensemble was evaluated once on the
four known Nakkhu impact categories:

- fixed 0.5-threshold accuracy: 50% (2 of 4 labels);
- probability-sensitive match: 61.70%;
- MSE: 0.3830; and
- RMSE: 0.6188.

ROC-AUC is undefined for this single event because all four observed labels are
positive. This result is not a reason to retune on Nakkhu; doing that would
destroy its value as a holdout.

## What this does not validate

These are event-level impact metrics. They do not measure street-level flood
extent, water depth, road-level arrival time, or the truth of a counterfactual
rescue plan. A spatial inundation model still needs multiple historical events
with aligned river observations, terrain/drainage features, and satellite
flood/non-flood cell labels, evaluated using complete-event spatial holdouts.
