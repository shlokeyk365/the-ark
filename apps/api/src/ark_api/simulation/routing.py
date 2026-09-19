"""Deterministic routing using authoritative route availability only."""

from dataclasses import dataclass
from fractions import Fraction
from heapq import heappop, heappush
from math import ceil, isfinite

from ark_api.simulation.models import Capability, RouteStatus, WorldState


class NoRouteError(ValueError):
    """No capability-valid path survives its entire traversal."""


@dataclass(frozen=True)
class RoutePath:
    node_ids: tuple[str, ...]
    route_ids: tuple[str, ...]
    # One absolute arrival minute per traversed edge.
    arrival_minutes: tuple[int, ...]
    total_travel_minutes: int
    arrival_minute: int


def shortest_path(
    world: WorldState,
    origin_id: str,
    target_id: str,
    departure_minute: int,
    capabilities: set[Capability] | frozenset[Capability],
    speed_multiplier: float = 1.0,
) -> RoutePath:
    """Minimize sum(ceil(base_travel_minutes / speed_multiplier)).

    Rounding is per edge, using exact decimal-rational speed, minimum one minute.
    Equal totals use lexicographic route-ID sequences, then node-ID sequences.
    allowed_capabilities lists alternatives; empty means unrestricted. Restricted
    edges retain these restrictions; CLOSED edges are never usable. An edge must
    be exited strictly BEFORE closure_minute (arrival at closure is rejected).
    Waiting cannot improve a path because edges only close, never reopen.
    """
    if type(departure_minute) is not int or departure_minute < 0:
        raise ValueError("departure_minute must be a nonnegative integer")
    if not isfinite(speed_multiplier) or speed_multiplier <= 0:
        raise ValueError("speed_multiplier must be positive and finite")
    node_ids = {node.id for node in world.nodes}
    if origin_id not in node_ids or target_id not in node_ids:
        raise NoRouteError("route endpoint does not exist")
    adjacency = {node_id: [] for node_id in node_ids}
    for edge in sorted(world.routes, key=lambda edge: edge.id):
        if edge.status == RouteStatus.CLOSED:
            continue
        if edge.allowed_capabilities and not edge.allowed_capabilities & capabilities:
            continue
        cost = max(
            1,
            ceil(Fraction(edge.base_travel_minutes) / Fraction(str(speed_multiplier))),
        )
        adjacency[edge.origin_node_id].append((edge.destination_node_id, edge, cost))
        if edge.bidirectional:
            adjacency[edge.destination_node_id].append(
                (edge.origin_node_id, edge, cost)
            )
    # Heap order is arrival, route IDs, node IDs; no unordered iteration affects it.
    queue = [(departure_minute, (), (origin_id,), ())]
    best = {}
    while queue:
        arrival, routes, nodes, times = heappop(queue)
        node = nodes[-1]
        key = (arrival, routes, nodes)
        if node in best and best[node] <= key:
            continue
        best[node] = key
        if node == target_id:
            return RoutePath(nodes, routes, times, arrival - departure_minute, arrival)
        for destination, edge, cost in adjacency[node]:
            end = arrival + cost
            if edge.closure_minute is not None and end >= edge.closure_minute:
                continue
            if destination not in nodes:
                heappush(
                    queue,
                    (end, (*routes, edge.id), (*nodes, destination), (*times, end)),
                )
    raise NoRouteError(f"no route from {origin_id!r} to {target_id!r}")


CIVILIAN_CAPABILITIES = frozenset({Capability.ROAD_TRAVEL, Capability.FOOT_TRAVEL})


def can_reach_safety(
    world: WorldState,
    node_id: str,
    minute: int,
    capabilities: set[Capability] | frozenset[Capability],
    speed_multiplier: float = 1.0,
) -> bool:
    for node in sorted(world.nodes, key=lambda node: node.id):
        if not node.is_safe_zone:
            continue
        try:
            shortest_path(
                world, node_id, node.id, minute, capabilities, speed_multiplier
            )
            return True
        except NoRouteError:
            pass
    return False
