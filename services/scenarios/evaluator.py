"""Plan scoring against an immutable derived world state."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from services.routing.engine import build_adjacency, shortest_path

JsonObject = Dict[str, Any]


def _asset_index(assets: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {
        feature["properties"]["id"]: feature["properties"]
        for feature in assets["features"]
    }


def evaluate_plan(
    plan: Mapping[str, Any],
    assets: Mapping[str, Any],
    network: Mapping[str, Any],
    world_state: Mapping[str, Any],
) -> JsonObject:
    """Evaluate one plan using only the supplied frozen world state."""

    asset_by_id = _asset_index(assets)
    edge_states = {
        edge_state["edge_id"]: edge_state
        for edge_state in world_state["edge_states"]
    }
    adjacency = build_adjacency(network, edge_states)
    shelter_assignments: Dict[str, int] = {}
    assignment_results = []
    evacuated = 0
    completion_times = []
    all_assignments_succeeded = True

    for assignment in plan["assignments"]:
        community = asset_by_id[assignment["community_id"]]
        shelter = asset_by_id[assignment["shelter_id"]]
        shelter_assignments[shelter["id"]] = (
            shelter_assignments.get(shelter["id"], 0) + assignment["people"]
        )
        route = shortest_path(adjacency, community["node_id"], shelter["node_id"])
        arrival_minutes = None
        meets_deadline = False
        if route is not None:
            arrival_minutes = (
                assignment["departure_offset_minutes"] + route["travel_minutes"]
            )
            meets_deadline = arrival_minutes <= plan["evaluation_deadline_minutes"]

        if route is not None and meets_deadline:
            evacuated += assignment["people"]
            completion_times.append(arrival_minutes)
        else:
            all_assignments_succeeded = False

        assignment_results.append(
            {
                **assignment,
                "route": route,
                "arrival_minutes": arrival_minutes,
                "meets_deadline": meets_deadline,
                "people_evacuated": assignment["people"] if meets_deadline else 0,
            }
        )

    shelter_overload = sum(
        max(0, assigned - int(asset_by_id[shelter_id]["capacity"]))
        for shelter_id, assigned in shelter_assignments.items()
    )
    communities = {
        feature["properties"]["id"]: feature["properties"]
        for feature in assets["features"]
        if feature["properties"]["asset_type"] == "community"
    }
    access_states = world_state["community_access"]
    people_isolated = sum(
        communities[access["community_id"]]["population"]
        for access in access_states
        if access["isolated"]
    )
    hospital_accessible_communities = sum(
        1 for access in access_states if access["hospital_accessible"]
    )
    critical_routes_lost = sum(
        1
        for state in world_state["edge_states"]
        if state["critical"] and state["status"] == "closed"
    )

    metrics = {
        "people_isolated": people_isolated,
        "people_evacuated_by_deadline": evacuated,
        "evacuation_completion_minutes": (
            max(completion_times) if completion_times else None
        ),
        "critical_routes_lost": critical_routes_lost,
        "hospital_accessible": hospital_accessible_communities == len(communities),
        "hospital_accessible_communities": hospital_accessible_communities,
        "shelter_overload": shelter_overload,
        "plan_viable": all_assignments_succeeded and shelter_overload == 0,
    }

    return {
        "result_id": f"{plan['plan_id']}:{world_state['world_state_version']}",
        "plan_id": plan["plan_id"],
        "plan_name": plan["name"],
        "source_world_state_version": world_state["world_state_version"],
        "status": "current",
        "calculated_at": world_state["calculated_at"],
        "assumptions": plan["assumptions"],
        "invalidation_reason": None,
        "metrics": metrics,
        "assignment_results": assignment_results,
    }
