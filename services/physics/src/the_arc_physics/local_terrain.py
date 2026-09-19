"""Location-level elevation and relief from the Open-Meteo Elevation API."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Iterable, Mapping, Tuple
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


Terrain = Tuple[float, float]


def load_or_fetch_local_terrain(
    points: Iterable[Tuple[float, float]], cache_path: Path
) -> Mapping[str, Terrain]:
    unique_points = sorted({(round(lat, 4), round(lon, 4)) for lat, lon in points})
    cached: Dict[str, Terrain] = {}
    if cache_path.exists():
        cached = {
            key: (float(value[0]), float(value[1]))
            for key, value in json.loads(
                cache_path.read_text(encoding="utf-8")
            ).items()
        }
    missing = [point for point in unique_points if terrain_key(*point) not in cached]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(missing), 20):
        point_batch = missing[start : start + 20]
        sample_batch = []
        for latitude, longitude in point_batch:
            offset = 0.01
            sample_batch.extend(
                [
                    (latitude, longitude),
                    (latitude + offset, longitude),
                    (latitude - offset, longitude),
                    (latitude, longitude + offset),
                    (latitude, longitude - offset),
                ]
            )
        query = urlencode(
            {
                "latitude": ",".join(
                    str(latitude) for latitude, _ in sample_batch
                ),
                "longitude": ",".join(
                    str(longitude) for _, longitude in sample_batch
                ),
            }
        )
        payload = _get_with_retry(
            f"https://api.open-meteo.com/v1/elevation?{query}"
        )
        elevations = [float(value) for value in payload["elevation"]]
        for index, point in enumerate(point_batch):
            samples = elevations[index * 5 : index * 5 + 5]
            cached[terrain_key(*point)] = (
                round(samples[0], 1),
                round(max(samples) - min(samples), 1),
            )
        cache_path.write_text(
            json.dumps(cached, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        time.sleep(0.75)
    return cached


def terrain_key(latitude: float, longitude: float) -> str:
    return f"{latitude:.4f},{longitude:.4f}"


def _get_with_retry(url: str) -> Mapping[str, object]:
    for attempt in range(6):
        try:
            with urlopen(url, timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code != 429 or attempt == 5:
                raise
            retry_after = error.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else min(30.0, 2.0 ** attempt)
            time.sleep(delay)
    raise RuntimeError("unreachable elevation retry state")
