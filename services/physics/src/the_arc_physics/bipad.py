"""Ingest recent, verified Nepal flood incidents from the official BIPAD API."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .geography import normalize_district
from .records import FloodEventRecord


BIPAD_API = "https://bipadportal.gov.np/api/v1"


def read_bipad_floods(
    cache_dir: Path,
    historical_records: Sequence[FloodEventRecord],
    start_year: int = 2014,
    end_year: int = 2023,
) -> Iterator[FloodEventRecord]:
    """Yield approved, verified flood incidents while keeping 2024 locked out."""

    if end_year >= 2024:
        raise ValueError("BIPAD training import must end before the 2024 holdout")
    cache_dir.mkdir(parents=True, exist_ok=True)
    municipality_payload = _cached_get(
        f"{BIPAD_API}/municipality/?"
        + urlencode({"limit": 1000, "expand": "district,province"}),
        cache_dir / "municipalities.json",
    )
    municipalities = {
        int(item["id"]): item for item in municipality_payload["results"]
    }
    region_by_district = _historical_region_lookup(historical_records)

    for incident in _incident_pages(cache_dir):
        incident_date = datetime.fromisoformat(incident["incidentOn"]).date()
        if not start_year <= incident_date.year <= end_year:
            continue
        if not incident.get("verified") or not incident.get("approved"):
            continue
        wards = incident.get("wards") or []
        if not wards or not isinstance(wards[0], Mapping):
            continue
        municipality = municipalities.get(int(wards[0]["municipality"]))
        if municipality is None:
            continue
        district = municipality["district"]["title_en"]
        normalized_district = normalize_district(district)
        region = region_by_district.get(normalized_district, "UNKNOWN")
        loss = incident.get("loss") or {}
        point = incident.get("point") or {}
        coordinates = point.get("coordinates") or (None, None)
        destroyed_roads = _integer(loss.get("infrastructureDestroyedRoadCount"))
        affected_roads = _integer(loss.get("infrastructureAffectedRoadCount"))
        destroyed_bridges = _integer(
            loss.get("infrastructureDestroyedBridgeCount")
        )
        affected_bridges = _integer(loss.get("infrastructureAffectedBridgeCount"))
        yield FloodEventRecord(
            event_id=f"bipad-{incident['id']}",
            source="Government of Nepal BIPAD Portal",
            year=incident_date.year,
            month=incident_date.month,
            day=incident_date.day,
            region=region,
            district=district,
            municipality=municipality["title_en"],
            cause=(incident.get("cause") or "FLOOD").upper(),
            deaths=_integer(loss.get("peopleDeathCount")),
            missing=_integer(loss.get("peopleMissingCount")),
            injured=_integer(loss.get("peopleInjuredCount")),
            people_affected=_integer(loss.get("peopleAffectedCount")),
            houses_destroyed=_integer(
                loss.get("infrastructureDestroyedHouseCount")
            ),
            houses_affected=_integer(loss.get("infrastructureAffectedHouseCount")),
            evacuated=_integer(loss.get("familyEvacuatedCount")),
            roads_damaged_km=0.0,
            transport_affected=(
                destroyed_roads + affected_roads + destroyed_bridges + affected_bridges
                > 0
            ),
            latitude=_optional_number(coordinates[1]),
            longitude=_optional_number(coordinates[0]),
            transport_label_known=False,
        )


def _incident_pages(cache_dir: Path) -> Iterator[Mapping[str, object]]:
    offset = 0
    limit = 1000
    seen_ids = set()
    for page in range(20):
        query = urlencode(
            {
                "hazard": 11,
                "expand": "loss,wards",
                "limit": limit,
                "offset": offset,
                "ordering": "id",
            }
        )
        payload = _cached_get(
            f"{BIPAD_API}/incident/?{query}",
            cache_dir / f"flood_incidents_ordered_{page:02d}.json",
        )
        results = payload.get("results", [])
        if not results:
            break
        for result in results:
            incident_id = int(result["id"])
            if incident_id not in seen_ids:
                seen_ids.add(incident_id)
                yield result
        if len(results) < limit:
            break
        offset += limit
    else:
        raise RuntimeError("BIPAD pagination exceeded the 20-page safety limit")


def _historical_region_lookup(
    records: Iterable[FloodEventRecord],
) -> Dict[str, str]:
    counts: Dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        counts[normalize_district(record.district)][record.region] += 1
    return {
        district: region_counts.most_common(1)[0][0]
        for district, region_counts in counts.items()
    }


def _cached_get(url: str, path: Path) -> Mapping[str, object]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    request = Request(url, headers={"User-Agent": "The-Arc-Hackathon/0.1"})
    with urlopen(request, timeout=180) as response:
        payload = json.load(response)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def _integer(value: object) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _optional_number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed != 0.0 else None
