from services.intelligence import FieldIntelligenceService
from services.routing.engine import derive_edge_states


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
