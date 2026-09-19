"""Normalized historical event records used by the learning pipeline."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, Sequence


TARGET_NAMES = (
    "casualty_or_missing",
    "housing_damage",
    "transport_disruption",
    "severe_impact",
)


@dataclass(frozen=True)
class FloodEventRecord:
    event_id: str
    source: str
    year: int
    month: int
    day: int
    region: str
    district: str
    municipality: str
    cause: str
    deaths: int
    missing: int
    injured: int
    people_affected: int
    houses_destroyed: int
    houses_affected: int
    evacuated: int
    roads_damaged_km: float
    transport_affected: bool

    @property
    def targets(self) -> Mapping[str, int]:
        casualties = self.deaths + self.missing + self.injured
        damaged_housing = self.houses_destroyed + self.houses_affected
        return {
            "casualty_or_missing": int(casualties > 0),
            "housing_damage": int(damaged_housing > 0),
            "transport_disruption": int(
                self.transport_affected or self.roads_damaged_km > 0
            ),
            "severe_impact": int(
                self.people_affected >= 50
                or damaged_housing >= 10
                or self.deaths + self.missing > 0
            ),
        }


CSV_FIELDS = tuple(FloodEventRecord.__dataclass_fields__.keys())


def write_records(path: Path, records: Iterable[FloodEventRecord]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))
            count += 1
    return count


def read_records(path: Path) -> List[FloodEventRecord]:
    records: List[FloodEventRecord] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            records.append(
                FloodEventRecord(
                    event_id=row["event_id"],
                    source=row["source"],
                    year=int(row["year"]),
                    month=int(row["month"]),
                    day=int(row["day"]),
                    region=row["region"],
                    district=row["district"],
                    municipality=row["municipality"],
                    cause=row["cause"],
                    deaths=int(row["deaths"]),
                    missing=int(row["missing"]),
                    injured=int(row["injured"]),
                    people_affected=int(row["people_affected"]),
                    houses_destroyed=int(row["houses_destroyed"]),
                    houses_affected=int(row["houses_affected"]),
                    evacuated=int(row["evacuated"]),
                    roads_damaged_km=float(row["roads_damaged_km"]),
                    transport_affected=_to_bool(row["transport_affected"]),
                )
            )
    return records


def validate_training_records(
    records: Sequence[FloodEventRecord],
    holdout_year: int = 2024,
) -> None:
    if len(records) < 100:
        raise ValueError("at least 100 historical flood records are required")
    duplicate_ids = len(records) - len({record.event_id for record in records})
    if duplicate_ids:
        raise ValueError(f"training data contains {duplicate_ids} duplicate event IDs")
    leaked = [record.event_id for record in records if record.year >= holdout_year]
    if leaked:
        raise ValueError(
            "holdout leakage: training records include events from "
            f"{holdout_year} or later (first: {leaked[0]})"
        )
    years = {record.year for record in records}
    if len(years) < 5:
        raise ValueError("training data must span at least five different years")
    for record in records:
        if not 1 <= record.month <= 12:
            raise ValueError(f"invalid month for {record.event_id}: {record.month}")


def _to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}

