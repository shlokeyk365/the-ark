"""Consolidate repeated administrative reports into event-location episodes."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from statistics import mean
from typing import Dict, Iterable, List, Tuple

from .geography import normalize_district
from .records import FloodEventRecord


EpisodeKey = Tuple[str, int, int, int, str, str, str]


def consolidate_event_reports(
    records: Iterable[FloodEventRecord],
) -> List[FloodEventRecord]:
    groups: Dict[EpisodeKey, List[FloodEventRecord]] = {}
    for record in records:
        key = (
            record.source,
            record.year,
            record.month,
            record.day,
            normalize_district(record.district),
            _normalized_place(record.municipality),
            (record.cause or "UNKNOWN").strip().upper(),
        )
        groups.setdefault(key, []).append(record)

    episodes = []
    for key, reports in sorted(groups.items(), key=lambda item: item[0]):
        first = reports[0]
        identifier = hashlib.sha256("|".join(map(str, key)).encode("utf-8")).hexdigest()[:20]
        latitudes = [value.latitude for value in reports if value.latitude is not None]
        longitudes = [value.longitude for value in reports if value.longitude is not None]
        episodes.append(
            replace(
                first,
                event_id=f"episode-{identifier}",
                deaths=sum(value.deaths for value in reports),
                missing=sum(value.missing for value in reports),
                injured=sum(value.injured for value in reports),
                people_affected=sum(value.people_affected for value in reports),
                houses_destroyed=sum(value.houses_destroyed for value in reports),
                houses_affected=sum(value.houses_affected for value in reports),
                evacuated=sum(value.evacuated for value in reports),
                roads_damaged_km=sum(value.roads_damaged_km for value in reports),
                transport_affected=any(
                    value.transport_affected for value in reports
                ),
                latitude=(mean(latitudes) if latitudes else None),
                longitude=(mean(longitudes) if longitudes else None),
                casualty_label_known=any(
                    value.casualty_label_known for value in reports
                ),
                housing_label_known=any(
                    value.housing_label_known for value in reports
                ),
                transport_label_known=any(
                    value.transport_label_known for value in reports
                ),
                severe_label_known=any(
                    value.severe_label_known for value in reports
                ),
            )
        )
    return episodes


def _normalized_place(value: str) -> str:
    normalized = " ".join((value or "UNKNOWN").strip().lower().split())
    return normalized or "unknown"
