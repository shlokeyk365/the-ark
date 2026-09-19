"""HydroBASINS/HydroRIVERS extraction and runtime feature lookup."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


Point = Tuple[float, float]


@dataclass(frozen=True)
class BasinFeature:
    basin_id: str
    sub_basin_area_sq_km: float
    upstream_area_sq_km: float
    distance_to_outlet_km: float
    basin_order: float
    geometry: Mapping[str, object]


@dataclass(frozen=True)
class RiverFeature:
    river_id: str
    average_discharge_cms: float
    upstream_area_sq_km: float
    strahler_order: float
    lines: Tuple[Tuple[Point, ...], ...]


@dataclass(frozen=True)
class HydrologyFeatures:
    basin_id: Optional[str] = None
    sub_basin_area_sq_km: Optional[float] = None
    upstream_area_sq_km: Optional[float] = None
    distance_to_outlet_km: Optional[float] = None
    basin_order: Optional[float] = None
    nearest_river_distance_km: Optional[float] = None
    river_average_discharge_cms: Optional[float] = None
    river_upstream_area_sq_km: Optional[float] = None
    river_strahler_order: Optional[float] = None


class HydrologyIndex:
    """Small Nepal-only spatial index derived from official HydroSHEDS data."""

    def __init__(
        self,
        basins: Sequence[BasinFeature],
        rivers: Sequence[RiverFeature],
        grid_size: float = 0.1,
    ) -> None:
        self.basins = tuple(basins)
        self.rivers = tuple(rivers)
        self.grid_size = grid_size
        self._river_grid: Dict[Tuple[int, int], set[int]] = {}
        for river_index, river in enumerate(self.rivers):
            for line in river.lines:
                for first, second in zip(line, line[1:]):
                    min_x = min(first[0], second[0])
                    max_x = max(first[0], second[0])
                    min_y = min(first[1], second[1])
                    max_y = max(first[1], second[1])
                    for x_cell in range(
                        math.floor(min_x / grid_size),
                        math.floor(max_x / grid_size) + 1,
                    ):
                        for y_cell in range(
                            math.floor(min_y / grid_size),
                            math.floor(max_y / grid_size) + 1,
                        ):
                            self._river_grid.setdefault((x_cell, y_cell), set()).add(
                                river_index
                            )

    @classmethod
    def load(cls, path: Path) -> "HydrologyIndex":
        payload = json.loads(path.read_text(encoding="utf-8"))
        basins = [
            BasinFeature(
                basin_id=str(item["basin_id"]),
                sub_basin_area_sq_km=float(item["sub_basin_area_sq_km"]),
                upstream_area_sq_km=float(item["upstream_area_sq_km"]),
                distance_to_outlet_km=float(item["distance_to_outlet_km"]),
                basin_order=float(item["basin_order"]),
                geometry=item["geometry"],
            )
            for item in payload["basins"]
        ]
        rivers = [
            RiverFeature(
                river_id=str(item["river_id"]),
                average_discharge_cms=float(item["average_discharge_cms"]),
                upstream_area_sq_km=float(item["upstream_area_sq_km"]),
                strahler_order=float(item["strahler_order"]),
                lines=tuple(
                    tuple((float(point[0]), float(point[1])) for point in line)
                    for line in item["lines"]
                ),
            )
            for item in payload["rivers"]
        ]
        return cls(basins, rivers, float(payload.get("grid_size", 0.1)))

    def features_at(self, latitude: float, longitude: float) -> HydrologyFeatures:
        basin = self.basin_at(latitude, longitude)
        river, distance = self._nearest_river(latitude, longitude)
        return HydrologyFeatures(
            basin_id=basin.basin_id if basin else None,
            sub_basin_area_sq_km=(basin.sub_basin_area_sq_km if basin else None),
            upstream_area_sq_km=(basin.upstream_area_sq_km if basin else None),
            distance_to_outlet_km=(basin.distance_to_outlet_km if basin else None),
            basin_order=(basin.basin_order if basin else None),
            nearest_river_distance_km=round(distance, 4) if river else None,
            river_average_discharge_cms=(
                river.average_discharge_cms if river else None
            ),
            river_upstream_area_sq_km=(river.upstream_area_sq_km if river else None),
            river_strahler_order=(river.strahler_order if river else None),
        )

    def basin_at(
        self, latitude: float, longitude: float
    ) -> Optional[BasinFeature]:
        return next(
            (
                value
                for value in self.basins
                if point_in_geometry(longitude, latitude, value.geometry)
            ),
            None,
        )

    def _nearest_river(
        self, latitude: float, longitude: float
    ) -> Tuple[Optional[RiverFeature], float]:
        center = (
            math.floor(longitude / self.grid_size),
            math.floor(latitude / self.grid_size),
        )
        candidates: set[int] = set()
        for radius in range(0, 11):
            for x_cell in range(center[0] - radius, center[0] + radius + 1):
                for y_cell in range(center[1] - radius, center[1] + radius + 1):
                    if radius and (
                        abs(x_cell - center[0]) != radius
                        and abs(y_cell - center[1]) != radius
                    ):
                        continue
                    candidates.update(self._river_grid.get((x_cell, y_cell), ()))
            if candidates:
                break
        best_river = None
        best_distance = math.inf
        for index in candidates:
            river = self.rivers[index]
            for line in river.lines:
                for first, second in zip(line, line[1:]):
                    distance = _point_segment_distance_km(
                        longitude, latitude, first, second
                    )
                    if distance < best_distance:
                        best_distance = distance
                        best_river = river
        return best_river, best_distance


def build_nepal_hydrology_index(
    basin_shapefile: Path,
    river_shapefile: Path,
    district_boundaries: Path,
    output_path: Path,
) -> Mapping[str, int]:
    """Clip Asian HydroBASINS/HydroRIVERS shapefiles to Nepal."""

    try:
        import shapefile
    except ImportError as error:  # pragma: no cover - exercised by CLI users
        raise RuntimeError("building the hydrology index requires pyshp") from error

    country = json.loads(district_boundaries.read_text(encoding="utf-8"))
    district_geometries = [feature["geometry"] for feature in country["features"]]
    district_regions = [
        (_geometry_collection_bbox((geometry,)), geometry)
        for geometry in district_geometries
    ]
    country_bbox = _geometry_collection_bbox(district_geometries)

    basins = []
    basin_reader = shapefile.Reader(str(basin_shapefile))
    for shape_record in basin_reader.iterShapeRecords():
        if not _bbox_intersects(shape_record.shape.bbox, country_bbox):
            continue
        record = shape_record.record.as_dict()
        geometry = _rounded_geometry(shape_record.shape.__geo_interface__)
        basins.append(
            {
                "basin_id": str(record["HYBAS_ID"]),
                "sub_basin_area_sq_km": float(record["SUB_AREA"]),
                "upstream_area_sq_km": float(record["UP_AREA"]),
                "distance_to_outlet_km": float(record["DIST_SINK"]),
                "basin_order": float(record["ORDER"]),
                "geometry": geometry,
            }
        )

    rivers = []
    river_reader = shapefile.Reader(str(river_shapefile))
    for shape_record in river_reader.iterShapeRecords():
        if not _bbox_intersects(shape_record.shape.bbox, country_bbox, margin=0.1):
            continue
        lines = _shape_lines(shape_record.shape)
        representative_points = [
            point
            for line in lines
            for point in (line[0], line[len(line) // 2], line[-1])
            if line
        ]
        if not any(
            _point_in_country(point[0], point[1], district_regions)
            for point in representative_points
        ):
            continue
        record = shape_record.record.as_dict()
        rivers.append(
            {
                "river_id": str(record["HYRIV_ID"]),
                "average_discharge_cms": float(record["DIS_AV_CMS"]),
                "upstream_area_sq_km": float(record["UPLAND_SKM"]),
                "strahler_order": float(record["ORD_STRA"]),
                "lines": [
                    [[round(x, 5), round(y, 5)] for x, y in line]
                    for line in lines
                ],
            }
        )

    payload = {
        "schema_version": "1.0",
        "source": "HydroBASINS v1c level 6 and HydroRIVERS v1.0",
        "grid_size": 0.1,
        "basins": basins,
        "rivers": rivers,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return {"basins": len(basins), "rivers": len(rivers)}


def point_in_geometry(
    longitude: float, latitude: float, geometry: Mapping[str, object]
) -> bool:
    coordinates = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        return _point_in_polygon(longitude, latitude, coordinates)  # type: ignore[arg-type]
    if geometry["type"] == "MultiPolygon":
        return any(
            _point_in_polygon(longitude, latitude, polygon)
            for polygon in coordinates  # type: ignore[union-attr]
        )
    return False


def _point_in_polygon(
    longitude: float,
    latitude: float,
    polygon: Sequence[Sequence[Sequence[float]]],
) -> bool:
    if not polygon or not _point_in_ring(longitude, latitude, polygon[0]):
        return False
    return not any(
        _point_in_ring(longitude, latitude, hole) for hole in polygon[1:]
    )


def _point_in_ring(
    longitude: float, latitude: float, ring: Sequence[Sequence[float]]
) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > latitude) != (y2 > latitude):
            crossing = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < crossing:
                inside = not inside
        previous = current
    return inside


def _point_segment_distance_km(
    longitude: float, latitude: float, first: Point, second: Point
) -> float:
    longitude_scale = 111.32 * math.cos(math.radians(latitude))
    latitude_scale = 110.57
    point_x = longitude * longitude_scale
    point_y = latitude * latitude_scale
    first_x = first[0] * longitude_scale
    first_y = first[1] * latitude_scale
    second_x = second[0] * longitude_scale
    second_y = second[1] * latitude_scale
    delta_x = second_x - first_x
    delta_y = second_y - first_y
    denominator = delta_x * delta_x + delta_y * delta_y
    if denominator == 0.0:
        return math.hypot(point_x - first_x, point_y - first_y)
    fraction = max(
        0.0,
        min(
            1.0,
            ((point_x - first_x) * delta_x + (point_y - first_y) * delta_y)
            / denominator,
        ),
    )
    return math.hypot(
        point_x - (first_x + fraction * delta_x),
        point_y - (first_y + fraction * delta_y),
    )


def _shape_lines(shape: object) -> List[List[Point]]:
    points = [(float(x), float(y)) for x, y in shape.points]  # type: ignore[attr-defined]
    starts = list(shape.parts) + [len(points)]  # type: ignore[attr-defined]
    return [points[first:last] for first, last in zip(starts, starts[1:])]


def _rounded_geometry(geometry: Mapping[str, object]) -> Mapping[str, object]:
    def rounded(value: object) -> object:
        if isinstance(value, (list, tuple)):
            return [rounded(item) for item in value]
        if isinstance(value, float):
            return round(value, 5)
        return value

    return {"type": geometry["type"], "coordinates": rounded(geometry["coordinates"])}


def _geometry_collection_bbox(
    geometries: Iterable[Mapping[str, object]],
) -> Tuple[float, float, float, float]:
    points: List[Point] = []

    def collect(value: object) -> None:
        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append((float(value[0]), float(value[1])))
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    for geometry in geometries:
        collect(geometry["coordinates"])
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _bbox_intersects(
    first: Sequence[float],
    second: Sequence[float],
    margin: float = 0.0,
) -> bool:
    return not (
        first[2] < second[0] - margin
        or first[0] > second[2] + margin
        or first[3] < second[1] - margin
        or first[1] > second[3] + margin
    )


def _point_in_country(
    longitude: float,
    latitude: float,
    district_regions: Sequence[
        Tuple[Sequence[float], Mapping[str, object]]
    ],
) -> bool:
    return any(
        point_in_geometry(longitude, latitude, geometry)
        for bbox, geometry in district_regions
        if bbox[0] <= longitude <= bbox[2] and bbox[1] <= latitude <= bbox[3]
    )
