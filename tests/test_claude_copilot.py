import json

import httpx
import pytest
from fastapi.testclient import TestClient

import apps.api.main as api_main
from services.intelligence.claude import (
    ClaudeGroundedClient,
    ClaudeProviderError,
)


def chat(client, message):
    return client.post(
        "/intelligence/chat",
        json={
            "message": message,
            "frame_id": "ktp-frame-now",
            "event_ids": [],
            "intelligence_report_ids": [],
        },
    )


def test_status_question_stays_deterministic(monkeypatch):
    class ForbiddenClaude:
        model = "claude-test"

        def answer(self, *args, **kwargs):
            raise AssertionError("Exact map status must not reach Claude")

    monkeypatch.setattr(api_main, "claude_client", ForbiddenClaude())
    response = chat(TestClient(api_main.app), "Is Nakkhu East Bridge open?")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "deterministic_answer"
    assert body["answer"]["provider"] == "deterministic"
    assert body["answer"]["evidence_ids"] == [
        "ktp-bridge-02",
        "ktp-world-0001",
    ]
    assert "is open" in body["answer"]["message"]


def test_supported_closure_report_stays_deterministic(monkeypatch):
    class ForbiddenClaude:
        model = "claude-test"

        def answer(self, *args, **kwargs):
            raise AssertionError("Supported map mutation must not reach Claude")

    api_main.intelligence_service.clear()
    monkeypatch.setattr(api_main, "claude_client", ForbiddenClaude())
    response = chat(
        TestClient(api_main.app),
        "Nakkhu East Bridge is closed and vehicles cannot pass.",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "deterministic_update"
    assert body["report"]["proposed_change"]["change_type"] == "close_edge"
    assert body["baseline_changed"] is False
    api_main.intelligence_service.clear()


def test_general_question_uses_grounded_claude_context(monkeypatch):
    class FakeClaude:
        model = "claude-test"

        def answer(self, question, context, evidence_ids):
            assert question == "Which responder resources are available?"
            fixture = context["responder_simulation_fixture"]
            assert len(fixture["world_state"]["responders"]) == 5
            assert len(fixture["world_state"]["rescue_requests"]) == 4
            assert context["canonical_world_state"]["edge_states"]
            assert context["mirofish"]["status"] in {"available", "unavailable"}
            assert "01-water-team" in evidence_ids
            return {
                "answer": "Five modeled responder resources are present.",
                "evidence_ids": ["01-water-team", "ktp-world-0001"],
                "limitations": ["MiroFish live output is unavailable."],
            }

    monkeypatch.setattr(api_main, "claude_client", FakeClaude())
    response = chat(
        TestClient(api_main.app), "Which responder resources are available?"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "claude_answer"
    assert body["answer"]["provider"] == "claude"
    assert body["answer"]["model"] == "claude-test"


def test_claude_client_sends_schema_grounding_and_hides_key():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["x-api-key"] == "secret-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert "secret-key" not in request.content.decode()
        assert "only from the supplied GROUNDING_CONTEXT" in body["system"]
        assert body["model"] == "claude-sonnet-4-6"
        assert body["output_config"]["format"]["type"] == "json_schema"
        prompt = json.loads(body["messages"][0]["content"])
        assert prompt["grounding_context"]["canonical_world_state"][
            "world_state_version"
        ] == "world-1"
        document = {
            "answer": "The route is open.",
            "evidence_ids": ["edge-1", "world-1"],
            "limitations": [],
        }
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": json.dumps(document)}],
                "stop_reason": "end_turn",
            },
        )

    client = ClaudeGroundedClient(
        api_key="secret-key",
        model="claude-sonnet-4-6",
        transport=httpx.MockTransport(handler),
    )
    result = client.answer(
        "Is the route open?",
        {"canonical_world_state": {"world_state_version": "world-1"}},
        {"edge-1", "world-1"},
    )

    assert result["answer"] == "The route is open."
    assert len(calls) == 1
    assert str(calls[0].url) == "https://api.anthropic.com/v1/messages"


def test_claude_client_rejects_unknown_evidence():
    def handler(request):
        document = {
            "answer": "Invented answer.",
            "evidence_ids": ["invented-id"],
            "limitations": [],
        }
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": json.dumps(document)}],
                "stop_reason": "end_turn",
            },
        )

    client = ClaudeGroundedClient(
        api_key="secret-key",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ClaudeProviderError, match="outside the supplied context"):
        client.answer("Question", {"data": True}, {"known-id"})


def test_claude_client_rejects_truncated_structured_output():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "{}"}],
                "stop_reason": "max_tokens",
            },
        )

    client = ClaudeGroundedClient(
        api_key="secret-key",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ClaudeProviderError, match="could not complete"):
        client.answer("Question", {"data": True}, {"known-id"})
