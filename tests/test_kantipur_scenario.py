import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.api.main import app
from apps.api.models import (
    EventRecomputeResponse,
    HealthResponse,
    ScenarioBootstrapResponse,
    WorldStateSnapshot,
)
from services.routing.engine import build_adjacency, shortest_path
from services.scenarios import ScenarioService
from services.scenarios.validation import (
    ScenarioValidationError,
    validate_scenario_fixtures,
)


FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scenarios"
    / "kantipur-river"
)


def _service() -> ScenarioService:
    return ScenarioService(FIXTURE_DIRECTORY)


def _by_id(items: list[dict], key: str) -> dict[str, dict]:
    return {item[key]: item for item in items}


def test_fixture_shape_and_capacity_are_coherent() -> None:
    service = _service()
    assets = [feature["properties"] for feature in service.assets["features"]]
    asset_types = [asset["asset_type"] for asset in assets]

    assert asset_types.count("community") == 5
    assert asset_types.count("bridge") == 2
    assert asset_types.count("hospital") == 1
    assert asset_types.count("shelter") == 2
    assert sum(asset["population"] for asset in assets if asset["asset_type"] == "community") == 4560
    assert sum(asset["capacity"] for asset in assets if asset["asset_type"] == "shelter") == 3000
    assert len(service.network["features"]) == 12
    assert len(service.flood_polygons["features"]) == 11
    assert {
        feature["properties"]["simulation_time_hours"]
        for feature in service.flood_polygons["features"]
    } == {0, 6, 12, 24}
    assert [
        frame["simulation_time_hours"] for frame in service.flood_frames["frames"]
    ] == list(range(0, 25, 3))


def test_baseline_is_reachable_and_has_expected_routes() -> None:
    service = _service()
    baseline = service.baseline()
    access = _by_id(baseline["community_access"], "community_id")

    assert all(not community["isolated"] for community in access.values())
    assert all(community["hospital_accessible"] for community in access.values())
    assert all(community["reachable_shelter_ids"] for community in access.values())
    assert access["ktp-com-05"]["time_to_isolation_hours"] == 21

    edge_states = _by_id(baseline["edge_states"], "edge_id")
    adjacency = build_adjacency(service.network, edge_states)
    route = shortest_path(
        adjacency, "ktp-node-com-05", "ktp-node-hospital-01"
    )
    assert route is not None
    assert route["edge_ids"] == ["ktp-road-10", "ktp-bridge-02", "ktp-road-04"]
    assert route["travel_minutes"] == 11


def test_flood_closure_then_bridge_event_isolates_riverbend() -> None:
    service = _service()
    before_event = service.build_world_state("ktp-frame-plus-12h")
    before_edges = _by_id(before_event["edge_states"], "edge_id")
    before_access = _by_id(before_event["community_access"], "community_id")

    assert before_edges["ktp-road-09"]["status"] == "closed"
    assert before_edges["ktp-bridge-02"]["status"] == "restricted"
    assert before_access["ktp-com-05"]["isolated"] is False

    result = service.apply_event("ktp-event-bridge-02-failure")
    updated = result["updated_world_state"]
    updated_edges = _by_id(updated["edge_states"], "edge_id")
    updated_access = _by_id(updated["community_access"], "community_id")

    assert updated_edges["ktp-bridge-02"]["status"] == "closed"
    assert updated_edges["ktp-bridge-02"]["originating_event_id"] == "ktp-event-bridge-02-failure"
    assert updated_access["ktp-com-05"]["isolated"] is True
    assert sum(1 for access in updated_access.values() if access["isolated"]) == 1


def test_plans_have_distinct_baseline_outcomes() -> None:
    service = _service()
    results = _by_id(service.baseline()["plan_results"], "plan_id")

    assert results["ktp-plan-a"]["metrics"]["people_evacuated_by_deadline"] == 2620
    assert results["ktp-plan-b"]["metrics"]["people_evacuated_by_deadline"] == 3000
    assert results["ktp-plan-c"]["metrics"]["people_evacuated_by_deadline"] == 3000
    assert results["ktp-plan-a"]["metrics"]["evacuation_completion_minutes"] == 15
    assert results["ktp-plan-b"]["metrics"]["evacuation_completion_minutes"] == 27
    assert results["ktp-plan-c"]["metrics"]["evacuation_completion_minutes"] == 22
    assert all(result["metrics"]["plan_viable"] for result in results.values())


def test_event_invalidates_and_recomputes_every_plan() -> None:
    service = _service()
    result = service.apply_event("ktp-event-bridge-02-failure")
    stale = _by_id(result["stale_plan_results"], "plan_id")
    recomputed = _by_id(result["recomputed_plan_results"], "plan_id")

    assert all(item["status"] == "stale" for item in stale.values())
    assert all(item["invalidation_reason"] for item in stale.values())
    assert all(item["status"] == "current" for item in recomputed.values())
    assert all(not item["metrics"]["plan_viable"] for item in recomputed.values())
    assert recomputed["ktp-plan-a"]["metrics"]["people_evacuated_by_deadline"] == 2000
    assert recomputed["ktp-plan-b"]["metrics"]["people_evacuated_by_deadline"] == 2380
    assert recomputed["ktp-plan-c"]["metrics"]["people_evacuated_by_deadline"] == 2760
    assert all(item["metrics"]["people_isolated"] == 620 for item in recomputed.values())


def test_api_serves_baseline_and_event_recompute() -> None:
    client = TestClient(app)

    baseline = client.get("/scenarios/kantipur-river/baseline")
    assert baseline.status_code == 200
    assert baseline.json()["world_state_version"] == "ktp-world-0001"

    event = client.post(
        "/scenarios/kantipur-river/events/ktp-event-bridge-02-failure"
    )
    assert event.status_code == 200
    assert event.json()["updated_world_state"]["world_state_version"].startswith(
        "ktp-world-0005-"
    )


def test_bootstrap_supplies_frontend_geometry_and_controls() -> None:
    client = TestClient(app)
    response = client.get("/scenarios/kantipur-river/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["initial_frame_id"] == "ktp-frame-now"
    assert len(payload["assets"]["features"]) == 10
    assert len(payload["road_network"]["features"]) == 12
    assert payload["flood_polygons"]["operational_use"] is False
    assert payload["flood_polygons"]["source"]["model_name"] == "kantipur-curated-surface"
    assert [
        frame["simulation_time_hours"] for frame in payload["available_frames"]
    ] == list(range(0, 25, 3))
    assert [event["event_id"] for event in payload["events"]] == [
        "ktp-event-bridge-02-failure"
    ]
    assert [plan["plan_id"] for plan in payload["plans"]] == [
        "ktp-plan-a",
        "ktp-plan-b",
        "ktp-plan-c",
    ]
    assert payload["impact_model"]["model_name"] == "CatBoost flood impact model"
    assert payload["impact_model"]["evaluation"]["unseen_district_roc_auc"] == 0.6987
    assert payload["impact_model"]["training_events"] == 4869


def test_model_prediction_pings_increase_with_local_flood_stage() -> None:
    service = _service()
    expected = {
        "casualty_or_missing": 0.489031,
        "housing_damage": 0.335107,
        "transport_disruption": 0.130326,
        "severe_impact": 0.364804,
    }

    frames = [
        service.build_world_state(frame_id)["prediction_signals"]
        for frame_id in (
            "ktp-frame-now",
            "ktp-frame-plus-6h",
            "ktp-frame-plus-12h",
            "ktp-frame-plus-24h",
        )
    ]
    now, plus_six, plus_twelve, horizon = frames

    assert len(now) == 10
    assert {signal["target"]: signal["base_probability"] for signal in now} == expected
    for initial_signal in now:
        ping_id = initial_signal["ping_id"]
        values = [
            next(signal for signal in signals if signal["ping_id"] == ping_id)[
                "probability"
            ]
            for signals in frames
        ]
        assert values == sorted(values)
        assert len(set(values)) == len(values)
        assert all(value <= expected[initial_signal["target"]] for value in values)

    horizon_by_target = {
        target: {
            signal["probability"]
            for signal in horizon
            if signal["target"] == target
        }
        for target in expected
    }
    assert all(len(values) > 1 for values in horizon_by_target.values())
    assert sorted(signal["priority_rank"] for signal in horizon) == list(range(1, 11))
    assert min(signal["priority_score"] for signal in horizon) >= 0
    assert max(signal["priority_score"] for signal in horizon) <= 100
    assert all(
        signal["score_type"] == "prototype_localized_risk_score"
        for signal in horizon
    )
    assert next(
        signal for signal in horizon if signal["ping_id"] == "nakkhu-risk-transport-central"
    )["priority_rank"] == 1

    assert all(signal["state"] == "forecast" for signal in now)
    assert sum(signal["state"] == "active" for signal in plus_six) == 5
    assert all(signal["state"] == "active" for signal in plus_twelve)
    assert all(signal["state"] == "active" for signal in horizon)
    assert all(
        signal["source_type"] == "scenario_adjusted_model_prior"
        for signal in now
    )
    assert all(signal["anchor_edge_id"].startswith("ktp-") for signal in now)


def test_wire_models_validate_all_service_responses_and_reject_drift() -> None:
    service = _service()

    ScenarioBootstrapResponse.model_validate(service.bootstrap())
    for frame in service.flood_frames["frames"]:
        WorldStateSnapshot.model_validate(
            service.build_world_state(frame["frame_id"])
        )
    EventRecomputeResponse.model_validate(
        service.apply_event("ktp-event-bridge-02-failure")
    )

    with pytest.raises(ValidationError):
        HealthResponse.model_validate({"status": "ok", "undeclared": True})


def test_openapi_publishes_named_frontend_contracts() -> None:
    schema = app.openapi()
    schemas = schema["components"]["schemas"]

    assert "ScenarioBootstrapResponse" in schemas
    assert "WorldStateSnapshot" in schemas
    assert "EventRecomputeResponse" in schemas
    assert "SimulationRun" in schemas
    assert "SimulationReport" in schemas
    assert "SimulationRunSummary" in schemas
    bootstrap_schema = schema["paths"]["/scenarios/kantipur-river/bootstrap"][
        "get"
    ]["responses"]["200"]["content"]["application/json"]["schema"]
    assert bootstrap_schema["$ref"].endswith("/ScenarioBootstrapResponse")


def test_api_returns_not_found_for_unknown_frame_and_event() -> None:
    client = TestClient(app)

    assert client.get("/scenarios/kantipur-river/frames/unknown").status_code == 404
    assert client.post("/scenarios/kantipur-river/events/unknown").status_code == 404


def test_local_frontend_origin_is_allowed_by_cors() -> None:
    client = TestClient(app)
    response = client.options(
        "/scenarios/kantipur-river/bootstrap",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_time_to_isolation_moves_forward_under_an_injected_event() -> None:
    service = _service()

    baseline = _by_id(service.baseline()["community_access"], "community_id")
    assert baseline["ktp-com-05"]["time_to_isolation_hours"] == 21
    assert baseline["ktp-com-05"]["isolated"] is False

    disrupted = _by_id(
        service.build_world_state(
            "ktp-frame-plus-12h", ["ktp-event-bridge-02-failure"]
        )["community_access"],
        "community_id",
    )
    assert disrupted["ktp-com-05"]["isolated"] is True
    assert disrupted["ktp-com-05"]["time_to_isolation_hours"] == 12
    assert all(
        access["time_to_isolation_hours"] is None
        for community_id, access in disrupted.items()
        if community_id != "ktp-com-05"
    )


def test_frames_can_be_scrubbed_with_an_event_held_active() -> None:
    client = TestClient(app)
    event_id = "ktp-event-bridge-02-failure"

    later = client.get(
        "/scenarios/kantipur-river/frames/ktp-frame-plus-24h",
        params={"events": [event_id]},
    )
    assert later.status_code == 200
    payload = later.json()
    WorldStateSnapshot.model_validate(payload)
    assert payload["world_state_version"] == "ktp-world-0009-bridge-02-failure"
    assert payload["active_event_ids"] == [event_id]
    edges = _by_id(payload["edge_states"], "edge_id")
    assert edges["ktp-bridge-02"]["status"] == "closed"
    assert edges["ktp-bridge-02"]["originating_event_id"] == event_id

    too_early = client.get(
        "/scenarios/kantipur-river/frames/ktp-frame-now",
        params={"events": [event_id]},
    )
    assert too_early.status_code == 409
    assert event_id in too_early.json()["detail"]

    unknown = client.get(
        "/scenarios/kantipur-river/frames/ktp-frame-plus-24h",
        params={"events": ["ktp-event-nope"]},
    )
    assert unknown.status_code == 404


def test_bootstrap_exposes_context_boundaries_as_non_domain_data() -> None:
    client = TestClient(app)
    payload = client.get("/scenarios/kantipur-river/bootstrap").json()
    context = payload["context_boundaries"]

    assert context["data_classification"] == "external_reference"
    assert context["operational_use"] is False
    assert [feature["properties"]["name"] for feature in context["features"]] == [
        "Kathmandu Metropolitan City",
        "Lalitpur Metropolitan City",
    ]
    assert all(
        feature["properties"]["routing_enabled"] is False
        and feature["properties"]["flood_model_input"] is False
        for feature in context["features"]
    )
    assert context["source"]["license"] == "MIT"

    service = _service()
    routed_ids = {
        feature["properties"]["id"] for feature in service.assets["features"]
    } | {feature["properties"]["id"] for feature in service.network["features"]}
    context_ids = {
        feature["properties"]["id"] for feature in context["features"]
    }
    assert not (routed_ids & context_ids)

    # Context geometry must never reach a derived world state.
    baseline = service.baseline()
    assert "context" not in json.dumps(baseline).lower()


def test_context_boundaries_flagged_as_domain_input_are_rejected() -> None:
    service = _service()
    tampered = copy.deepcopy(service.context_boundaries)
    tampered["features"][0]["properties"]["routing_enabled"] = True

    with pytest.raises(ScenarioValidationError):
        validate_scenario_fixtures(
            service.manifest,
            service.assets,
            service.network,
            service.flood_frames,
            service.flood_polygons,
            service.response_plans,
            service.event_stream,
            tampered,
            service.impact_prior,
            service.prediction_pings,
        )


def test_flood_polygon_contract_rejects_unknown_frames_and_open_rings() -> None:
    service = _service()

    unknown_frame = copy.deepcopy(service.flood_polygons)
    unknown_frame["features"][0]["properties"]["frame_id"] = "missing-frame"
    with pytest.raises(ScenarioValidationError, match="unknown frame"):
        validate_scenario_fixtures(
            service.manifest,
            service.assets,
            service.network,
            service.flood_frames,
            unknown_frame,
            service.response_plans,
            service.event_stream,
            service.context_boundaries,
            service.impact_prior,
            service.prediction_pings,
        )

    open_ring = copy.deepcopy(service.flood_polygons)
    open_ring["features"][0]["geometry"]["coordinates"][0][-1] = [85.29, 27.69]
    with pytest.raises(ScenarioValidationError, match="closed rings"):
        validate_scenario_fixtures(
            service.manifest,
            service.assets,
            service.network,
            service.flood_frames,
            open_ring,
            service.response_plans,
            service.event_stream,
            service.context_boundaries,
            service.impact_prior,
            service.prediction_pings,
        )
