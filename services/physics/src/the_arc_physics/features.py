"""Leakage-safe, city-independent event features for historical models."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np

from .records import FloodEventRecord


NUMERIC_FIELDS = (
    "latitude",
    "longitude",
    "district_area_sq_km",
    "elevation_m",
    "terrain_relief_m",
    "households_2011",
    "population_2011",
    "population_density_2011",
    "rainfall_1d_mm",
    "rainfall_3d_mm",
    "rainfall_7d_mm",
    "rainfall_30d_mm",
    "rainy_days_7d",
    "rainfall_7d_anomaly",
)

LOG_FIELDS = {
    "district_area_sq_km",
    "elevation_m",
    "terrain_relief_m",
    "households_2011",
    "population_2011",
    "population_density_2011",
    "rainfall_1d_mm",
    "rainfall_3d_mm",
    "rainfall_7d_mm",
    "rainfall_30d_mm",
    "rainfall_7d_anomaly",
}


@dataclass(frozen=True)
class EventInput:
    year: int
    month: int
    day: int
    region: str
    district: str
    cause: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    district_area_sq_km: Optional[float] = None
    elevation_m: Optional[float] = None
    terrain_relief_m: Optional[float] = None
    households_2011: Optional[float] = None
    population_2011: Optional[float] = None
    population_density_2011: Optional[float] = None
    rainfall_1d_mm: Optional[float] = None
    rainfall_3d_mm: Optional[float] = None
    rainfall_7d_mm: Optional[float] = None
    rainfall_30d_mm: Optional[float] = None
    rainy_days_7d: Optional[float] = None
    rainfall_7d_anomaly: Optional[float] = None


class FeatureEncoder:
    """Encoder that deliberately excludes city and district identity.

    Geographic names remain in :class:`EventInput` for audit and grouping but
    are not predictor columns. This forces the model to transfer through
    weather, terrain, coordinates, region, and event cause.
    """

    def __init__(
        self,
        regions: Sequence[str],
        causes: Sequence[str],
        numeric_medians: Mapping[str, float],
    ) -> None:
        self.regions = tuple(regions)
        self.causes = tuple(causes)
        self.numeric_medians = {
            field: float(numeric_medians.get(field, 0.0)) for field in NUMERIC_FIELDS
        }
        self.feature_names = (
            "month_sin",
            "month_cos",
            "monsoon_month",
            "day_known",
            *(f"numeric={field}" for field in NUMERIC_FIELDS),
            *(f"available={field}" for field in NUMERIC_FIELDS),
            *(f"region={value}" for value in self.regions),
            *(f"cause={value}" for value in self.causes),
        )

    @classmethod
    def fit(cls, rows: Iterable[EventInput]) -> "FeatureEncoder":
        rows = tuple(rows)
        medians = {}
        for field in NUMERIC_FIELDS:
            values = [
                float(value)
                for row in rows
                if (value := getattr(row, field)) is not None
                and math.isfinite(float(value))
            ]
            medians[field] = median(values) if values else 0.0
        return cls(
            regions=sorted({row.region or "UNKNOWN" for row in rows}),
            causes=sorted({row.cause or "UNKNOWN" for row in rows}),
            numeric_medians=medians,
        )

    def transform(self, rows: Iterable[EventInput]) -> np.ndarray:
        rows = tuple(rows)
        matrix = np.zeros((len(rows), len(self.feature_names)), dtype=float)
        region_index = {value: index for index, value in enumerate(self.regions)}
        cause_index = {value: index for index, value in enumerate(self.causes)}
        numeric_offset = 4
        availability_offset = numeric_offset + len(NUMERIC_FIELDS)
        region_offset = availability_offset + len(NUMERIC_FIELDS)
        cause_offset = region_offset + len(self.regions)

        for index, row in enumerate(rows):
            angle = 2.0 * math.pi * (row.month - 1) / 12.0
            matrix[index, 0] = math.sin(angle)
            matrix[index, 1] = math.cos(angle)
            matrix[index, 2] = float(6 <= row.month <= 9)
            matrix[index, 3] = float(row.day > 0)
            for field_index, field in enumerate(NUMERIC_FIELDS):
                raw_value = getattr(row, field)
                available = raw_value is not None and math.isfinite(float(raw_value))
                value = float(raw_value) if available else self.numeric_medians[field]
                if field in LOG_FIELDS:
                    value = math.log1p(max(0.0, value))
                matrix[index, numeric_offset + field_index] = value
                matrix[index, availability_offset + field_index] = float(available)
            if row.region in region_index:
                matrix[index, region_offset + region_index[row.region]] = 1.0
            if row.cause in cause_index:
                matrix[index, cause_offset + cause_index[row.cause]] = 1.0
        return matrix

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy": "city_identity_excluded_v1",
            "regions": list(self.regions),
            "causes": list(self.causes),
            "numeric_medians": dict(self.numeric_medians),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FeatureEncoder":
        return cls(
            regions=value["regions"],
            causes=value["causes"],
            numeric_medians=value.get("numeric_medians", {}),
        )


def event_inputs(records: Iterable[FloodEventRecord]) -> List[EventInput]:
    return [
        EventInput(
            year=record.year,
            month=record.month,
            day=record.day,
            region=record.region,
            district=record.district,
            cause=record.cause,
            **{field: getattr(record, field) for field in NUMERIC_FIELDS},
        )
        for record in records
    ]
