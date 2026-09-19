"""Transparent classification metrics used for cross-validation and holdouts."""

from __future__ import annotations

from typing import Dict

import numpy as np


def binary_metrics(labels: np.ndarray, probabilities: np.ndarray) -> Dict[str, float]:
    predicted = probabilities >= 0.5
    actual = labels >= 0.5
    true_positive = int(np.sum(predicted & actual))
    true_negative = int(np.sum(~predicted & ~actual))
    false_positive = int(np.sum(predicted & ~actual))
    false_negative = int(np.sum(~predicted & actual))
    precision = _divide(true_positive, true_positive + false_positive)
    recall = _divide(true_positive, true_positive + false_negative)
    f1 = _divide(2.0 * precision * recall, precision + recall)
    return {
        "accuracy": round(_divide(true_positive + true_negative, len(labels)), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "brier": round(float(np.mean((probabilities - labels) ** 2)), 4),
        "support": int(len(labels)),
        "positive_rate": round(float(np.mean(labels)), 4),
    }


def _divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0

