"""Training, grouped cross-validation, and locked-holdout evaluation."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Dict, List, Mapping, Sequence

import numpy as np

from .features import EventInput, FeatureEncoder, event_inputs
from .geography import normalize_district
from .logistic import BinaryLogisticRegression
from .metrics import binary_metrics, grouped_roc_auc_interval
from .model import MultiLabelFloodImpactModel
from .records import FloodEventRecord, TARGET_NAMES, validate_training_records


def train_and_evaluate(
    records: Sequence[FloodEventRecord],
    model_path: Path,
    report_path: Path,
    folds: int = 5,
) -> Mapping[str, Any]:
    validate_training_records(records)
    cross_validation = grouped_cross_validation(records, folds=folds, grouping="year")
    district_generalization = grouped_cross_validation(
        records, folds=folds, grouping="district"
    )
    validation_gate = combined_validation_gate(
        cross_validation, district_generalization
    )
    model = MultiLabelFloodImpactModel.fit(records)
    model.training_metadata = {
        **model.training_metadata,
        "feature_policy": "city and district identity excluded from predictors",
        "validation_gate": validation_gate,
    }
    model.save(model_path)
    report = {
        "model_purpose": "Historical event-level flood impact prior",
        "not_a_flood_extent_model": True,
        "training": dict(model.training_metadata),
        "cross_validation": cross_validation,
        "district_generalization": district_generalization,
        "validation_gate": validation_gate,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def grouped_cross_validation(
    records: Sequence[FloodEventRecord],
    folds: int = 5,
    grouping: str = "year",
    classifier_factory: Callable[[], Any] = BinaryLogisticRegression,
    model_name: str = "logistic_regression",
) -> Mapping[str, Any]:
    if folds < 2:
        raise ValueError("at least two folds are required")
    fold_reports: List[Mapping[str, Any]] = []
    out_of_fold = {
        target: np.full(len(records), np.nan, dtype=float) for target in TARGET_NAMES
    }
    baseline_out_of_fold = {
        target: np.full(len(records), np.nan, dtype=float) for target in TARGET_NAMES
    }

    fold_assignments = _fold_assignments(records, folds, grouping)
    if len(set(fold_assignments)) != folds:
        raise ValueError(
            f"{grouping}-grouped validation needs at least one group in every fold"
        )
    for fold in range(folds):
        test_indices = [
            index for index, assigned_fold in enumerate(fold_assignments)
            if assigned_fold == fold
        ]
        train_indices = [index for index in range(len(records)) if index not in test_indices]
        train_records = [records[index] for index in train_indices]
        test_records = [records[index] for index in test_indices]
        encoder = FeatureEncoder.fit(event_inputs(train_records))
        train_matrix = encoder.transform(event_inputs(train_records))
        test_matrix = encoder.transform(event_inputs(test_records))
        target_metrics: Dict[str, Any] = {}

        for target in TARGET_NAMES:
            train_known_positions = [
                index
                for index, record in enumerate(train_records)
                if record.target_known[target]
            ]
            test_known_positions = [
                index
                for index, record in enumerate(test_records)
                if record.target_known[target]
            ]
            train_labels = np.asarray(
                [train_records[index].targets[target] for index in train_known_positions],
                dtype=float,
            )
            test_labels = np.asarray(
                [test_records[index].targets[target] for index in test_known_positions],
                dtype=float,
            )
            classifier = classifier_factory().fit(
                train_matrix[train_known_positions], train_labels
            )
            probabilities = np.asarray(
                classifier.predict_proba(test_matrix[test_known_positions])
            )
            if probabilities.ndim == 2:
                probabilities = probabilities[:, 1]
            target_metrics[target] = binary_metrics(test_labels, probabilities)
            baseline_probability = float(np.mean(train_labels))
            for position, probability in zip(test_known_positions, probabilities):
                record_index = test_indices[position]
                out_of_fold[target][record_index] = probability
                baseline_out_of_fold[target][record_index] = baseline_probability

        fold_reports.append(
            {
                "fold": fold,
                "training_events": len(train_records),
                "validation_events": len(test_records),
                "validation_years": sorted({record.year for record in test_records}),
                "validation_districts": sorted(
                    {record.district for record in test_records}
                ),
                "metrics": target_metrics,
            }
        )

    overall: Dict[str, Any] = {}
    bootstrap_groups = [
        normalize_district(record.district)
        if grouping == "district"
        else record.year
        for record in records
    ]
    for target in TARGET_NAMES:
        known = np.asarray(
            [record.target_known[target] for record in records], dtype=bool
        )
        labels = np.asarray(
            [record.targets[target] for record in records], dtype=float
        )[known]
        probabilities = out_of_fold[target][known]
        baseline_probabilities = baseline_out_of_fold[target][known]
        if np.any(np.isnan(probabilities)) or np.any(np.isnan(baseline_probabilities)):
            raise RuntimeError(f"missing out-of-fold predictions for {target}")
        model_metrics = binary_metrics(labels, probabilities)
        baseline_metrics = binary_metrics(labels, baseline_probabilities)
        interval = grouped_roc_auc_interval(
            labels,
            probabilities,
            np.asarray(bootstrap_groups)[known].tolist(),
        )
        model_mse = float(model_metrics["mse"])
        baseline_mse = float(baseline_metrics["mse"])
        mse_skill = (
            1.0 - model_mse / baseline_mse if baseline_mse > 0.0 else 0.0
        )
        auc = model_metrics["roc_auc"]
        lower_auc = interval["lower"]
        beats_random_auc = bool(lower_auc is not None and lower_auc > 0.5)
        beats_prevalence_mse = model_mse < baseline_mse
        overall[target] = {
            **model_metrics,
            "roc_auc_95_percent_ci": interval,
            "auc_lift_over_random": (
                round(float(auc) - 0.5, 4) if auc is not None else None
            ),
            "prevalence_baseline": baseline_metrics,
            "mse_skill_vs_prevalence": round(mse_skill, 4),
            "signal_assessment": {
                "beats_random_auc_with_95_percent_confidence": beats_random_auc,
                "beats_prevalence_baseline_mse": beats_prevalence_mse,
                "not_guessing": beats_random_auc and beats_prevalence_mse,
            },
        }
    overall["macro_f1"] = round(mean(overall[target]["f1"] for target in TARGET_NAMES), 4)
    overall["mean_accuracy"] = round(
        mean(overall[target]["accuracy"] for target in TARGET_NAMES), 4
    )
    valid_aucs = [
        overall[target]["roc_auc"]
        for target in TARGET_NAMES
        if overall[target]["roc_auc"] is not None
    ]
    overall["macro_roc_auc"] = round(mean(valid_aucs), 4)
    overall["mean_rmse"] = round(
        mean(overall[target]["rmse"] for target in TARGET_NAMES), 4
    )
    target_gates = {
        target: {
            "roc_auc_at_least_0_65": bool(
                overall[target]["roc_auc"] is not None
                and overall[target]["roc_auc"] >= 0.65
            ),
            "positive_mse_skill": overall[target]["mse_skill_vs_prevalence"] > 0.0,
            "passes": bool(
                overall[target]["roc_auc"] is not None
                and overall[target]["roc_auc"] >= 0.65
                and overall[target]["mse_skill_vs_prevalence"] > 0.0
            ),
        }
        for target in TARGET_NAMES
    }
    validation_gate = {
        "deployment_ready": all(value["passes"] for value in target_gates.values()),
        "status": (
            "validated" if all(value["passes"] for value in target_gates.values())
            else "research_only"
        ),
        "policy": (
            "Every target must have year-grouped ROC-AUC >= 0.65 and lower MSE "
            "than a fold-specific prevalence baseline."
        ),
        "targets": target_gates,
    }
    return {
        "model": model_name,
        "grouping": grouping,
        "strategy": (
            f"grouped by complete {grouping}; no random row split and no "
            "city/district identity predictor"
        ),
        "baseline_strategy": (
            "Each validation event receives only its training fold's target prevalence."
        ),
        "folds": fold_reports,
        "overall": overall,
        "validation_gate": validation_gate,
    }


def combined_validation_gate(
    year_report: Mapping[str, Any],
    district_report: Mapping[str, Any],
) -> Mapping[str, Any]:
    targets = {}
    for target in TARGET_NAMES:
        year_metrics = year_report["overall"][target]
        district_metrics = district_report["overall"][target]
        passes = bool(
            year_metrics["roc_auc"] >= 0.65
            and district_metrics["roc_auc"] >= 0.65
            and year_metrics["mse_skill_vs_prevalence"] > 0.0
            and district_metrics["mse_skill_vs_prevalence"] > 0.0
        )
        targets[target] = {
            "year_grouped_roc_auc": year_metrics["roc_auc"],
            "district_grouped_roc_auc": district_metrics["roc_auc"],
            "positive_mse_skill_in_both": bool(
                year_metrics["mse_skill_vs_prevalence"] > 0.0
                and district_metrics["mse_skill_vs_prevalence"] > 0.0
            ),
            "passes": passes,
        }
    ready = all(value["passes"] for value in targets.values())
    return {
        "deployment_ready": ready,
        "status": "validated" if ready else "research_only",
        "policy": (
            "Every target must achieve ROC-AUC >= 0.65 and positive MSE skill "
            "in both year-held-out and district-held-out evaluation."
        ),
        "targets": targets,
    }


def _fold_assignments(
    records: Sequence[FloodEventRecord], folds: int, grouping: str
) -> List[int]:
    if grouping not in {"year", "district"}:
        raise ValueError("grouping must be 'year' or 'district'")
    if grouping == "year":
        return [record.year % folds for record in records]

    group_counts: Dict[str, int] = {}
    for record in records:
        district = normalize_district(record.district)
        group_counts[district] = group_counts.get(district, 0) + 1
    fold_sizes = [0] * folds
    group_to_fold = {}
    ordered_groups = sorted(
        group_counts,
        key=lambda value: (
            -group_counts[value],
            hashlib.sha256(value.encode("utf-8")).hexdigest(),
        ),
    )
    for group in ordered_groups:
        fold = min(range(folds), key=lambda value: (fold_sizes[value], value))
        group_to_fold[group] = fold
        fold_sizes[fold] += group_counts[group]
    return [group_to_fold[normalize_district(record.district)] for record in records]


def evaluate_locked_holdout(
    model: MultiLabelFloodImpactModel,
    holdout_path: Path,
) -> Mapping[str, Any]:
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    if not holdout.get("locked", False):
        raise ValueError("holdout must be explicitly marked as locked")
    event = EventInput(**holdout["model_input"])
    probabilities = model.predict(event)
    actual = holdout["actual_labels"]
    component_results = {}
    correct = 0
    squared_errors = []
    for target in TARGET_NAMES:
        predicted_label = int(probabilities[target] >= 0.5)
        actual_label = int(bool(actual[target]))
        correct += int(predicted_label == actual_label)
        squared_errors.append((probabilities[target] - actual_label) ** 2)
        component_results[target] = {
            "probability": probabilities[target],
            "predicted_label": predicted_label,
            "actual_label": actual_label,
            "correct": predicted_label == actual_label,
        }
    return {
        "holdout_id": holdout["event_id"],
        "classification_accuracy_percent": round(100.0 * correct / len(TARGET_NAMES), 2),
        "probabilistic_match_percent": round(
            100.0 * (1.0 - float(np.mean(squared_errors))), 2
        ),
        "mean_squared_error": round(float(np.mean(squared_errors)), 4),
        "root_mean_squared_error": round(
            float(np.sqrt(np.mean(squared_errors))), 4
        ),
        "roc_auc": None,
        "roc_auc_note": (
            "ROC-AUC is undefined for one event whose four observed labels are all positive."
        ),
        "components": component_results,
        "interpretation": (
            "This evaluates event-level impact categories. It does not measure "
            "street-level flood extent or prove counterfactual rescue outcomes."
        ),
    }
