"""Compare model families without consulting the locked 2024 holdout."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Mapping, Sequence

from .candidates import classifier_factories
from .pipeline import grouped_cross_validation
from .records import FloodEventRecord


def benchmark_models(
    records: Sequence[FloodEventRecord],
    output_path: Path,
    folds: int = 5,
) -> Mapping[str, Any]:
    candidates: Dict[str, Any] = {}
    for name, factory in classifier_factories().items():
        by_year = grouped_cross_validation(
            records,
            folds=folds,
            grouping="year",
            classifier_factory=factory,
            model_name=name,
        )
        by_district = grouped_cross_validation(
            records,
            folds=folds,
            grouping="district",
            classifier_factory=factory,
            model_name=name,
        )
        by_basin = grouped_cross_validation(
            records,
            folds=folds,
            grouping="basin",
            classifier_factory=factory,
            model_name=name,
        )
        by_storm = grouped_cross_validation(
            records,
            folds=folds,
            grouping="storm",
            classifier_factory=factory,
            model_name=name,
        )
        candidates[name] = {
            "year_grouped": by_year,
            "district_grouped": by_district,
            "basin_grouped": by_basin,
            "storm_grouped": by_storm,
            "selection_summary": {
                "mean_macro_roc_auc": round(
                    mean(
                        report["overall"]["macro_roc_auc"]
                        for report in (by_year, by_district, by_basin, by_storm)
                    ),
                    4,
                ),
                "mean_rmse": round(
                    mean(
                        report["overall"]["mean_rmse"]
                        for report in (by_year, by_district, by_basin, by_storm)
                    ),
                    4,
                ),
            },
        }

    logistic_rmse = candidates["logistic_regression"]["selection_summary"][
        "mean_rmse"
    ]
    eligible = [
        name
        for name, report in candidates.items()
        if report["selection_summary"]["mean_rmse"] <= logistic_rmse * 1.02
    ]
    selected = max(
        eligible,
        key=lambda name: candidates[name]["selection_summary"][
            "mean_macro_roc_auc"
        ],
    )
    report = {
        "holdout_used_for_selection": False,
        "feature_policy": "city and district identity excluded from predictors",
        "selection_rule": (
            "Highest mean of year-, district-, basin-, and storm-grouped macro "
            "ROC-AUC among "
            "candidates whose mean RMSE is within 2% of logistic regression."
        ),
        "selected_model": selected,
        "candidates": candidates,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
