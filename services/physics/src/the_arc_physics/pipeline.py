"""Training, grouped cross-validation, and locked-holdout evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np

from .features import EventInput, FeatureEncoder, event_inputs
from .logistic import BinaryLogisticRegression
from .metrics import binary_metrics
from .model import MultiLabelFloodImpactModel
from .records import FloodEventRecord, TARGET_NAMES, validate_training_records


def train_and_evaluate(
    records: Sequence[FloodEventRecord],
    model_path: Path,
    report_path: Path,
    folds: int = 5,
) -> Mapping[str, Any]:
    validate_training_records(records)
    cross_validation = grouped_cross_validation(records, folds=folds)
    model = MultiLabelFloodImpactModel.fit(records)
    model.save(model_path)
    report = {
        "model_purpose": "Historical event-level flood impact prior",
        "not_a_flood_extent_model": True,
        "training": dict(model.training_metadata),
        "cross_validation": cross_validation,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def grouped_cross_validation(
    records: Sequence[FloodEventRecord],
    folds: int = 5,
) -> Mapping[str, Any]:
    if folds < 2:
        raise ValueError("at least two folds are required")
    fold_reports: List[Mapping[str, Any]] = []
    out_of_fold = {
        target: np.zeros(len(records), dtype=float) for target in TARGET_NAMES
    }

    for fold in range(folds):
        test_indices = [
            index for index, record in enumerate(records) if record.year % folds == fold
        ]
        train_indices = [index for index in range(len(records)) if index not in test_indices]
        train_records = [records[index] for index in train_indices]
        test_records = [records[index] for index in test_indices]
        encoder = FeatureEncoder.fit(event_inputs(train_records))
        train_matrix = encoder.transform(event_inputs(train_records))
        test_matrix = encoder.transform(event_inputs(test_records))
        target_metrics: Dict[str, Any] = {}

        for target in TARGET_NAMES:
            train_labels = np.asarray(
                [record.targets[target] for record in train_records], dtype=float
            )
            test_labels = np.asarray(
                [record.targets[target] for record in test_records], dtype=float
            )
            classifier = BinaryLogisticRegression().fit(train_matrix, train_labels)
            probabilities = classifier.predict_proba(test_matrix)
            target_metrics[target] = binary_metrics(test_labels, probabilities)
            for index, probability in zip(test_indices, probabilities):
                out_of_fold[target][index] = probability

        fold_reports.append(
            {
                "fold": fold,
                "training_events": len(train_records),
                "validation_events": len(test_records),
                "validation_years": sorted({record.year for record in test_records}),
                "metrics": target_metrics,
            }
        )

    overall: Dict[str, Any] = {}
    for target in TARGET_NAMES:
        labels = np.asarray([record.targets[target] for record in records], dtype=float)
        overall[target] = binary_metrics(labels, out_of_fold[target])
    overall["macro_f1"] = round(mean(overall[target]["f1"] for target in TARGET_NAMES), 4)
    overall["mean_accuracy"] = round(
        mean(overall[target]["accuracy"] for target in TARGET_NAMES), 4
    )
    return {
        "strategy": "grouped by complete event year; no random row split",
        "folds": fold_reports,
        "overall": overall,
    }


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
        "components": component_results,
        "interpretation": (
            "This evaluates event-level impact categories. It does not measure "
            "street-level flood extent or prove counterfactual rescue outcomes."
        ),
    }

