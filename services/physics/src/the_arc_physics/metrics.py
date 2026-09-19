"""Transparent probabilistic classification metrics.

The implementation intentionally stays dependency-light so the evaluation can
be reproduced with only NumPy.  Metrics are calculated from out-of-fold
predictions by the pipeline, never from predictions on the fitted training set.
"""

from __future__ import annotations

from math import sqrt
from typing import Any, Dict, Optional, Sequence

import numpy as np


def binary_metrics(labels: np.ndarray, probabilities: np.ndarray) -> Dict[str, Any]:
    labels = np.asarray(labels, dtype=float)
    probabilities = np.asarray(probabilities, dtype=float)
    if labels.ndim != 1 or probabilities.ndim != 1:
        raise ValueError("labels and probabilities must be one-dimensional")
    if len(labels) != len(probabilities) or len(labels) == 0:
        raise ValueError("labels and probabilities must have the same non-zero length")
    if np.any((probabilities < 0.0) | (probabilities > 1.0)):
        raise ValueError("probabilities must be between zero and one")

    predicted = probabilities >= 0.5
    actual = labels >= 0.5
    true_positive = int(np.sum(predicted & actual))
    true_negative = int(np.sum(~predicted & ~actual))
    false_positive = int(np.sum(predicted & ~actual))
    false_negative = int(np.sum(~predicted & actual))
    precision = _divide(true_positive, true_positive + false_positive)
    recall = _divide(true_positive, true_positive + false_negative)
    f1 = _divide(2.0 * precision * recall, precision + recall)
    mse = float(np.mean((probabilities - labels) ** 2))
    clipped = np.clip(probabilities, 1e-15, 1.0 - 1e-15)
    log_loss = -float(
        np.mean(labels * np.log(clipped) + (1.0 - labels) * np.log(1.0 - clipped))
    )
    return {
        "accuracy": round(_divide(true_positive + true_negative, len(labels)), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "roc_auc": _round_optional(roc_auc(labels, probabilities)),
        "average_precision": _round_optional(average_precision(labels, probabilities)),
        "mse": round(mse, 4),
        "rmse": round(sqrt(mse), 4),
        "brier": round(mse, 4),
        "log_loss": round(log_loss, 4),
        "support": int(len(labels)),
        "positive_rate": round(float(np.mean(labels)), 4),
    }


def roc_auc(labels: np.ndarray, probabilities: np.ndarray) -> Optional[float]:
    """Return tie-aware ROC-AUC, or ``None`` if only one class is present."""

    labels = np.asarray(labels, dtype=float) >= 0.5
    probabilities = np.asarray(probabilities, dtype=float)
    positives = int(np.sum(labels))
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None

    order = np.argsort(probabilities, kind="mergesort")
    sorted_probabilities = probabilities[order]
    ranks = np.empty(len(probabilities), dtype=float)
    start = 0
    while start < len(probabilities):
        stop = start + 1
        while (
            stop < len(probabilities)
            and sorted_probabilities[stop] == sorted_probabilities[start]
        ):
            stop += 1
        average_rank = ((start + 1) + stop) / 2.0
        ranks[order[start:stop]] = average_rank
        start = stop

    positive_rank_sum = float(np.sum(ranks[labels]))
    return (positive_rank_sum - positives * (positives + 1) / 2.0) / (
        positives * negatives
    )


def average_precision(
    labels: np.ndarray, probabilities: np.ndarray
) -> Optional[float]:
    """Return average precision (area under the step-wise precision/recall curve)."""

    actual = np.asarray(labels, dtype=float) >= 0.5
    probabilities = np.asarray(probabilities, dtype=float)
    positives = int(np.sum(actual))
    if positives == 0:
        return None
    order = np.argsort(-probabilities, kind="mergesort")
    sorted_actual = actual[order]
    sorted_probabilities = probabilities[order]
    true_positives = np.cumsum(sorted_actual)
    score_changes = np.r_[
        sorted_probabilities[1:] != sorted_probabilities[:-1], True
    ]
    threshold_indices = np.flatnonzero(score_changes)
    precision = true_positives[threshold_indices] / (threshold_indices + 1)
    recall = true_positives[threshold_indices] / positives
    recall_increase = np.diff(np.r_[0.0, recall])
    return float(np.sum(recall_increase * precision))


def grouped_roc_auc_interval(
    labels: np.ndarray,
    probabilities: np.ndarray,
    groups: Sequence[int],
    iterations: int = 1000,
    seed: int = 20240928,
) -> Dict[str, Any]:
    """Bootstrap an AUC interval by resampling complete groups (years)."""

    labels = np.asarray(labels, dtype=float)
    probabilities = np.asarray(probabilities, dtype=float)
    group_values = np.asarray(groups)
    if len(labels) != len(probabilities) or len(labels) != len(group_values):
        raise ValueError("labels, probabilities, and groups must have equal lengths")
    unique_groups = np.unique(group_values)
    rng = np.random.default_rng(seed)
    estimates = []
    group_indices = {
        group: np.flatnonzero(group_values == group) for group in unique_groups
    }
    for _ in range(iterations):
        sampled_groups = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        sampled_indices = np.concatenate(
            [group_indices[group] for group in sampled_groups]
        )
        estimate = roc_auc(labels[sampled_indices], probabilities[sampled_indices])
        if estimate is not None:
            estimates.append(estimate)
    if not estimates:
        return {"lower": None, "upper": None, "confidence": 0.95, "samples": 0}
    return {
        "lower": round(float(np.percentile(estimates, 2.5)), 4),
        "upper": round(float(np.percentile(estimates, 97.5)), 4),
        "confidence": 0.95,
        "samples": len(estimates),
        "resampling_unit": "year",
    }


def _divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _round_optional(value: Optional[float]) -> Optional[float]:
    return round(value, 4) if value is not None else None
