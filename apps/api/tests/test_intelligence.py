import asyncio

import httpx
import pytest

from ark_api.main import app
from ark_api.routes.intelligence import service

ENDPOINT = "/api/v1/intelligence/messages"


def request(method, path, **kwargs):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


@pytest.fixture(autouse=True)
def clear_store():
    service.store.clear()


@pytest.fixture
def payload(world_state):
    return {
        "message": (
            "Rescue 4 reports road-1 is under two feet of water and vehicles "
            "cannot pass. Water is rising."
        ),
        "source": {"type": "field_responder", "name": "Rescue 4", "channel": "radio"},
        "world_state": world_state.model_dump(mode="json"),
    }


def test_probable_report_creates_tentative_branch_without_changing_baseline(payload):
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report"]["status"] == "probable"
    assert body["report"]["claim"]["claim_type"] == "route_blocked"
    assert body["report"]["claim"]["water_depth_m"] == pytest.approx(0.61)
    assert body["report"]["claim"]["trend"] == "rising"
    assert body["baseline_changed"] is False
    assert body["tentative_world_state"]["routes"][0]["status"] == "closed"
    assert payload["world_state"]["routes"][0]["status"] == "open"


def test_low_reliability_report_is_stored_but_not_applied(payload):
    payload["source"] = {"type": "public", "name": "Anonymous caller"}
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["report"]["status"] == "possible"
    assert body["tentative_world_state"] is None


def test_ambiguous_message_is_unresolved(payload):
    payload["message"] = "Someone said a road near a bridge might be bad."
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 200
    assert response.json()["report"]["status"] == "unresolved"
    assert response.json()["report"]["proposed_change"]["change_type"] == "none"


def test_operator_confirmation_updates_canonical_world(payload):
    created = request("POST", ENDPOINT, json=payload).json()
    report_id = created["report"]["id"]
    response = request(
        "POST",
        f"/api/v1/intelligence/reports/{report_id}/decision",
        json={
            "decision": "confirm",
            "world_state": payload["world_state"],
            "note": "Confirmed by incident command",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report"]["status"] == "confirmed"
    assert body["baseline_changed"] is True
    route = body["world_state"]["routes"][0]
    assert route["status"] == "closed"
    assert route["closure_minute"] == payload["world_state"]["current_minute"]
    assert report_id in body["world_state"]["metadata"]["intelligence_report_ids"]


def test_rejection_preserves_world(payload):
    created = request("POST", ENDPOINT, json=payload).json()
    report_id = created["report"]["id"]
    response = request(
        "POST",
        f"/api/v1/intelligence/reports/{report_id}/decision",
        json={"decision": "reject", "world_state": payload["world_state"]},
    )
    assert response.status_code == 200
    assert response.json()["baseline_changed"] is False
    assert response.json()["world_state"] == payload["world_state"]


def test_reports_are_queryable(payload):
    created = request("POST", ENDPOINT, json=payload).json()["report"]
    listed = request("GET", "/api/v1/intelligence/reports").json()
    fetched = request("GET", f"/api/v1/intelligence/reports/{created['id']}").json()
    assert [report["id"] for report in listed] == [created["id"]]
    assert fetched == created


def test_unknown_report_returns_404(payload):
    response = request(
        "POST",
        "/api/v1/intelligence/reports/missing/decision",
        json={"decision": "confirm", "world_state": payload["world_state"]},
    )
    assert response.status_code == 404
