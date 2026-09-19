"""Selected city-independent soft-voting flood impact model."""

from __future__ import annotations

import json
import gzip
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import numpy as np

from .candidates import classifier_factories
from .features import EventInput, FeatureEncoder, event_inputs
from .geography import normalize_district
from .records import FloodEventRecord, TARGET_NAMES


@dataclass
class EnsembleFloodImpactModel:
    encoder: FeatureEncoder
    classifiers: Mapping[str, Any]
    training_metadata: Mapping[str, Any]

    @classmethod
    def fit(
        cls,
        records: Sequence[FloodEventRecord],
        validation_gate: Mapping[str, Any],
    ) -> "EnsembleFloodImpactModel":
        inputs = event_inputs(records)
        encoder = FeatureEncoder.fit(inputs)
        matrix = encoder.transform(inputs)
        factory = classifier_factories()["soft_voting_ensemble"]
        classifiers: Dict[str, Any] = {}
        for target in TARGET_NAMES:
            known = np.asarray(
                [record.target_known[target] for record in records], dtype=bool
            )
            labels = np.asarray([record.targets[target] for record in records], dtype=float)
            classifiers[target] = factory().fit(matrix[known], labels[known])
        return cls(
            encoder=encoder,
            classifiers=classifiers,
            training_metadata={
                "model_type": "soft_voting_logistic_extra_trees_catboost",
                "record_count": len(records),
                "event_count": len({record.event_id for record in records}),
                "district_group_count": len(
                    {normalize_district(record.district) for record in records}
                ),
                "year_min": min(record.year for record in records),
                "year_max": max(record.year for record in records),
                "source_names": sorted({record.source for record in records}),
                "feature_policy": "city and district identity excluded from predictors",
                "holdout_policy": "No event from 2024 or later is allowed in training.",
                "validation_gate": dict(validation_gate),
            },
        )

    def predict(self, event: EventInput) -> Dict[str, float]:
        matrix = self.encoder.transform((event,))
        predictions = {}
        for target, classifier in self.classifiers.items():
            probabilities = np.asarray(classifier.predict_proba(matrix))
            probability = (
                probabilities[0, 1] if probabilities.ndim == 2 else probabilities[0]
            )
            predictions[target] = round(float(probability), 6)
        return predictions

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wb", compresslevel=6) as handle:
            pickle.dump(self, handle, protocol=pickle.HIGHEST_PROTOCOL)
        manifest = {
            "model_type": self.training_metadata["model_type"],
            "artifact": path.name,
            "feature_encoder": self.encoder.to_dict(),
            "training_metadata": dict(self.training_metadata),
            "warning": "Only load this pickle from the trusted project repository.",
        }
        path.with_suffix(".manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> "EnsembleFloodImpactModel":
        with gzip.open(path, "rb") as handle:
            model = pickle.load(handle)
        if not isinstance(model, cls):
            raise ValueError("artifact is not an EnsembleFloodImpactModel")
        return model


def load_flood_model(path: Path) -> Any:
    if path.name.lower().endswith((".pkl.gz", ".pickle.gz")):
        return EnsembleFloodImpactModel.load(path)
    from .model import MultiLabelFloodImpactModel

    return MultiLabelFloodImpactModel.load(path)
