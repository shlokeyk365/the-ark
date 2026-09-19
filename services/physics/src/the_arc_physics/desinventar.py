"""Parser for the UNDRR DesInventar Nepal export."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, Iterable, Iterator, Union

from .records import FloodEventRecord


def read_desinventar_floods(source: Path) -> Iterator[FloodEventRecord]:
    """Yield normalized FLOOD records from a DesInventar XML or ZIP export."""

    if source.suffix.lower() == ".zip":
        if not zipfile.is_zipfile(source):
            raise ValueError(f"not a valid ZIP archive: {source}")
        with zipfile.ZipFile(source) as archive:
            members = [name for name in archive.namelist() if name.endswith(".xml")]
            if len(members) != 1:
                raise ValueError("DesInventar archive must contain exactly one XML export")
            with archive.open(members[0]) as handle:
                yield from _parse_xml(handle)
        return

    with source.open("rb") as handle:
        yield from _parse_xml(handle)


def _parse_xml(handle: object) -> Iterator[FloodEventRecord]:
    stack = []
    for event, element in ET.iterparse(handle, events=("start", "end")):
        if event == "start":
            stack.append(element.tag)
            continue

        if element.tag == "TR" and len(stack) >= 2 and stack[-2] == "fichas":
            values = {child.tag: (child.text or "").strip() for child in element}
            if values.get("evento", "").upper() == "FLOOD":
                record = _to_record(values)
                if record is not None:
                    yield record
            element.clear()
        stack.pop()


def _to_record(values: Dict[str, str]) -> Union[FloodEventRecord, None]:
    year = _integer(values.get("fechano"))
    month = _integer(values.get("fechames"))
    if year <= 0 or not 1 <= month <= 12:
        return None
    return FloodEventRecord(
        event_id=(
            f"desinventar-{values.get('uu_id')}"
            if values.get("uu_id")
            else f"desinventar-{values.get('serial') or values.get('clave')}"
        ),
        source="UNDRR DesInventar Nepal",
        year=year,
        month=month,
        day=max(0, _integer(values.get("fechadia"))),
        region=values.get("name0") or "UNKNOWN",
        district=values.get("name1") or "UNKNOWN",
        municipality=values.get("name2") or "UNKNOWN",
        cause=values.get("causa") or "UNKNOWN",
        deaths=_integer(values.get("muertos")),
        missing=_integer(values.get("desaparece")),
        injured=_integer(values.get("heridos")),
        people_affected=_integer(values.get("afectados")),
        houses_destroyed=_integer(values.get("vivdest")),
        houses_affected=_integer(values.get("vivafec")),
        evacuated=_integer(values.get("evacuados")),
        roads_damaged_km=_number(values.get("kmvias")),
        transport_affected=_integer(values.get("transporte")) > 0,
    )


def _integer(value: Union[str, None]) -> int:
    try:
        return max(0, int(float(value or 0)))
    except ValueError:
        return 0


def _number(value: Union[str, None]) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except ValueError:
        return 0.0
