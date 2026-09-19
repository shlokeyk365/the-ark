"""Join district geography and pre-event rainfall to historical flood records."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .geography import DistrictGeography, normalize_district
from .population import DistrictPopulation
from .records import FloodEventRecord
from .weather import load_or_fetch_power_rainfall, rainfall_features


def enrich_records(
    records: Iterable[FloodEventRecord],
    geography: Mapping[str, DistrictGeography],
    population: Mapping[str, DistrictPopulation],
    weather_cache: Path,
    weather_end_year: int = 2024,
) -> Iterator[FloodEventRecord]:
    weather_by_district = {}
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
        weather_key = (round(latitude * 2.0) / 2.0, round(longitude * 2.0) / 2.0)
        if weather_key not in weather_by_district:
            weather_by_district[weather_key] = load_or_fetch_power_rainfall(
                latitude,
                longitude,
                weather_end_year,
                weather_cache,
            )
        rainfall = {}
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
            **rainfall,
        )
