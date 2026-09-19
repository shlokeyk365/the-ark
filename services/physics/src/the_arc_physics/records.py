"""Normalized historical event records used by the learning pipeline."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence


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
    casualty_label_known: bool = True
    housing_label_known: bool = True
    transport_label_known: bool = True
    severe_label_known: bool = True

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

    @property
    def target_known(self) -> Mapping[str, bool]:
        return {
            "casualty_or_missing": self.casualty_label_known,
            "housing_damage": self.housing_label_known,
            "transport_disruption": self.transport_label_known,
            "severe_impact": self.severe_label_known,
        }


CSV_FIELDS = tuple(FloodEventRecord.__dataclass_fields__.keys())


def write_records(path: Path, records: Iterable[FloodEventRecord]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
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
                    latitude=_optional_number(row.get("latitude")),
                    longitude=_optional_number(row.get("longitude")),
                    district_area_sq_km=_optional_number(
                        row.get("district_area_sq_km")
                    ),
                    elevation_m=_optional_number(row.get("elevation_m")),
                    terrain_relief_m=_optional_number(row.get("terrain_relief_m")),
                    households_2011=_optional_number(row.get("households_2011")),
                    population_2011=_optional_number(row.get("population_2011")),
                    population_density_2011=_optional_number(
                        row.get("population_density_2011")
                    ),
                    rainfall_1d_mm=_optional_number(row.get("rainfall_1d_mm")),
                    rainfall_3d_mm=_optional_number(row.get("rainfall_3d_mm")),
                    rainfall_7d_mm=_optional_number(row.get("rainfall_7d_mm")),
                    rainfall_30d_mm=_optional_number(row.get("rainfall_30d_mm")),
                    rainy_days_7d=_optional_number(row.get("rainy_days_7d")),
                    rainfall_7d_anomaly=_optional_number(
                        row.get("rainfall_7d_anomaly")
                    ),
                    casualty_label_known=_optional_bool(
                        row.get("casualty_label_known"), default=True
                    ),
                    housing_label_known=_optional_bool(
                        row.get("housing_label_known"), default=True
                    ),
                    transport_label_known=_optional_bool(
                        row.get("transport_label_known"), default=True
                    ),
                    severe_label_known=_optional_bool(
                        row.get("severe_label_known"), default=True
                    ),
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


def _optional_bool(value: Optional[str], default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return _to_bool(value)


def _optional_number(value: Optional[str]) -> Optional[float]:
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed > -900.0 else None
