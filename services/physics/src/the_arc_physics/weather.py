"""Historical rainfall feature extraction using NASA POWER daily data."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from statistics import mean
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen


POWER_START = date(1981, 1, 1)
POWER_CACHE_PATTERN = re.compile(
    r"rain_([+-]\d+(?:\.\d+)?)_([+-]\d+(?:\.\d+)?)_1981_\d{4}\.json$"
)


def power_grid(latitude: float, longitude: float) -> Tuple[float, float]:
    """Collapse nearby districts onto NASA POWER's approximately 0.5° grid."""

    return round(latitude * 2.0) / 2.0, round(longitude * 2.0) / 2.0


def load_or_fetch_power_rainfall(
    latitude: float,
    longitude: float,
    end_year: int,
    cache_dir: Path,
) -> Dict[str, float]:
    grid_latitude, grid_longitude = power_grid(latitude, longitude)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / (
        f"rain_{grid_latitude:+05.1f}_{grid_longitude:+06.1f}_1981_{end_year}.json"
    )
    if cache_path.exists():
        return {
            key: float(value)
            for key, value in json.loads(cache_path.read_text(encoding="utf-8")).items()
        }

    query = urlencode(
        {
            "parameters": "PRECTOTCORR",
            "community": "AG",
            "longitude": grid_longitude,
            "latitude": grid_latitude,
            "start": "19810101",
            "end": f"{end_year}1231",
            "format": "JSON",
            "time-standard": "UTC",
        }
    )
    url = f"https://power.larc.nasa.gov/api/temporal/daily/point?{query}"
    with urlopen(url, timeout=180) as response:
        payload = json.load(response)
    raw_values = payload["properties"]["parameter"]["PRECTOTCORR"]
    values = {
        key: float(value)
        for key, value in raw_values.items()
        if value is not None and float(value) > -900.0
    }
    cache_path.write_text(json.dumps(values, separators=(",", ":")), encoding="utf-8")
    return values


def rainfall_features(
    event_date: date,
    daily_rainfall: Mapping[str, float],
) -> Mapping[str, Optional[float]]:
    windows = {}
    for days in (1, 3, 7, 30):
        values = _window_values(event_date, daily_rainfall, days)
        windows[days] = round(sum(values), 3) if values is not None else None

    seven_day_values = _window_values(event_date, daily_rainfall, 7)
    rainy_days = (
        float(sum(value >= 1.0 for value in seven_day_values))
        if seven_day_values is not None
        else None
    )
    normal = _monthly_daily_normal(event_date.month, daily_rainfall)
    anomaly = None
    if windows[7] is not None and normal is not None and normal > 0.0:
        anomaly = round(windows[7] / (7.0 * normal), 3)
    return {
        "rainfall_1d_mm": windows[1],
        "rainfall_3d_mm": windows[3],
        "rainfall_7d_mm": windows[7],
        "rainfall_30d_mm": windows[30],
        "rainy_days_7d": rainy_days,
        "rainfall_7d_anomaly": anomaly,
    }


def load_cached_power_grids(
    cache_dir: Path,
) -> Mapping[Tuple[float, float], Mapping[str, float]]:
    grids = {}
    for path in sorted(cache_dir.glob("rain_*_1981_*.json")):
        match = POWER_CACHE_PATTERN.match(path.name)
        if match is None:
            continue
        grids[(float(match.group(1)), float(match.group(2)))] = {
            key: float(value)
            for key, value in json.loads(path.read_text(encoding="utf-8")).items()
        }
    return grids


def basin_rainfall_features(
    event_date: date,
    rainfall_grids: Sequence[Mapping[str, float]],
) -> Mapping[str, Optional[float]]:
    result: Dict[str, Optional[float]] = {}
    for days in (1, 3, 7):
        totals = []
        for daily_rainfall in rainfall_grids:
            values = _window_values(event_date, daily_rainfall, days)
            if values is not None:
                totals.append(sum(values))
        result[f"basin_rainfall_{days}d_mean_mm"] = (
            round(mean(totals), 3) if totals else None
        )
        result[f"basin_rainfall_{days}d_max_mm"] = (
            round(max(totals), 3) if totals else None
        )
    mean_3d = result["basin_rainfall_3d_mean_mm"]
    max_3d = result["basin_rainfall_3d_max_mm"]
    result["basin_rainfall_3d_spread_mm"] = (
        round(max_3d - mean_3d, 3)
        if max_3d is not None and mean_3d is not None
        else None
    )
    return result


def _window_values(
    event_date: date,
    daily_rainfall: Mapping[str, float],
    days: int,
) -> Optional[Sequence[float]]:
    keys = [
        (event_date - timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range(days)
    ]
    if any(key not in daily_rainfall for key in keys):
        return None
    return [daily_rainfall[key] for key in keys]


def _monthly_daily_normal(
    month: int,
    daily_rainfall: Mapping[str, float],
) -> Optional[float]:
    values = [
        value
        for key, value in daily_rainfall.items()
        if 1981 <= int(key[:4]) <= 2010 and int(key[4:6]) == month
    ]
    return sum(values) / len(values) if values else None
