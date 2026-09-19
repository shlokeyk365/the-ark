"""Join district geography and pre-event rainfall to historical flood records."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .geography import DistrictGeography, normalize_district
from .hydrography import HydrologyIndex
from .local_terrain import load_or_fetch_local_terrain, terrain_key
from .population import DistrictPopulation
from .records import FloodEventRecord
from .weather import (
    basin_rainfall_features,
    load_cached_power_grids,
    load_or_fetch_power_rainfall,
    rainfall_features,
)


def enrich_records(
    records: Iterable[FloodEventRecord],
    geography: Mapping[str, DistrictGeography],
    population: Mapping[str, DistrictPopulation],
    weather_cache: Path,
    hydrology: HydrologyIndex | None = None,
    terrain_cache: Path | None = None,
    weather_end_year: int = 2024,
) -> Iterator[FloodEventRecord]:
    records = tuple(records)
    resolved_coordinates = []
    for record in records:
        district = geography.get(normalize_district(record.district))
        if district is None:
            continue
        resolved_coordinates.append(
            (
                record.latitude if record.latitude is not None else district.latitude,
                record.longitude if record.longitude is not None else district.longitude,
            )
        )
    terrain = (
        load_or_fetch_local_terrain(resolved_coordinates, terrain_cache)
        if terrain_cache is not None
        else {}
    )
    weather_by_district = {}
    hydrology_by_point = {}
    basin_weather = {}
    if hydrology is not None:
        for (grid_latitude, grid_longitude), daily_rainfall in (
            load_cached_power_grids(weather_cache).items()
        ):
            basin = hydrology.basin_at(grid_latitude, grid_longitude)
            if basin is not None:
                basin_weather.setdefault(basin.basin_id, []).append(daily_rainfall)
    for record in records:
        district = geography.get(normalize_district(record.district))
        district_population = population.get(normalize_district(record.district))
        if district is None:
            yield record
            continue
        latitude = record.latitude if record.latitude is not None else district.latitude
        longitude = (
            record.longitude if record.longitude is not None else district.longitude
        )
        point_key = terrain_key(latitude, longitude)
        local_elevation, local_relief = terrain.get(point_key, (None, None))
        if hydrology is not None and point_key not in hydrology_by_point:
            hydrology_by_point[point_key] = hydrology.features_at(latitude, longitude)
        hydro = hydrology_by_point.get(point_key)
        weather_key = (round(latitude * 2.0) / 2.0, round(longitude * 2.0) / 2.0)
        if weather_key not in weather_by_district:
            weather_by_district[weather_key] = load_or_fetch_power_rainfall(
                latitude,
                longitude,
                weather_end_year,
                weather_cache,
            )
        rainfall = {}
        basin_rainfall = {}
        if record.day > 0 and record.year >= 1981:
            try:
                event_date = date(record.year, record.month, record.day)
            except ValueError:
                event_date = None
            if event_date is not None:
                rainfall = rainfall_features(
                    event_date,
                    weather_by_district[weather_key],
                )
                rainfall_grids = (
                    basin_weather.get(hydro.basin_id, []) if hydro else []
                )
                if not rainfall_grids:
                    rainfall_grids = [weather_by_district[weather_key]]
                basin_rainfall = basin_rainfall_features(
                    event_date,
                    rainfall_grids,
                )
        yield replace(
            record,
            latitude=latitude,
            longitude=longitude,
            district_area_sq_km=district.area_sq_km,
            elevation_m=district.elevation_m,
            terrain_relief_m=district.terrain_relief_m,
            households_2011=(
                float(district_population.households_2011)
                if district_population is not None
                else None
            ),
            population_2011=(
                float(district_population.population_2011)
                if district_population is not None
                else None
            ),
            population_density_2011=(
                district_population.population_2011 / district.area_sq_km
                if district_population is not None and district.area_sq_km > 0.0
                else None
            ),
            basin_id=hydro.basin_id if hydro else None,
            sub_basin_area_sq_km=(hydro.sub_basin_area_sq_km if hydro else None),
            upstream_area_sq_km=(hydro.upstream_area_sq_km if hydro else None),
            distance_to_outlet_km=(hydro.distance_to_outlet_km if hydro else None),
            basin_order=(hydro.basin_order if hydro else None),
            nearest_river_distance_km=(
                hydro.nearest_river_distance_km if hydro else None
            ),
            river_average_discharge_cms=(
                hydro.river_average_discharge_cms if hydro else None
            ),
            river_upstream_area_sq_km=(
                hydro.river_upstream_area_sq_km if hydro else None
            ),
            river_strahler_order=(hydro.river_strahler_order if hydro else None),
            local_elevation_m=local_elevation,
            local_relief_m=local_relief,
            **rainfall,
            **basin_rainfall,
        )
