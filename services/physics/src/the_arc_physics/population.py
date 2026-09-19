"""Read district population exposure derived from Nepal's 2011 census."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from .geography import normalize_district


@dataclass(frozen=True)
class DistrictPopulation:
    households_2011: int
    population_2011: int


def read_district_population(path: Path) -> Dict[str, DistrictPopulation]:
    rows = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            rows[normalize_district(raw["district"])] = DistrictPopulation(
                households_2011=int(raw["households_2011"]),
                population_2011=int(raw["population_2011"]),
            )
    return rows
