"""Deterministic graph derivation for the Kantipur MVP."""

from __future__ import annotations

import heapq
from collections import defaultdict
from math import inf
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

JsonObject = Dict[str, Any]
Adjacency = Mapping[str, List[Tuple[str, str, float]]]


def _conditions_by_edge(frame: Mapping[str, Any]) -> Dict[str, float]:
    return {
        condition["edge_id"]: float(condition["flood_depth_m"])
        for condition in frame["edge_conditions"]
    }


def _forced_changes(events: Iterable[Mapping[str, Any]]) -> Dict[str, JsonObject]:
    changes: Dict[str, JsonObject] = {}
    field_changes: Dict[str, JsonObject] = {}
    for event in events:
        for change in event["changes"]:
            is_field = event.get("event_type") == "field_intelligence"
            if change["change_type"] == "clear_field_restriction" and is_field:
                field_changes.pop(change["edge_id"], None)
                continue
            if change["change_type"] in {
                "force_close_edge",
                "force_restrict_edge",
            }:
                target = field_changes if is_field else changes
                target[change["edge_id"]] = {
                    "event_id": event["event_id"],
                    "reason": change["reason"],
                    "status": (
                        "closed"
                        if change["change_type"] == "force_close_edge"
                        else "restricted"
                    ),
                }
    for edge_id, change in field_changes.items():
        if edge_id not in changes or changes[edge_id]["status"] != "closed":
            changes[edge_id] = change
    return changes


def derive_edge_states(
    network: Mapping[str, Any],
    frame: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]] = (),
) -> Dict[str, JsonObject]:
    """Translate one flood frame plus active events into edge states."""

    conditions = _conditions_by_edge(frame)
    forced_changes = _forced_changes(events)
    states: Dict[str, JsonObject] = {}

    for feature in network["features"]:
        edge = feature["properties"]
        edge_id = edge["id"]
        depth = conditions[edge_id]
        event = forced_changes.get(edge_id)

        if event is not None and (event["status"] == "closed" or depth < float(edge["closure_depth_m"])):
            status = event["status"]
            closure_reason = event["reason"]
            travel_minutes = (
                None
                if status == "closed"
                else float(edge["baseline_travel_minutes"])
                * float(edge["penalty_multiplier"])
            )
            event_id: Optional[str] = event["event_id"]
        elif depth >= float(edge["closure_depth_m"]):
            status = "closed"
            closure_reason = (
                f"Flood depth {depth:.2f} m meets or exceeds "
                f"{float(edge['closure_depth_m']):.2f} m closure threshold"
            )
            travel_minutes = None
            event_id = None
        elif depth >= float(edge["penalty_depth_m"]):
            status = "restricted"
            closure_reason = None
            travel_minutes = float(edge["baseline_travel_minutes"]) * float(
                edge["penalty_multiplier"]
            )
            event_id = None
        else:
            status = "open"
            closure_reason = None
            travel_minutes = float(edge["baseline_travel_minutes"])
            event_id = None

        states[edge_id] = {
            "edge_id": edge_id,
            "edge_type": edge["edge_type"],
            "status": status,
            "closure_reason": closure_reason,
            "flood_depth_m": depth,
            "baseline_travel_minutes": float(edge["baseline_travel_minutes"]),
            "penalty_depth_m": float(edge["penalty_depth_m"]),
            "closure_depth_m": float(edge["closure_depth_m"]),
            "penalty_multiplier": float(edge["penalty_multiplier"]),
            "effective_travel_minutes": travel_minutes,
            "source_frame_id": frame["frame_id"],
            "originating_event_id": event_id,
            "critical": bool(edge["critical"]),
        }

    return states


def build_adjacency(
    network: Mapping[str, Any], edge_states: Mapping[str, Mapping[str, Any]]
) -> Dict[str, List[Tuple[str, str, float]]]:
    """Build a traversable adjacency list from derived edge states."""

    adjacency: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)
    for feature in network["features"]:
        edge = feature["properties"]
        state = edge_states[edge["id"]]
        if state["status"] == "closed":
            continue

        minutes = float(state["effective_travel_minutes"])
        source = edge["from_node_id"]
        destination = edge["to_node_id"]
        adjacency[source].append((destination, edge["id"], minutes))
        if edge["bidirectional"]:
            adjacency[destination].append((source, edge["id"], minutes))

    return dict(adjacency)


def shortest_path(
    adjacency: Adjacency, source_node_id: str, destination_node_id: str
) -> Optional[JsonObject]:
    """Find the deterministic shortest safe path with Dijkstra's algorithm."""

    queue: List[Tuple[float, str, List[str], List[str]]] = [
        (0.0, source_node_id, [source_node_id], [])
    ]
    best: Dict[str, float] = {source_node_id: 0.0}

    while queue:
        minutes, node_id, node_path, edge_path = heapq.heappop(queue)
        if minutes > best.get(node_id, inf):
            continue
        if node_id == destination_node_id:
            return {
                "source_node_id": source_node_id,
                "destination_node_id": destination_node_id,
                "node_ids": node_path,
                "edge_ids": edge_path,
                "travel_minutes": minutes,
            }

        for neighbor, edge_id, edge_minutes in sorted(adjacency.get(node_id, [])):
            total = minutes + edge_minutes
            if total < best.get(neighbor, inf):
                best[neighbor] = total
                heapq.heappush(
                    queue,
                    (total, neighbor, node_path + [neighbor], edge_path + [edge_id]),
                )

    return None


def _assets_by_type(
    assets: Mapping[str, Any], asset_type: str
) -> List[Mapping[str, Any]]:
    return [
        feature["properties"]
        for feature in assets["features"]
        if feature["properties"]["asset_type"] == asset_type
    ]


def compute_community_access(
    assets: Mapping[str, Any],
    network: Mapping[str, Any],
    edge_states: Mapping[str, Mapping[str, Any]],
) -> List[JsonObject]:
    """Calculate separate shelter and hospital access for every community."""

    adjacency = build_adjacency(network, edge_states)
    communities = _assets_by_type(assets, "community")
    shelters = [asset for asset in _assets_by_type(assets, "shelter") if asset["open"]]
    hospitals = [asset for asset in _assets_by_type(assets, "hospital") if asset["open"]]
    hospital = hospitals[0]
    access_states: List[JsonObject] = []

    for community in communities:
        shelter_routes = []
        for shelter in shelters:
            route = shortest_path(adjacency, community["node_id"], shelter["node_id"])
            if route is not None:
                shelter_routes.append(
                    {
                        "shelter_id": shelter["id"],
                        "route": route,
                    }
                )

        hospital_route = shortest_path(
            adjacency, community["node_id"], hospital["node_id"]
        )
        access_states.append(
            {
                "community_id": community["id"],
                "reachable_shelter_ids": sorted(
                    route["shelter_id"] for route in shelter_routes
                ),
                "shelter_routes": shelter_routes,
                "hospital_accessible": hospital_route is not None,
                "hospital_route": hospital_route,
                "isolated": not shelter_routes and hospital_route is None,
            }
        )

    return access_states


def calculate_time_to_isolation(
    assets: Mapping[str, Any],
    network: Mapping[str, Any],
    frames: Iterable[Mapping[str, Any]],
    events: Iterable[Mapping[str, Any]] = (),
) -> Dict[str, Optional[float]]:
    """Return the first frame time at which each community becomes isolated.

    Events are applied only to the frames at or after their effective hour, so
    an injected disruption pulls isolation forward instead of being ignored.
    """

    community_ids = [
        asset["id"] for asset in _assets_by_type(assets, "community")
    ]
    times: Dict[str, Optional[float]] = {
        community_id: None for community_id in community_ids
    }
    event_list = list(events)

    for frame in sorted(frames, key=lambda item: item["simulation_time_hours"]):
        active = [
            event
            for event in event_list
            if event["effective_at_hours"] <= frame["simulation_time_hours"]
        ]
        states = derive_edge_states(network, frame, active)
        for access in compute_community_access(assets, network, states):
            community_id = access["community_id"]
            if access["isolated"] and times[community_id] is None:
                times[community_id] = float(frame["simulation_time_hours"])

    return times
