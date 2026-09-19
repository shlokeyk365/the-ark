import pytest

from ark_api.routes import simulations
from ark_api.simulation.models import RobustnessConfig, SimulationRequest
from tests.test_simulation_api import ENDPOINT, request


def payload(world, **changes):
    return {"world_state": world.model_dump(mode="json"), **changes}


@pytest.mark.parametrize("value", [None, {"enabled": False}])
def test_disabled_preserves_baseline(simulation_world, monkeypatch, value):
    expected = simulations.run_response_simulation(
        SimulationRequest(world_state=simulation_world)
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Disabled robustness must not execute")

    monkeypatch.setattr(simulations, "analyze_robustness", forbidden)
    response = request(
        "POST", ENDPOINT, json=payload(simulation_world, robustness=value)
    )
    assert response.status_code == 200
    assert response.json() == expected.model_dump(mode="json")
    assert response.json()["robustness"] is None


def test_enabled_identical_and_no_mutation(simulation_world):
    submitted = SimulationRequest(
        world_state=simulation_world,
        robustness=RobustnessConfig(enabled=True, trial_count=3),
    )
    before = submitted.model_dump_json()
    direct = simulations.run_response_simulation(submitted)
    assert submitted.model_dump_json() == before
    responses = [
        request("POST", ENDPOINT, json=submitted.model_dump(mode="json"))
        for _ in range(2)
    ]
    assert responses[0].status_code == 200
    assert responses[0].content == responses[1].content
    assert responses[0].json() == direct.model_dump(mode="json")
    baseline = simulations.run_response_simulation(
        SimulationRequest(world_state=simulation_world)
    )
    assert direct.results == baseline.results
    assert direct.recommended_plan_id == baseline.recommended_plan_id
    assert (
        direct.robustness.baseline_recommended_plan_id == baseline.recommended_plan_id
    )
    assert direct.robustness.completed_matched_trials == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"trial_count": 101},
        {"trial_count": 0},
        {"seed": "42"},
        {"unknown": 1},
        {"route_closure_shift_minutes": [15, -15]},
        {"travel_time_increase_percent": [-1, 40]},
    ],
)
def test_invalid_configuration_422(simulation_world, changes):
    response = request(
        "POST",
        ENDPOINT,
        json=payload(simulation_world, robustness={"enabled": True, **changes}),
    )
    assert response.status_code == 422


def test_unavailable_count_400(simulation_world):
    response = request(
        "POST",
        ENDPOINT,
        json=payload(
            simulation_world,
            robustness={"enabled": True, "responder_unavailability_count": 2},
        ),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DOMAIN_VALIDATION_FAILED"


def test_internal_error_sanitized(simulation_world, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("sensitive diagnostic")

    monkeypatch.setattr(simulations, "analyze_robustness", broken)
    response = request(
        "POST", ENDPOINT, json=payload(simulation_world, robustness={"enabled": True})
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "sensitive diagnostic" not in response.text


def test_poor_trials_200(simulation_world, make_plan, make_action):
    plan = make_plan(make_action())
    response = request(
        "POST",
        ENDPOINT,
        json=payload(
            simulation_world,
            plans=[plan.model_dump(mode="json")],
            robustness={
                "enabled": True,
                "trial_count": 2,
                "responder_unavailability_count": 1,
            },
        ),
    )
    assert response.status_code == 200
    summary = response.json()["robustness"]["summaries"][0]
    assert summary["completed_trial_count"] == 2
    assert summary["reason_counts"]
