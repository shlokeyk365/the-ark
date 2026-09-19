# Flood model evaluation

The September 2024 Nakkhu event is a locked holdout. Its known outcomes are not
used in training, feature selection, model selection, threshold selection, or
tuning. The 0.5 classification threshold is unchanged after evaluation.

## Training unit and features

The model learns from 4,869 location-level flood episodes spanning 1971–2023,
consolidated from 5,349 DesInventar and BIPAD reports. Consolidation prevents a
municipality-day with many administrative reports from receiving disproportionate
training weight.

Predictors include date, coordinates, rainfall, census exposure, district-scale
terrain, local elevation/relief, level-6 catchment characteristics, river
proximity, long-term discharge, and river order. City, district, basin ID, and
data-source identity are excluded from predictors.

The severe-impact definition was harmonized across sources to use deaths or
missing people, or at least 10 damaged homes. BIPAD's uniformly zero
`people_affected` field no longer creates a source-dependent target definition.

## Evaluation design

Every candidate is evaluated four ways:

1. complete years held out;
2. complete normalized districts held out;
3. complete HydroBASINS level-6 catchments held out; and
4. complete four-day nationwide storm windows held out.

The fourth split prevents reports from the same storm in different cities from
appearing in training and validation. Each result is compared with a baseline
that knows only the training fold's label prevalence. Unknown labels are
excluded per target.

## Model selection

Selection maximizes mean macro ROC-AUC across all four split strategies while
requiring mean RMSE to remain within 2% of logistic regression.

| Candidate | Mean macro ROC-AUC | Mean RMSE |
| --- | ---: | ---: |
| Logistic regression | 0.6320 | 0.4258 |
| Histogram gradient boosting | 0.6613 | 0.4219 |
| Random forest | 0.6649 | 0.4184 |
| Extra Trees | 0.6625 | 0.4190 |
| **CatBoost** | **0.6760** | **0.4166** |
| Soft-voting ensemble | 0.6738 | 0.4170 |

Two additional CatBoost configurations were tested but did not beat the
selected configuration. Basin-wide rainfall summaries were also excluded after
an ablation reduced mean AUC from 0.6760 to 0.6724.

## Selected CatBoost results

| Target | Year AUC | District AUC | Basin AUC | Storm AUC |
| --- | ---: | ---: | ---: | ---: |
| Casualty or missing | 0.6570 | 0.7075 | 0.6941 | 0.6955 |
| Housing damage | 0.6278 | 0.6838 | 0.6888 | 0.6554 |
| Transport disruption | 0.6548 | 0.7213 | 0.6882 | 0.6907 |
| Severe impact | 0.6333 | 0.6824 | 0.6791 | 0.6561 |
| **Macro** | **0.6432** | **0.6987** | **0.6875** | **0.6744** |

Mean RMSE is 0.4237 for years, 0.4118 for districts, 0.4134 for basins,
and 0.4174 for storms. Every target has positive MSE skill in every split and
passes the report's non-guessing check. That is meaningful improvement, but it
is not close enough to 0.80 to claim operational reliability.

The deployment gate requires every target to reach ROC-AUC 0.65 and positive
MSE skill in every split. Housing and severe impact miss the unseen-year AUC
requirement, so status remains `research_only`.

## Corrected Nakkhu location and locked result

The prior scenario coordinate was incorrect: it produced a local elevation of
1,963 m. The corrected Kantipur Colony coordinate is approximately
27.64646, 85.31348, with sampled local elevation 1,302 m and a mapped river
distance of about 26 m. This factual correction was made before final model
selection.

After the model was frozen, its one-time Nakkhu result was:

- fixed 0.5-threshold accuracy: 0% (0 of 4 labels);
- probability-sensitive match: 53.43%;
- MSE: 0.4657; and
- RMSE: 0.6825.

ROC-AUC is undefined because this is one event and all four observed labels are
positive. The result is not used to change thresholds or retrain the model.
It shows that stronger general historical ranking does not yet capture the
severity of this particular extreme urban-river event.

## Remaining route toward 0.80

The next material inputs are event-time river stage/discharge and rate of rise,
sub-daily upstream rainfall, street-scale height above drainage, building and
road exposure, and satellite-derived flood masks. Additional tuning of the
current administrative-report model is unlikely to close that gap honestly.
