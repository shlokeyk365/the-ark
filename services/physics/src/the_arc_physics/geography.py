"""District-level geography used for city-independent flood features."""

from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Sequence, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen


@dataclass(frozen=True)
class DistrictGeography:
    district: str
    latitude: float
    longitude: float
    area_sq_km: float
    elevation_m: float | None = None
    terrain_relief_m: float | None = None


DISTRICT_ALIASES = {
    "arghakanchi": "arghakhanchi",
    "kavre": "kavrepalanchok",
    "mahotari": "mahottari",
    "sindhupalchoke": "sindhupalchok",
    "chitwan": "chitawan",
    "nawalparasieast": "nawalparasi",
    "nawalparasiwest": "nawalparasi",
    "rukumeast": "rukum",
    "rukumwest": "rukum",
}


def build_district_geography(boundaries_path: Path) -> List[DistrictGeography]:
    collection = json.loads(boundaries_path.read_text(encoding="utf-8"))
    rows = []
    for feature in collection["features"]:
        properties = feature["properties"]
        district = properties.get("NAME_3") or properties.get("shapeName")
        polygons = list(_polygons(feature["geometry"]))
        longitude, latitude, area_sq_degrees = _multipolygon_centroid(polygons)
        area_sq_km = area_sq_degrees * 111.32 * 111.32 * math.cos(
            math.radians(latitude)
        )
        rows.append(
            DistrictGeography(
                district=district,
                latitude=round(latitude, 6),
                longitude=round(longitude, 6),
                area_sq_km=round(abs(area_sq_km), 2),
            )
        )
    return sorted(rows, key=lambda row: row.district)


def add_elevation_samples(
    rows: Sequence[DistrictGeography],
) -> List[DistrictGeography]:
    """Fetch center and nearby elevations, then derive a coarse relief feature."""

    sample_coordinates: List[Tuple[float, float]] = []
    for row in rows:
        offset = 0.08
        sample_coordinates.extend(
            [
                (row.latitude, row.longitude),
                (row.latitude + offset, row.longitude),
                (row.latitude - offset, row.longitude),
                (row.latitude, row.longitude + offset),
                (row.latitude, row.longitude - offset),
            ]
        )

    elevations: List[float] = []
    for start in range(0, len(sample_coordinates), 100):
        batch = sample_coordinates[start : start + 100]
        query = urlencode(
            {
                "latitude": ",".join(str(latitude) for latitude, _ in batch),
                "longitude": ",".join(str(longitude) for _, longitude in batch),
            }
        )
        with urlopen(
            f"https://api.open-meteo.com/v1/elevation?{query}", timeout=60
        ) as response:
            payload = json.load(response)
        elevations.extend(float(value) for value in payload["elevation"])

    enriched = []
    for index, row in enumerate(rows):
        samples = elevations[index * 5 : index * 5 + 5]
        enriched.append(
            DistrictGeography(
                district=row.district,
                latitude=row.latitude,
                longitude=row.longitude,
                area_sq_km=row.area_sq_km,
                elevation_m=round(samples[0], 1),
                terrain_relief_m=round(max(samples) - min(samples), 1),
            )
        )
    return enriched


def write_district_geography(path: Path, rows: Iterable[DistrictGeography]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(DistrictGeography.__dataclass_fields__)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def read_district_geography(path: Path) -> Dict[str, DistrictGeography]:
    rows: Dict[str, DistrictGeography] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row = DistrictGeography(
                district=raw["district"],
                latitude=float(raw["latitude"]),
                longitude=float(raw["longitude"]),
                area_sq_km=float(raw["area_sq_km"]),
                elevation_m=_optional_float(raw.get("elevation_m")),
                terrain_relief_m=_optional_float(raw.get("terrain_relief_m")),
            )
            rows[normalize_district(row.district)] = row
    return rows


def normalize_district(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    key = re.sub(r"[^a-z]", "", ascii_value)
    return DISTRICT_ALIASES.get(key, key)


def _polygons(geometry: Mapping[str, object]) -> Iterator[Sequence[Sequence[float]]]:
    geometry_type = geometry["type"]
    coordinates = geometry["coordinates"]
    if geometry_type == "Polygon":
        yield coordinates  # type: ignore[misc]
    elif geometry_type == "MultiPolygon":
        yield from coordinates  # type: ignore[misc]
    else:
        raise ValueError(f"unsupported geometry type: {geometry_type}")


def _multipolygon_centroid(
    polygons: Sequence[Sequence[Sequence[float]]],
) -> Tuple[float, float, float]:
    weighted_x = 0.0
    weighted_y = 0.0
    total_area = 0.0
    for polygon in polygons:
        if not polygon:
            continue
        centroid_x, centroid_y, signed_area = _ring_centroid(polygon[0])
        area = abs(signed_area)
        weighted_x += centroid_x * area
        weighted_y += centroid_y * area
        total_area += area
    if total_area == 0.0:
        raise ValueError("boundary geometry has zero area")
    return weighted_x / total_area, weighted_y / total_area, total_area


def _ring_centroid(ring: Sequence[Sequence[float]]) -> Tuple[float, float, float]:
    twice_area = 0.0
    x_sum = 0.0
    y_sum = 0.0
    for first, second in zip(ring, ring[1:]):
        cross = first[0] * second[1] - second[0] * first[1]
        twice_area += cross
        x_sum += (first[0] + second[0]) * cross
        y_sum += (first[1] + second[1]) * cross
    if abs(twice_area) < 1e-12:
        points = ring or ((0.0, 0.0),)
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
            0.0,
        )
    return x_sum / (3.0 * twice_area), y_sum / (3.0 * twice_area), twice_area / 2.0


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)
