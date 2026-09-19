"""Small dependency-light binary logistic regression implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

import numpy as np


@dataclass
class BinaryLogisticRegression:
    learning_rate: float = 0.08
    iterations: int = 600
    l2: float = 0.02

    def fit(self, matrix: np.ndarray, labels: np.ndarray) -> "BinaryLogisticRegression":
        if matrix.ndim != 2 or labels.ndim != 1:
            raise ValueError("expected a feature matrix and one-dimensional labels")
        if len(matrix) != len(labels):
            raise ValueError("feature and label counts differ")
        positives = float(labels.sum())
        negatives = float(len(labels) - positives)
        self.mean_ = matrix.mean(axis=0)
        self.scale_ = matrix.std(axis=0)
        self.scale_[self.scale_ < 1e-8] = 1.0
        normalized = (matrix - self.mean_) / self.scale_
        design = np.column_stack((np.ones(len(normalized)), normalized))
        self.weights_ = np.zeros(design.shape[1], dtype=float)

        if positives == 0 or negatives == 0:
            smoothed_rate = (positives + 0.5) / (len(labels) + 1.0)
            self.weights_[0] = np.log(smoothed_rate / (1.0 - smoothed_rate))
            return self

        positive_weight = len(labels) / (2.0 * positives)
        negative_weight = len(labels) / (2.0 * negatives)
        sample_weights = np.where(labels > 0.5, positive_weight, negative_weight)
        denominator = sample_weights.sum()

        for _ in range(self.iterations):
            probabilities = _sigmoid(design @ self.weights_)
            residual = (probabilities - labels) * sample_weights
            gradient = design.T @ residual / denominator
            gradient[1:] += self.l2 * self.weights_[1:]
            self.weights_ -= self.learning_rate * gradient
            if float(np.max(np.abs(gradient))) < 1e-6:
                break
        return self

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        self._check_fitted()
        normalized = (matrix - self.mean_) / self.scale_
        design = np.column_stack((np.ones(len(normalized)), normalized))
        return _sigmoid(design @ self.weights_)

    def to_dict(self) -> Dict[str, Any]:
        self._check_fitted()
        return {
            "learning_rate": self.learning_rate,
            "iterations": self.iterations,
            "l2": self.l2,
            "mean": self.mean_.tolist(),
            "scale": self.scale_.tolist(),
            "weights": self.weights_.tolist(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BinaryLogisticRegression":
        model = cls(
            learning_rate=float(value["learning_rate"]),
            iterations=int(value["iterations"]),
            l2=float(value["l2"]),
        )
        model.mean_ = np.asarray(value["mean"], dtype=float)
        model.scale_ = np.asarray(value["scale"], dtype=float)
        model.weights_ = np.asarray(value["weights"], dtype=float)
        return model

    def _check_fitted(self) -> None:
        if not hasattr(self, "weights_"):
            raise RuntimeError("model has not been fitted")


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))
