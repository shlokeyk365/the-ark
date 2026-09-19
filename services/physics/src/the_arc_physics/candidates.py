"""Reproducible classifier candidates for flood-impact benchmarking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

import numpy as np

from .logistic import BinaryLogisticRegression


@dataclass
class ConstantSafeClassifier:
    factory: Callable[[], Any]

    def fit(self, matrix: np.ndarray, labels: np.ndarray) -> "ConstantSafeClassifier":
        unique = np.unique(labels)
        if len(unique) == 1:
            self.constant_ = float(unique[0])
            self.model_ = None
        else:
            self.constant_ = None
            self.model_ = self.factory().fit(matrix, labels)
        return self

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        if self.constant_ is not None:
            positive = np.full(len(matrix), self.constant_, dtype=float)
            return np.column_stack((1.0 - positive, positive))
        return self.model_.predict_proba(matrix)

    def __getstate__(self) -> Dict[str, Any]:
        return {"constant_": self.constant_, "model_": self.model_}

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.factory = lambda: None
        self.constant_ = state["constant_"]
        self.model_ = state["model_"]


@dataclass
class SoftVotingClassifier:
    factories: tuple[Callable[[], Any], ...]

    def fit(self, matrix: np.ndarray, labels: np.ndarray) -> "SoftVotingClassifier":
        self.models_ = [factory().fit(matrix, labels) for factory in self.factories]
        return self

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        positive_probabilities = []
        for model in self.models_:
            probabilities = np.asarray(model.predict_proba(matrix))
            positive_probabilities.append(
                probabilities[:, 1] if probabilities.ndim == 2 else probabilities
            )
        positive = np.mean(positive_probabilities, axis=0)
        return np.column_stack((1.0 - positive, positive))

    def __getstate__(self) -> Dict[str, Any]:
        return {"models_": self.models_}

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.factories = ()
        self.models_ = state["models_"]


def classifier_factories() -> Dict[str, Callable[[], Any]]:
    from catboost import CatBoostClassifier
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        HistGradientBoostingClassifier,
        RandomForestClassifier,
    )

    hist_gradient_boosting = lambda: ConstantSafeClassifier(
        lambda: HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=220,
            max_leaf_nodes=15,
            min_samples_leaf=30,
            l2_regularization=0.5,
            random_state=20240928,
        )
    )
    random_forest = lambda: ConstantSafeClassifier(
        lambda: RandomForestClassifier(
            n_estimators=350,
            max_features=0.7,
            min_samples_leaf=10,
            n_jobs=-1,
            random_state=20240928,
        )
    )
    extra_trees = lambda: ConstantSafeClassifier(
        lambda: ExtraTreesClassifier(
            n_estimators=350,
            max_features=0.7,
            min_samples_leaf=10,
            n_jobs=-1,
            random_state=20240928,
        )
    )
    catboost = lambda: ConstantSafeClassifier(
        lambda: CatBoostClassifier(
            iterations=280,
            depth=5,
            learning_rate=0.04,
            loss_function="Logloss",
            l2_leaf_reg=5.0,
            random_seed=20240928,
            allow_writing_files=False,
            verbose=False,
            thread_count=4,
        )
    )
    return {
        "logistic_regression": BinaryLogisticRegression,
        "hist_gradient_boosting": hist_gradient_boosting,
        "random_forest": random_forest,
        "extra_trees": extra_trees,
        "catboost": catboost,
        "soft_voting_ensemble": lambda: SoftVotingClassifier(
            (BinaryLogisticRegression, extra_trees, catboost)
        ),
    }
