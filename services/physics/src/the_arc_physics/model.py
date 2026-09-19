"""Multi-event Nepal flood impact model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

import numpy as np

from .features import EventInput, FeatureEncoder, event_inputs
from .logistic import BinaryLogisticRegression
from .records import FloodEventRecord, TARGET_NAMES


@dataclass
class MultiLabelFloodImpactModel:
    encoder: FeatureEncoder
    classifiers: Mapping[str, BinaryLogisticRegression]
    training_metadata: Mapping[str, Any]

    @classmethod
    def fit(
        cls,
        records: Sequence[FloodEventRecord],
    ) -> "MultiLabelFloodImpactModel":
        inputs = event_inputs(records)
        encoder = FeatureEncoder.fit(inputs)
        matrix = encoder.transform(inputs)
        classifiers: Dict[str, BinaryLogisticRegression] = {}
        for target in TARGET_NAMES:
            labels = np.asarray([record.targets[target] for record in records], dtype=float)
            classifiers[target] = BinaryLogisticRegression().fit(matrix, labels)
        return cls(
            encoder=encoder,
            classifiers=classifiers,
            training_metadata={
                "record_count": len(records),
                "event_count": len({record.event_id for record in records}),
                "year_min": min(record.year for record in records),
                "year_max": max(record.year for record in records),
                "source_names": sorted({record.source for record in records}),
                "holdout_policy": "No event from 2024 or later is allowed in training.",
            },
        )

    def predict(self, event: EventInput) -> Dict[str, float]:
        matrix = self.encoder.transform((event,))
        return {
            target: round(float(classifier.predict_proba(matrix)[0]), 6)
            for target, classifier in self.classifiers.items()
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model_type": "multi_label_logistic_regression",
            "model_purpose": "historical_flood_impact_prior",
            "encoder": self.encoder.to_dict(),
            "classifiers": {
                target: classifier.to_dict()
                for target, classifier in self.classifiers.items()
            },
            "training_metadata": dict(self.training_metadata),
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "MultiLabelFloodImpactModel":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            encoder=FeatureEncoder.from_dict(payload["encoder"]),
            classifiers={
                target: BinaryLogisticRegression.from_dict(value)
                for target, value in payload["classifiers"].items()
            },
            training_metadata=payload["training_metadata"],
        )

