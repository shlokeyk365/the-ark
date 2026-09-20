import pytest
from fastapi.testclient import TestClient

import apps.api.main as api_main
from services.intelligence import FieldIntelligenceService, ReportNotFoundError
from services.routing.engine import derive_edge_states
from services.scenarios import ScenarioService


class FakeScenario:
    manifest = {"scenario_id": "test-scenario"}
    assets = {
        "features": [
            {
                "properties": {
                    "id": "bridge-asset",
                    "name": "East River Bridge",
                    "edge_id": "edge-1",
                }
            }
        ]
    }
    network = {
        "features": [
            {
                "properties": {
                    "id": "edge-1",
                    "edge_type": "bridge",
                    "from_node_id": "a",
                    "to_node_id": "b",
                    "baseline_travel_minutes": 4,
                    "bidirectional": True,
                    "penalty_depth_m": 0.2,
                    "closure_depth_m": 0.8,
                    "penalty_multiplier": 2,
                    "critical": True,
                }
            }
        ]
    }


def test_probable_report_does_not_become_confirmed_automatically():
    service = FieldIntelligenceService(FakeScenario())
    report = service.ingest(
        "Rescue 4 reports East River Bridge is under two feet of water "
        "and vehicles cannot pass.",
        "field_responder",
        "Rescue 4",
        "frame-now",
    )

    assert report.status == "probable"
    assert report.edge_id == "edge-1"
    assert report.water_depth_m == 0.61
    assert service.events_for([report.report_id]) == []
    assert service.events_for([report.report_id], include_probable=True)


def test_confirmed_report_closes_edge_deterministically():
    service = FieldIntelligenceService(FakeScenario())
    report = service.ingest(
        "East River Bridge is blocked and vehicles cannot pass.",
        "official",
        "Incident Command",
        "frame-now",
    )
    service.decide(report.report_id, "confirm", "Verified by radio.")
    event = service.events_for([report.report_id])
    frame = {
        "frame_id": "frame-now",
        "edge_conditions": [{"edge_id": "edge-1", "flood_depth_m": 0.0}],
    }

    state = derive_edge_states(FakeScenario.network, frame, event)["edge-1"]

    assert state["status"] == "closed"
    assert state["effective_travel_minutes"] is None
    assert state["originating_event_id"] == report.report_id


def test_flood_report_without_blockage_restricts_edge():
    service = FieldIntelligenceService(FakeScenario())
    report = service.ingest(
        "Water is rising over East River Bridge.",
        "field_responder",
        "Rescue 2",
        "frame-now",
    )
    event = service.events_for([report.report_id], include_probable=True)
    frame = {
        "frame_id": "frame-now",
        "edge_conditions": [{"edge_id": "edge-1", "flood_depth_m": 0.0}],
    }

    state = derive_edge_states(FakeScenario.network, frame, event)["edge-1"]

    assert state["status"] == "restricted"
    assert state["effective_travel_minutes"] == 8


def test_deleted_report_is_removed_from_the_store():
    service = FieldIntelligenceService(FakeScenario())
    report = service.ingest(
        "East River Bridge is blocked and vehicles cannot pass.",
        "operator",
        "Incident Command",
        "frame-now",
    )
    service.decide(report.report_id, "confirm", None)

    deleted = service.delete(report.report_id)

    assert deleted.report_id == report.report_id
    assert service.list() == []
    with pytest.raises(ReportNotFoundError):
        service.get(report.report_id)


def test_map_summary_reads_the_canonical_world_state():
    scenario = ScenarioService()
    service = FieldIntelligenceService(scenario)
    state = scenario.baseline()

    summary = service.summarize_map(state)

    assert summary["source_world_state_version"] == state["world_state_version"]
    assert summary["facts"] == {
        "routes_total": len(state["edge_states"]),
        "routes_closed": 0,
        "routes_restricted": 0,
        "communities_total": len(state["community_access"]),
        "communities_isolated": 0,
        "hospital_accessible_communities": len(state["community_access"]),
        "active_hazards": len(state["hazards"]),
        "active_events": 0,
        "viable_plans": sum(
            result["metrics"]["plan_viable"] for result in state["plan_results"]
        ),
    }
    assert summary["priorities"]
    assert summary["recommended_plan"]
    assert "Flow velocity is unavailable" in summary["limitations"][1]


def test_map_summary_endpoint_returns_versioned_briefing(monkeypatch):
    class FakeClaude:
        model = "claude-test"

        def briefing(self, context, deterministic, evidence_ids):
            assert context["canonical_world_state"]["frame_id"] == "ktp-frame-now"
            assert context["responder_simulation_fixture"]["world_state"][
                "responders"
            ]
            return {
                "headline": deterministic["headline"],
                "overview": deterministic["overview"],
                "priorities": deterministic["priorities"],
                "recommended_plan": deterministic["recommended_plan"],
                "evidence_ids": ["ktp-world-0001"],
            }

    monkeypatch.setattr(api_main, "claude_client", FakeClaude())
    client = TestClient(api_main.app)

    response = client.post(
        "/intelligence/map-summary",
        json={
            "frame_id": "ktp-frame-now",
            "event_ids": [],
            "intelligence_report_ids": [],
        },
    )

    assert response.status_code == 200
    briefing = response.json()
    assert briefing["frame_id"] == "ktp-frame-now"
    assert briefing["source_world_state_version"] == "ktp-world-0001"
    assert briefing["facts"]["routes_total"] > 0
    assert briefing["overview"]
    assert briefing["provider"] == "claude"
    assert briefing["model"] == "claude-test"
