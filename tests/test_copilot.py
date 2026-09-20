import json

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.models import CopilotRequest
from services.intelligence.copilot import CopilotService
from services.intelligence.service import FieldIntelligenceService
from services.reports import ReportRepository
from services.scenarios import ScenarioService


@pytest.fixture
def copilot(monkeypatch):
    monkeypatch.setattr("services.intelligence.copilot.claude_settings", lambda: ("test-key", "test-model"))
    scenario = ScenarioService()
    return CopilotService(scenario, FieldIntelligenceService(scenario), ReportRepository(":memory:"))


def request(message, **kwargs):
    return CopilotRequest(message=message, frame_id="ktp-frame-now", **kwargs)


def test_status_questions_and_negations_never_close_map(copilot):
    for message in ["Is ktp-bridge-02 closed?", "ktp-bridge-02 is not closed", "ktp-bridge-02 open and closed", "ktp-bridge-02 and ktp-bridge-01 closed", "ktp-bridge-020 closed"]:
        answer = copilot.ask(request(message))
        assert answer["report"] is None
        assert answer["tentative_world_state"] is None
    assert copilot.intelligence.list() == []


def test_close_and_reopen_keep_flood_constraints(copilot):
    closed = copilot.ask(request("ktp-bridge-02 is closed"))
    report_id = closed["report"]["report_id"]
    copilot.intelligence.decide(report_id, "confirm", None)
    reopened = copilot.ask(request("ktp-bridge-02 is open", intelligence_report_ids=[report_id]))
    edge = next(e for e in reopened["tentative_world_state"]["edge_states"] if e["edge_id"] == "ktp-bridge-02")
    assert edge["status"] == "open"
    assert not reopened["baseline_changed"]
    open_id = reopened["report"]["report_id"]
    copilot.intelligence.decide(open_id, "confirm", None)
    events = copilot.intelligence.events_for([report_id, open_id])
    late = copilot.scenario.build_world_state(copilot.scenario.flood_frames["frames"][-1]["frame_id"], [], events)
    edge = next(e for e in late["edge_states"] if e["edge_id"] == "ktp-bridge-02")
    assert edge["status"] == "closed"
    assert edge["originating_event_id"] is None


def test_context_contains_separate_responder_simulation_and_current_map(copilot):
    rows = copilot.context(copilot.scenario.baseline(), [])
    text = json.dumps(rows)
    assert "CURRENT MAP" in text
    assert "synthetic" in text
    assert "accepted_proposals" in text
    assert "snapshot_hash" in text
    assert "nepal-nakkhu-demo-v1" in text
    assert "Rendering coordinates omitted" in text
    assert "No saved simulation reports available" in text


@pytest.mark.parametrize("source_count", [1, 20, 33])
def test_claude_returns_coherent_answer_with_server_evidence(copilot, source_count):
    def handler(req):
        payload = json.loads(req.content)
        data = json.loads(payload["messages"][0]["content"])
        assert req.headers["x-api-key"] == "test-key"
        assert "test-key" not in payload["messages"][0]["content"]
        row = next(r for r in data["evidence"] if "ktp-bridge-02" in r["text"] and r["source"].startswith("CURRENT MAP"))
        ids = [row["evidence_id"]] + [r["evidence_id"] for r in data["evidence"] if r != row][:source_count - 1]
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps({
            "status": "The bridge is open in the current frame.",
            "threat": "No closure reason is recorded.",
            "action": "Use the current route posture and reassess on status change.",
            "action_metric": "1 active route posture",
            "detail_topics": [],
            "evidence_ids": ids,
        })}]})
    copilot.transport = httpx.MockTransport(handler)
    answer = copilot.ask(request("Why does the bridge matter to this plan?"))
    assert answer["answer"].startswith("STATUS: The bridge is open")
    assert "\nTHREAT:" in answer["answer"]
    assert "\nACTION:" in answer["answer"]
    assert len(answer["answer"].split()) <= 120
    assert answer["report"] is None
    assert "test-key" not in json.dumps(answer)


@pytest.mark.parametrize("body", [
    {"status": "Invented", "threat": "Invented", "action": "Invented", "action_metric": "1 reason", "detail_topics": [], "evidence_ids": ["invented"]},
    {"status": "", "threat": "Missing", "action": "Missing", "action_metric": "1 reason", "detail_topics": [], "evidence_ids": []},
    {"status": "Invalid", "threat": "Invalid", "action": "Invalid", "action_metric": "1 reason", "detail_topics": [], "evidence_ids": "E0000"},
])
def test_unsupported_model_output_is_not_displayed(copilot, body):
    copilot.transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        "stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(body)}],
    }))
    answer = copilot.ask(request("Explain the plans"))
    assert answer["answer"].startswith("STATUS: Incident assistant unavailable")
    assert "Invented evacuation order" not in answer["answer"]


def test_uncited_model_claims_are_replaced_by_abstention(copilot):
    copilot.transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        "stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps({
            "status": "Invented evacuation order", "threat": "Invented", "action": "Invented",
            "action_metric": "1 reason", "detail_topics": [], "evidence_ids": [],
        })}],
    }))
    answer = copilot.ask(request("Explain the plans"))
    assert "do not answer this question" in answer["answer"]
    assert "Invented" not in answer["answer"]


def test_no_key_and_http_failure_are_visible(copilot, monkeypatch):
    copilot.transport = httpx.MockTransport(lambda _: httpx.Response(401, json={"secret": "test-key"}))
    assert copilot.ask(request("Explain the plans"))["answer"].startswith("STATUS: Incident assistant unavailable")
    monkeypatch.setattr("services.intelligence.copilot.claude_settings", lambda: ("", "test-model"))
    answer = copilot.ask(request("Explain the plans"))
    assert answer["answer"].startswith("STATUS: Incident assistant unavailable")


def test_chat_http_contract_and_invalid_frame():
    with TestClient(app) as client:
        answer = client.post("/intelligence/chat", json=request("ktp-bridge-02 blocked").model_dump())
        assert answer.status_code == 200
        assert answer.json()["tentative_world_state"] is not None
        assert "evidence" not in answer.json()
        assert "mode" not in answer.json()
        assert answer.json()["answer"].startswith("STATUS:")
        assert client.post("/intelligence/chat", json={"message": "hello", "frame_id": "missing"}).status_code == 404
        assert set(client.get("/intelligence/status").json()) == {"assistant_configured"}
