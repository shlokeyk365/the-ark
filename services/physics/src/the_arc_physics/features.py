"""Leakage-safe event metadata features for the first historical model."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import numpy as np

from .records import FloodEventRecord


@dataclass(frozen=True)
class EventInput:
    year: int
    month: int
    day: int
    region: str
    district: str
    cause: str


class FeatureEncoder:
    """One-hot encoder fitted only on the training side of each split."""

    def __init__(
        self,
        regions: Sequence[str],
        districts: Sequence[str],
        causes: Sequence[str],
    ) -> None:
        self.regions = tuple(regions)
        self.districts = tuple(districts)
        self.causes = tuple(causes)
        self.feature_names = (
            "month_sin",
            "month_cos",
            "monsoon_month",
            "day_known",
            *(f"region={value}" for value in self.regions),
            *(f"district={value}" for value in self.districts),
            *(f"cause={value}" for value in self.causes),
        )

    @classmethod
    def fit(cls, rows: Iterable[EventInput]) -> "FeatureEncoder":
        rows = tuple(rows)
        return cls(
            regions=sorted({row.region or "UNKNOWN" for row in rows}),
            districts=sorted({row.district or "UNKNOWN" for row in rows}),
            causes=sorted({row.cause or "UNKNOWN" for row in rows}),
        )

    def transform(self, rows: Iterable[EventInput]) -> np.ndarray:
        rows = tuple(rows)
        matrix = np.zeros((len(rows), len(self.feature_names)), dtype=float)
        region_index = {value: index for index, value in enumerate(self.regions)}
        district_index = {value: index for index, value in enumerate(self.districts)}
        cause_index = {value: index for index, value in enumerate(self.causes)}
        region_offset = 4
        district_offset = region_offset + len(self.regions)
        cause_offset = district_offset + len(self.districts)

        for index, row in enumerate(rows):
            angle = 2.0 * math.pi * (row.month - 1) / 12.0
            matrix[index, 0] = math.sin(angle)
            matrix[index, 1] = math.cos(angle)
            matrix[index, 2] = float(6 <= row.month <= 9)
            matrix[index, 3] = float(row.day > 0)
            if row.region in region_index:
                matrix[index, region_offset + region_index[row.region]] = 1.0
            if row.district in district_index:
                matrix[index, district_offset + district_index[row.district]] = 1.0
            if row.cause in cause_index:
                matrix[index, cause_offset + cause_index[row.cause]] = 1.0
        return matrix

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regions": list(self.regions),
            "districts": list(self.districts),
            "causes": list(self.causes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FeatureEncoder":
        return cls(
            regions=value["regions"],
            districts=value["districts"],
            causes=value["causes"],
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
        )
        for record in records
    ]

