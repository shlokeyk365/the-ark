"""Deterministic MVP extractor. Replace behind this contract with an LLM later."""

import re
from dataclasses import dataclass

from ark_api.intelligence.models import (
    AssetMatch,
    AssetType,
    ChangeType,
    ClaimType,
    ExtractedClaim,
    ProposedStateChange,
)
from ark_api.simulation.models import WorldState

_BLOCKED = re.compile(
    r"\b(blocked|closed|impassable|unusable|cannot pass|can't pass|turning around)\b",
    re.IGNORECASE,
)
_FLOOD = re.compile(
    r"\b(flood(?:ed|ing)?|underwater|water over|water on|inundat(?:ed|ion))\b",
    re.IGNORECASE,
)
_RISING = re.compile(r"\b(rising|getting higher|increasing)\b", re.IGNORECASE)
_DEPTH = re.compile(
    r"(?P<value>\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s*(?P<unit>feet|foot|ft|meters?|metres?|m)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
}


@dataclass(frozen=True)
class ExtractionResult:
    claim: ExtractedClaim
    change: ProposedStateChange
    extraction_confidence: float


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def _route_display_name(world: WorldState, route_id: str) -> str:
    route = next(route for route in world.routes if route.id == route_id)
    nodes = {node.id: node.name for node in world.nodes}
    return f"{nodes[route.origin_node_id]} to {nodes[route.destination_node_id]}"


def _match_route(message: str, world: WorldState) -> AssetMatch | None:
    lowered = message.lower()
    nodes = {node.id: node for node in world.nodes}
    candidates: list[tuple[float, str]] = []
    for route in world.routes:
        if route.id.lower() in lowered:
            candidates.append((1.0, route.id))
            continue
        origin = nodes[route.origin_node_id]
        destination = nodes[route.destination_node_id]
        origin_tokens = _tokens(origin.name) | _tokens(origin.id)
        destination_tokens = _tokens(destination.name) | _tokens(destination.id)
        message_tokens = _tokens(message)
        origin_hit = bool(origin_tokens & message_tokens)
        destination_hit = bool(destination_tokens & message_tokens)
        if origin_hit and destination_hit:
            candidates.append((0.94, route.id))
        elif origin_hit or destination_hit:
            candidates.append((0.72, route.id))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    best_score, best_id = candidates[0]
    if sum(score == best_score for score, _ in candidates) > 1:
        best_score = min(best_score, 0.55)
    return AssetMatch(
        asset_type=AssetType.ROUTE,
        asset_id=best_id,
        display_name=_route_display_name(world, best_id),
        confidence=best_score,
    )


def _match_node(message: str, world: WorldState) -> AssetMatch | None:
    lowered = message.lower()
    matches = [
        node
        for node in world.nodes
        if node.id.lower() in lowered or node.name.lower() in lowered
    ]
    if len(matches) != 1:
        return None
    node = matches[0]
    return AssetMatch(
        asset_type=AssetType.NODE,
        asset_id=node.id,
        display_name=node.name,
        confidence=0.9,
    )


def _water_depth_m(message: str) -> float | None:
    match = _DEPTH.search(message)
    if not match:
        return None
    raw_value = match.group("value").lower()
    value = float(raw_value) if raw_value[0].isdigit() else _NUMBER_WORDS[raw_value]
    unit = match.group("unit").lower()
    return round(value * 0.3048, 3) if unit in {"feet", "foot", "ft"} else value


def extract_field_message(message: str, world: WorldState) -> ExtractionResult:
    blocked = bool(_BLOCKED.search(message))
    flooded = bool(_FLOOD.search(message))
    route_match = _match_route(message, world)
    node_match = None if route_match else _match_node(message, world)
    asset_match = route_match or node_match
    depth = _water_depth_m(message)
    trend = "rising" if _RISING.search(message) else None

    if route_match and blocked:
        claim_type = ClaimType.ROUTE_BLOCKED
        summary = f"Reported route blockage at {route_match.display_name}."
        change_type = ChangeType.CLOSE_ROUTE
        confidence = 0.94
    elif route_match and flooded:
        claim_type = ClaimType.ROUTE_FLOODED
        summary = f"Reported flooding on {route_match.display_name}."
        change_type = ChangeType.RESTRICT_ROUTE
        confidence = 0.88
    elif node_match and flooded:
        claim_type = ClaimType.FLOOD_OBSERVED
        summary = f"Reported flooding at {node_match.display_name}."
        change_type = ChangeType.ADD_FLOOD_HAZARD
        confidence = 0.84
    else:
        claim_type = ClaimType.UNKNOWN
        summary = "The message could not be converted into a supported state change."
        change_type = ChangeType.NONE
        confidence = 0.35

    return ExtractionResult(
        claim=ExtractedClaim(
            claim_type=claim_type,
            summary=summary,
            asset_match=asset_match,
            water_depth_m=depth,
            trend=trend,
        ),
        change=ProposedStateChange(
            change_type=change_type,
            target_id=asset_match.asset_id if asset_match else None,
            reason=summary,
        ),
        extraction_confidence=confidence,
    )
