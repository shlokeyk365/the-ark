"""Cross-file validation for deterministic scenario fixtures."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


class ScenarioValidationError(ValueError):
    """Raised when scenario fixtures contradict their shared contract."""


def _assert_unique(values: Iterable[str], label: str) -> set[str]:
    values_list = list(values)
    if len(values_list) != len(set(values_list)):
        raise ScenarioValidationError(f"Duplicate {label} detected")
    return set(values_list)


def validate_scenario_fixtures(
    manifest: Mapping[str, Any],
    assets: Mapping[str, Any],
    network: Mapping[str, Any],
    flood_frames: Mapping[str, Any],
    plans: Mapping[str, Any],
    event_stream: Mapping[str, Any],
    context_boundaries: Mapping[str, Any],
    impact_prior: Mapping[str, Any],
    prediction_pings: Mapping[str, Any],
) -> None:
    scenario_id = manifest["scenario_id"]
    documents = (
        assets,
        network,
        flood_frames,
        plans,
        event_stream,
        context_boundaries,
    )
    if any(document["scenario_id"] != scenario_id for document in documents):
        raise ScenarioValidationError("All fixture files must share one scenario_id")

    asset_properties = [feature["properties"] for feature in assets["features"]]
    asset_ids = _assert_unique((asset["id"] for asset in asset_properties), "asset ID")
    node_ids = _assert_unique(
        (
            asset["node_id"]
            for asset in asset_properties
            if "node_id" in asset
        ),
        "asset node ID",
    )

    edges = [feature["properties"] for feature in network["features"]]
    edge_ids = _assert_unique((edge["id"] for edge in edges), "edge ID")
    graph_nodes = {
        node_id
        for edge in edges
        for node_id in (edge["from_node_id"], edge["to_node_id"])
    }
    if not node_ids.issubset(graph_nodes):
        raise ScenarioValidationError("Every routed asset node must exist in the graph")

    for edge in edges:
        if edge["penalty_depth_m"] < 0 or edge["closure_depth_m"] < 0:
            raise ScenarioValidationError(f"Negative threshold on {edge['id']}")
        if edge["penalty_depth_m"] >= edge["closure_depth_m"]:
            raise ScenarioValidationError(f"Contradictory thresholds on {edge['id']}")
        if edge["baseline_travel_minutes"] <= 0 or edge["penalty_multiplier"] < 1:
            raise ScenarioValidationError(f"Invalid travel rule on {edge['id']}")

    frames = flood_frames["frames"]
    frame_ids = _assert_unique((frame["frame_id"] for frame in frames), "frame ID")
    del frame_ids
    frame_times = [frame["simulation_time_hours"] for frame in frames]
    if frame_times != sorted(frame_times) or len(frame_times) != len(set(frame_times)):
        raise ScenarioValidationError("Flood frames must use increasing unique times")
    for frame in frames:
        condition_ids = _assert_unique(
            (condition["edge_id"] for condition in frame["edge_conditions"]),
            f"edge condition in {frame['frame_id']}",
        )
        if condition_ids != edge_ids:
            raise ScenarioValidationError(
                f"{frame['frame_id']} must contain one reading for every edge"
            )
        if any(condition["flood_depth_m"] < 0 for condition in frame["edge_conditions"]):
            raise ScenarioValidationError(
                f"{frame['frame_id']} contains a negative flood depth"
            )

    communities = {
        asset["id"]: asset
        for asset in asset_properties
        if asset["asset_type"] == "community"
    }
    shelters = {
        asset["id"]: asset
        for asset in asset_properties
        if asset["asset_type"] == "shelter"
    }
    _assert_unique((plan["plan_id"] for plan in plans["plans"]), "plan ID")
    for plan in plans["plans"]:
        assigned_by_community: dict[str, int] = {}
        for assignment in plan["assignments"]:
            community_id = assignment["community_id"]
            shelter_id = assignment["shelter_id"]
            if community_id not in communities or shelter_id not in shelters:
                raise ScenarioValidationError(
                    f"Unknown assignment reference in {plan['plan_id']}"
                )
            assigned_by_community[community_id] = (
                assigned_by_community.get(community_id, 0) + assignment["people"]
            )
        for community_id, people in assigned_by_community.items():
            if people > communities[community_id]["population"]:
                raise ScenarioValidationError(
                    f"{plan['plan_id']} over-assigns {community_id}"
                )

    _assert_unique(
        (event["event_id"] for event in event_stream["events"]), "event ID"
    )
    for event in event_stream["events"]:
        for change in event["changes"]:
            if change["edge_id"] not in edge_ids:
                raise ScenarioValidationError(
                    f"{event['event_id']} targets unknown edge {change['edge_id']}"
                )

    bridge_asset_edges = {
        asset["edge_id"]
        for asset in asset_properties
        if asset["asset_type"] == "bridge"
    }
    if not bridge_asset_edges.issubset(edge_ids) or not bridge_asset_edges.issubset(
        asset_ids
    ):
        raise ScenarioValidationError("Bridge assets and graph edges must share IDs")

    _validate_context_boundaries(context_boundaries, asset_ids | edge_ids)
    _validate_prediction_pings(
        scenario_id,
        asset_ids,
        edge_ids,
        impact_prior,
        prediction_pings,
    )


def _validate_context_boundaries(
    context_boundaries: Mapping[str, Any], domain_ids: set[str]
) -> None:
    """Keep administrative context strictly decorative.

    These polygons exist so the map has a recognizable setting. They must never
    collide with a domain ID or claim to be a routing or flood-model input.
    """

    if context_boundaries["data_classification"] != "external_reference":
        raise ScenarioValidationError(
            "Context boundaries must be classified external_reference"
        )
    if context_boundaries["operational_use"]:
        raise ScenarioValidationError("Context boundaries are not operational data")

    context_ids = _assert_unique(
        (feature["properties"]["id"] for feature in context_boundaries["features"]),
        "context boundary ID",
    )
    if context_ids & domain_ids:
        raise ScenarioValidationError(
            "Context boundary IDs must not collide with routed asset or edge IDs"
        )

    for feature in context_boundaries["features"]:
        properties = feature["properties"]
        if properties["routing_enabled"] or properties["flood_model_input"]:
            raise ScenarioValidationError(
                f"{properties['id']} must not be flagged as a domain input"
            )


def _validate_prediction_pings(
    scenario_id: str,
    asset_ids: set[str],
    edge_ids: set[str],
    impact_prior: Mapping[str, Any],
    prediction_pings: Mapping[str, Any],
) -> None:
    if prediction_pings["scenario_id"] != scenario_id:
        raise ScenarioValidationError("Prediction pings must share the scenario_id")
    if prediction_pings["event_id"] != impact_prior["eventId"]:
        raise ScenarioValidationError("Prediction pings and model prior must share event_id")

    probabilities = impact_prior["impactProbabilities"]
    pings = prediction_pings["pings"]
    _assert_unique((ping["ping_id"] for ping in pings), "prediction ping ID")
    targets = _assert_unique((ping["target"] for ping in pings), "prediction target")
    if targets != set(probabilities):
        raise ScenarioValidationError(
            "Prediction pings must cover every model target exactly once"
        )

    for target, probability in probabilities.items():
        if not 0 <= probability <= 1:
            raise ScenarioValidationError(
                f"Prediction probability for {target} must be between 0 and 1"
            )
    for ping in pings:
        if ping.get("anchor_asset_id") not in asset_ids:
            raise ScenarioValidationError(
                f"Prediction ping {ping['ping_id']} references an unknown asset"
            )
        if ping.get("anchor_edge_id") not in edge_ids:
            raise ScenarioValidationError(
                f"Prediction ping {ping['ping_id']} references an unknown edge"
            )
        longitude, latitude = ping["coordinates"]
        if not (80 <= longitude <= 90 and 25 <= latitude <= 31):
            raise ScenarioValidationError(
                f"Prediction ping {ping['ping_id']} falls outside Nepal"
            )
        if ping["activation_hours"] < 0:
            raise ScenarioValidationError(
                f"Prediction ping {ping['ping_id']} has invalid activation time"
            )
