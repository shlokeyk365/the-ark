"""Stable contract between the learned impact prior and scenario consumers."""

from __future__ import annotations

from typing import Any, Mapping

from .features import NUMERIC_FIELDS, EventInput
from .model import MultiLabelFloodImpactModel


def simulation_impact_prior(
    model: MultiLabelFloodImpactModel,
    event_id: str,
    event: EventInput,
) -> Mapping[str, Any]:
    """Return a frontend/simulator-safe prediction without holdout labels."""

    return {
        "schemaVersion": "1.0",
        "eventId": event_id,
        "modelPurpose": "historical_event_impact_prior",
        "input": {
            "year": event.year,
            "month": event.month,
            "day": event.day,
            "region": event.region,
            "district": event.district,
            "cause": event.cause,
            **{field: getattr(event, field) for field in NUMERIC_FIELDS},
        },
        "impactProbabilities": model.predict(event),
        "trainingMetadata": dict(model.training_metadata),
        "limitations": [
            "These probabilities do not predict street-level flood extent or depth.",
            "The historical records contain reporting bias and incomplete zero values.",
            "Counterfactual rescue outcomes cannot be validated by this model.",
        ],
    }
