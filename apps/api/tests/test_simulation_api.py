import asyncio
import logging

import httpx
import pytest

from ark_api.main import app
from ark_api.routes import simulations
from ark_api.simulation.models import SimulationRequest, SimulationResponse
from ark_api.simulation.scoring import rank_scenario_results

ENDPOINT = "/api/v1/simulate-response"


def request(method, path, **kwargs):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


@pytest.fixture
def payload(simulation_world):
    return {"world_state": simulation_world.model_dump(mode="json")}


def test_health_unchanged():
    response = request("GET", "/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ark-api"}


@pytest.mark.parametrize("explicit_null", [False, True])
def test_generated_plans_ranked_and_complete(payload, explicit_null):
    if explicit_null:
        payload["plans"] = None
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 200, response.text
    parsed = SimulationResponse.model_validate(response.json())
    assert len(parsed.results) == 3
    assert {r.plan_id for r in parsed.results} == {
        "immediate-rescue",
        "balanced-response",
        "preventive-evacuation",
    }
    assert parsed.results == rank_scenario_results(parsed.results)
    assert parsed.recommended_plan_id == next(
        r.plan_id for r in parsed.results if r.viable
    )
    assert parsed.disclaimer == simulations.DISCLAIMER
    assert parsed.model_version == "ark-response-simulator/0.1.0"
    for result in parsed.results:
        assert len(result.score_breakdown) == 9
        assert result.metrics is not None
        assert result.timeline
        assert isinstance(result.violations, list)
        assert isinstance(result.nonviable_reasons, list)
        assert result.status == "completed"


def test_supplied_plans_only_and_ids_preserved(payload, make_plan):
    supplied = make_plan()
    supplied.id = "user-specific-plan"
    payload["plans"] = [supplied.model_dump(mode="json")]
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 200
    assert [r["plan_id"] for r in response.json()["results"]] == ["user-specific-plan"]


@pytest.mark.parametrize(
    "case,code",
    [
        ("empty", "EMPTY_PLANS"),
        ("duplicate", "DUPLICATE_PLAN_ID"),
        ("count", "TOO_MANY_PLANS"),
        ("duration", "DURATION_LIMIT_EXCEEDED"),
    ],
)
def test_structured_client_errors(payload, make_plan, case, code):
    if case == "empty":
        payload["plans"] = []
    elif case == "duplicate":
        payload["plans"] = [make_plan().model_dump(mode="json")] * 2
    elif case == "count":
        payload["plans"] = [
            make_plan().model_dump(mode="json") | {"id": f"p-{i}"} for i in range(21)
        ]
    else:
        payload["duration_minutes"] = 1441
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]


@pytest.mark.parametrize(
    "status", ["draft", "running", "completed", "failed", "cancelled"]
)
def test_non_ready_status_rejected(payload, make_plan, status):
    payload["plans"] = [make_plan().model_dump(mode="json") | {"status": status}]
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PLAN_NOT_READY"


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_minutes": 0},
        {"duration_minutes": -1},
        {"duration_minutes": 1.5},
        {"duration_minutes": True},
        {"duration_minutes": "60"},
        {"world_state": {}},
        {"unknown": True},
        {"random_seed": "42"},
        {"plans": [{"id": "incomplete"}]},
    ],
)
def test_pydantic_errors_keep_standard_422(payload, changes):
    response = request("POST", ENDPOINT, json=payload | changes)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_malformed_json():
    response = request(
        "POST", ENDPOINT, content="{", headers={"content-type": "application/json"}
    )
    assert response.status_code == 422


def test_one_malformed_plan_rejects_whole_request(payload, make_plan, monkeypatch):
    def should_not_run(*args):
        pytest.fail("Invalid requests must not begin execution")

    monkeypatch.setattr(simulations, "simulate_plan", should_not_run)
    payload["plans"] = [make_plan().model_dump(mode="json"), {"id": "invalid"}]
    assert request("POST", ENDPOINT, json=payload).status_code == 422


def test_action_rejection_is_normal_result(payload, make_plan, make_action):
    payload["plans"] = [
        make_plan(make_action(responder_id="missing")).model_dump(mode="json")
    ]
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["metrics"]["rejected_actions"] == 1
    assert result["violations"]
    assert result["viable"] is True


def test_nonviable_plans_returned_but_not_recommended(payload, make_plan, make_action):
    payload["world_state"]["routes"][0]["closure_minute"] = 20
    stranded = make_plan(make_action())
    stranded.id = "stranded"
    stays_safe = make_plan()
    stays_safe.id = "safe"
    payload["plans"] = [
        stranded.model_dump(mode="json"),
        stays_safe.model_dump(mode="json"),
    ]
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["recommended_plan_id"] == "safe"
    assert {r["plan_id"]: r["viable"] for r in body["results"]} == {
        "safe": True,
        "stranded": False,
    }


def test_all_nonviable_returns_null_recommendation(payload):
    for node in payload["world_state"]["nodes"]:
        node["is_safe_zone"] = False
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["recommended_plan_id"] is None
    assert all(not r["viable"] and r["nonviable_reasons"] for r in body["results"])


@pytest.mark.parametrize("supplied", [False, True])
def test_service_does_not_mutate_input(
    simulation_world, make_plan, make_action, supplied
):
    source = SimulationRequest(
        world_state=simulation_world,
        plans=[make_plan(make_action())] if supplied else None,
    )
    before = source.model_dump_json()
    simulations.run_response_simulation(source)
    assert source.model_dump_json() == before


def test_deterministic_response_and_reserved_seed(payload):
    first = request("POST", ENDPOINT, json=payload)
    second = request("POST", ENDPOINT, json=payload)
    different_seed = request("POST", ENDPOINT, json=payload | {"random_seed": 123})
    assert first.status_code == second.status_code == different_seed.status_code == 200
    assert first.content == second.content == different_seed.content


def test_limits_are_inclusive(payload, make_plan):
    payload["duration_minutes"] = 1440
    payload["plans"] = [
        make_plan().model_dump(mode="json") | {"id": f"p-{i}"} for i in range(20)
    ]
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 200
    assert len(response.json()["results"]) == 20
    assert all(r["simulation_minutes"] == 1440 for r in response.json()["results"])


@pytest.mark.parametrize(
    "function",
    ["generate_candidate_plans", "rank_scenario_results", "recommend_plan_id"],
)
def test_domain_errors_are_sanitized(payload, monkeypatch, function):
    def fail(*args):
        raise ValueError("sensitive local path or credentials")

    monkeypatch.setattr(simulations, function, fail)
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DOMAIN_VALIDATION_FAILED"
    assert "sensitive" not in response.text


def test_unexpected_errors_logged_and_sanitized(payload, monkeypatch, caplog):
    def fail(*args):
        raise RuntimeError("sensitive exception details")

    monkeypatch.setattr(simulations, "simulate_plan", fail)
    with caplog.at_level(logging.ERROR, logger=simulations.__name__):
        response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "The simulation could not be completed.",
            "details": {},
        }
    }
    assert "sensitive" not in response.text
    assert "Unexpected response-simulation failure" in caplog.text
    assert caplog.records[-1].exc_info is not None


def test_internal_contract_bug_is_server_error(payload, monkeypatch):
    def fail(*args):
        SimulationRequest.model_validate({})

    monkeypatch.setattr(simulations, "generate_candidate_plans", fail)
    response = request("POST", ENDPOINT, json=payload)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"


def test_openapi_paths_and_contracts():
    response = request("GET", "/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"].startswith("3.")
    assert "get" in schema["paths"]["/health"]
    operation = schema["paths"][ENDPOINT]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/SimulationRequest")
    assert operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/SimulationResponse")
    assert {"SimulationRequest", "SimulationResponse", "ErrorResponse"} <= schema[
        "components"
    ]["schemas"].keys()
