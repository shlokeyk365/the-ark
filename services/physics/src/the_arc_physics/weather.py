"""Historical rainfall feature extraction using NASA POWER daily data."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen


POWER_START = date(1981, 1, 1)


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
