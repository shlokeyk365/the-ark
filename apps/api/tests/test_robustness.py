import random
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ark_api.simulation import robustness as r
from ark_api.simulation.engine import simulate_plan
from ark_api.simulation.models import (
    LocationNode,
    PlanStatus,
    RobustnessConfig,
    RobustnessResult,
    RouteStatus,
    SimulationRequest,
)
from ark_api.simulation.plans import generate_candidate_plans
from ark_api.simulation.scoring import DEFAULT_SCORING_POLICY, rank_scenario_results
from tests.test_scoring import result as scoring_result


def config(**changes):
    defaults = dict(
        enabled=True,
        trial_count=3,
        route_closure_shift_minutes=(0, 0),
        travel_time_increase_percent=(0, 0),
        shelter_capacity_reduction_percent=(0, 0),
        request_reporting_delay_minutes=(0, 0),
    )
    return RobustnessConfig(**(defaults | changes))


def analyze(world, **changes):
    return r.analyze_robustness(
        world, generate_candidate_plans(world), 60, config(**changes)
    )


def test_defaults_and_immutable():
    c = RobustnessConfig()
    assert not c.enabled and c.trial_count == 20 and c.seed == 42
    assert c.route_closure_shift_minutes == (-15, 15)
    assert c.travel_time_increase_percent == (0, 40)
    with pytest.raises(ValidationError):
        c.seed = 1
    with pytest.raises(TypeError):
        c.route_closure_shift_minutes[0] = 0
    assert RobustnessConfig(trial_count=100).trial_count == 100


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown": True},
        {"enabled": 1},
        {"trial_count": 0},
        {"trial_count": -1},
        {"trial_count": 101},
        {"trial_count": True},
        {"trial_count": "20"},
        {"seed": -1},
        {"seed": 2**63},
        {"seed": True},
        {"route_closure_shift_minutes": (-16, 15)},
        {"route_closure_shift_minutes": (0, 16)},
        {"route_closure_shift_minutes": (3, -3)},
        {"route_closure_shift_minutes": [0]},
        {"travel_time_increase_percent": (-1, 10)},
        {"travel_time_increase_percent": (0, 41)},
        {"travel_time_increase_percent": (10, 1)},
        {"travel_time_increase_percent": (0, 1.2)},
        {"shelter_capacity_reduction_percent": (-1, 0)},
        {"shelter_capacity_reduction_percent": (0, 41)},
        {"shelter_capacity_reduction_percent": (10, 0)},
        {"request_reporting_delay_minutes": (0, 16)},
        {"request_reporting_delay_minutes": (-1, 0)},
        {"request_reporting_delay_minutes": (10, 0)},
        {"additional_request_count": 4},
        {"additional_request_count": -1},
        {"responder_unavailability_count": -1},
        {"responder_unavailability_count": 21},
    ],
)
def test_invalid_config(changes):
    with pytest.raises(ValidationError):
        RobustnessConfig(**changes)


def test_disabled_no_work(world_state, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Disabled robustness must not run")

    monkeypatch.setattr(r, "simulate_plan", forbidden)
    monkeypatch.setattr(r, "generate_trial", forbidden)
    assert r.analyze_robustness(world_state, [], 60, RobustnessConfig()) is None


def test_bound_available(world_state):
    with pytest.raises(r.RobustnessInputError):
        analyze(world_state, responder_unavailability_count=2)


def test_determinism_and_seed(world_state):
    settings = dict(
        route_closure_shift_minutes=(-15, 15), travel_time_increase_percent=(0, 40)
    )
    random.seed(3)
    first = analyze(world_state, **settings)
    random.seed(93832)
    assert first.model_dump_json() == analyze(world_state, **settings).model_dump_json()
    other = analyze(world_state, seed=43, **settings)
    assert first.trials[0].audit.route_changes != other.trials[
        0
    ].audit.route_changes or (
        first.trials[0].audit.travel_time_changes
        != other.trials[0].audit.travel_time_changes
    )
    assert (
        first.trials[0].audit.trial_id
        == analyze(world_state, **settings).trials[0].audit.trial_id
    )


def test_matched_once_and_input_order(simulation_world, monkeypatch):
    plans = generate_candidate_plans(simulation_world)
    baseline = rank_scenario_results(
        [simulate_plan(simulation_world, p) for p in plans]
    )
    generate = r.generate_trial
    execute = r.simulate_plan
    draws, worlds = [], []

    def spy_generate(*args):
        draws.append(args[2])
        return generate(*args)

    def spy_execute(world, plan, duration):
        worlds.append(world.model_dump_json())
        return execute(world, plan, duration)

    monkeypatch.setattr(r, "generate_trial", spy_generate)
    monkeypatch.setattr(r, "simulate_plan", spy_execute)
    first = r.analyze_robustness(
        simulation_world, plans, 60, config(), baseline_results=baseline
    )
    assert draws == [0, 1, 2]
    assert len(worlds) == 9
    assert all(len(set(worlds[i : i + 3])) == 1 for i in range(0, 9, 3))
    second = r.analyze_robustness(
        simulation_world, list(reversed(plans)), 60, config(), baseline_results=baseline
    )
    assert first.model_dump_json() == second.model_dump_json()


def test_inputs_outputs_immutable(simulation_world):
    plans = generate_candidate_plans(simulation_world)
    baseline = rank_scenario_results(
        [simulate_plan(simulation_world, p) for p in plans]
    )
    objects = [simulation_world, *plans, *baseline, DEFAULT_SCORING_POLICY]
    before = [o.model_dump_json() for o in objects]
    result = r.analyze_robustness(
        simulation_world, plans, 60, config(), baseline_results=baseline
    )
    assert before == [o.model_dump_json() for o in objects]
    with pytest.raises(ValidationError):
        result.trials[0].outcomes[0].metrics.people_rescued = 10
    with pytest.raises(ValidationError):
        result.trials[0].audit.seed = 10
    with pytest.raises(ValidationError):
        RobustnessResult.model_validate(result.model_dump() | {"extra": 1})


@pytest.mark.parametrize("shift,accepted", [(-10, False), (10, True)])
def test_route_timing(world_state, make_plan, make_action, shift, accepted):
    world_state.routes[0].closure_minute = 18
    trial, audit = r.generate_trial(
        world_state, config(route_closure_shift_minutes=(shift, shift)), 0, 60
    )
    result = simulate_plan(trial, make_plan(make_action()))
    assert (result.metrics.rejected_actions == 0) == accepted
    change = audit.route_changes[0]
    assert change.original == 18
    assert change.perturbed == max(10, 18 + shift)
    assert change.clamped == (shift < 0)


def test_skipped_closures(world_state):
    world_state.routes[0].closure_minute = None
    _, audit = r.generate_trial(world_state, config(), 0, 60)
    assert audit.skipped[0].reason_code == "already_reported_before_snapshot"
    assert any(s.reason_code == "no_scheduled_closure" for s in audit.skipped)
    world_state.routes[0].closure_minute = 30
    world_state.routes[0].status = RouteStatus.CLOSED
    _, audit = r.generate_trial(world_state, config(), 0, 60)
    assert any(s.reason_code == "closure_not_future" for s in audit.skipped)


@pytest.mark.parametrize("percent,expected", [(0, 5), (1, 6), (20, 6), (40, 7)])
def test_travel_rounding(simulation_world, make_plan, make_action, percent, expected):
    trial, audit = r.generate_trial(
        simulation_world, config(travel_time_increase_percent=(percent, percent)), 0, 60
    )
    assert trial.routes[0].base_travel_minutes == expected
    assert (
        audit.travel_time_changes[0].perturbed >= audit.travel_time_changes[0].original
    )
    result = simulate_plan(trial, make_plan(make_action()))
    completed = next(e for e in result.timeline if e.event_type == "action_completed")
    assert completed.minute == 10 + expected


def test_unavailability(simulation_world, make_plan, make_action):
    result = r.analyze_robustness(
        simulation_world,
        [make_plan(make_action())],
        60,
        config(responder_unavailability_count=1),
    )
    for trial in result.trials:
        assert trial.audit.unavailable_responder_ids == ("bus-1",)
        outcome = trial.outcomes[0]
        assert outcome.metrics.rejected_actions == 1
        assert outcome.failure_reasons[0].reason_code == "responder_unavailable"
        assert outcome.failure_reasons[0].action_id == "action-1"


def test_shelter_clamp_and_admission(simulation_world, make_plan, make_action):
    simulation_world.shelters[0].occupancy = 35
    world, audit = r.generate_trial(
        simulation_world, config(shelter_capacity_reduction_percent=(40, 40)), 0, 60
    )
    assert world.shelters[0].capacity == 35
    assert audit.shelter_capacity_changes[0].clamped
    action = make_action(
        action_type="evacuate",
        community_id="community-1",
        shelter_id="shelter-1",
        people_count=1,
    )
    result = simulate_plan(world, make_plan(action))
    assert result.metrics.people_evacuated == 0 and result.metrics.rejected_actions == 1
    assert any(
        e.metadata.get("reason_code") == "shelter_capacity_exceeded"
        for e in result.timeline
    )


def test_reporting_delay(simulation_world, make_action, make_plan):
    simulation_world.rescue_requests[0].reported_minute = 10
    world, audit = r.generate_trial(
        simulation_world, config(request_reporting_delay_minutes=(15, 15)), 0, 60
    )
    assert audit.request_reporting_delays[0].original == 10
    assert world.rescue_requests[0].reported_minute == 25
    action = make_action(action_type="rescue", request_id="call-1", people_count=5)
    result = simulate_plan(world, make_plan(action))
    assert result.metrics.people_rescued == 0
    assert result.metrics.critical_calls_unanswered == 1
    assert any(
        e.metadata.get("reason_code") == "request_not_active" for e in result.timeline
    )


def test_synthetic_requests_safe_and_stable(world_state):
    world_state.nodes.append(
        LocationNode(id="unmodeled", name="Hypothetical empty zone")
    )
    c = config(additional_request_count=2)
    first, audit = r.generate_trial(world_state, c, 0, 60)
    second, repeated = r.generate_trial(world_state, c, 0, 60)
    assert audit == repeated and first == second
    ids = audit.synthetic_additional_request_ids
    assert len(ids) == 1 and ids[0].startswith("synthetic-")
    assert len({q.id for q in first.rescue_requests}) == len(first.rescue_requests)
    assert first.rescue_requests[-1].node_id == "unmodeled"
    assert first.metadata["robustness_synthetic_requests"]["historical"] is False
    assert any(s.reason_code == "no_disjoint_non_safe_node" for s in audit.skipped)


@pytest.mark.parametrize(
    "values,expected",
    [([], None), ([3], 3.0), ([1, 3, 2], 2.0), ([-3, -1], -2.0), ([1, 2, 4, 5], 3.0)],
)
def test_median(values, expected):
    assert r.stable_median(values) == expected


def outcome(trial_id, score, viable=True):
    result = scoring_result(people_rescued=2, people_evacuated=4)
    result.score = score
    result.viable = viable
    result.status = PlanStatus.COMPLETED if viable else PlanStatus.FAILED
    result.nonviable_reasons = [] if viable else ["run_status:failed"]
    return r.trial_outcome(trial_id, result)


def test_aggregation_null_negative_nonviable():
    outcomes = (outcome("a", -9.0, False), outcome("b", 3.0), outcome("c", None))
    summary = r.summarize_plan("plan", 10.0, outcomes, 1)
    assert summary.completed_trial_count == 3 and summary.viable_trial_count == 2
    assert summary.viability_rate == float(Fraction(2, 3))
    assert summary.minimum_score == -9.0 and summary.maximum_score == 3.0
    assert summary.mean_score == summary.median_score == -3.0
    assert summary.best_trial_id == "b" and summary.worst_trial_id == "a"
    assert {x.reason_code: x.count for x in summary.reason_counts} == {
        "numeric_score_unavailable": 1,
        "run_status:failed": 1,
    }
    tied = r.summarize_plan("plan", 0.0, (outcome("z", 1.0), outcome("a", 1.0)), 0)
    assert tied.best_trial_id == tied.worst_trial_id == "a"
    missing = r.summarize_plan("plan", None, (outcome("a", None),), 0)
    assert missing.minimum_score is missing.mean_score is missing.best_trial_id is None


@pytest.mark.parametrize(
    "change",
    [
        {"viable_trial_count": 0, "viability_rate": 0.0, "median_score": 999.0},
        {"median_score": 0.0, "minimum_score": 999.0},
        {"minimum_score": 0.0, "baseline_score": 999.0},
        {"baseline_score": 0.0},
        {},
    ],
)
def test_order_tiebreakers(change):
    best = r.summarize_plan("a", 1.0, (outcome("t", 1.0),), 0)
    other = best.model_copy(update={"plan_id": "b", **change})
    assert r.robustness_order([other, best]) == ("a", "b")


def test_recommendation_stability(simulation_world):
    result = analyze(simulation_world)
    baseline = result.baseline_recommended_plan_id
    count = sum(t.ranking[0] == baseline for t in result.trials)
    assert result.recommendation_stability_rate == count / 3
    assert sum(s.first_place_trial_count for s in result.summaries) == 3


def test_nepal_demo_repeat_no_network(monkeypatch):
    from ark_api.agents.providers.mirofish import MiroFishHttpProposalProvider
    from ark_api.routes.simulations import run_response_simulation

    def forbidden(*args, **kwargs):
        pytest.fail("No provider or network calls in robustness")

    monkeypatch.setattr(MiroFishHttpProposalProvider, "propose_actions", forbidden)
    import socket

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    root = Path(__file__).resolve().parents[3]
    request = SimulationRequest.model_validate_json(
        (root / "data/scenarios/kantipur-river/nepal_nakkhu_demo_v1.json").read_text()
    )
    request.robustness = RobustnessConfig(
        enabled=True, responder_unavailability_count=1, additional_request_count=1
    )
    response = run_response_simulation(request)
    assert response.recommended_plan_id == "balanced-response"
    assert len(response.robustness.trials) == 20
    script = root / "apps/api/scripts/run_nepal_robustness_demo.py"
    outputs = [
        subprocess.run(
            [sys.executable, str(script)], check=True, capture_output=True, text=True
        ).stdout
        for _ in range(2)
    ]
    assert outputs[0] == outputs[1]
    assert "Synthetic sensitivity tests, not outcome probabilities" in outputs[0]


def test_failed_plan_does_not_stop_trials(simulation_world, monkeypatch):
    execute = r.simulate_plan
    calls = []

    def failed_trial(world, plan, duration):
        calls.append(plan.id)
        result = execute(world, plan, duration)
        if plan.id == "immediate-rescue":
            result.status = PlanStatus.FAILED
        return result

    monkeypatch.setattr(r, "simulate_plan", failed_trial)
    result = analyze(simulation_world)
    assert len(calls) == 12  # Three baseline runs plus 3 x 3 matched trials.
    summary = next(s for s in result.summaries if s.plan_id == "immediate-rescue")
    assert summary.nonviable_trial_count == 3
    assert summary.minimum_score is not None
    assert all(len(t.outcomes) == 3 for t in result.trials)


def test_hundred_trials_not_including_baseline(simulation_world, make_plan):
    result = r.analyze_robustness(
        simulation_world, [make_plan()], 1, config(trial_count=100)
    )
    assert len(result.trials) == 100
    assert result.summaries[0].completed_trial_count == 100


def test_no_baseline_recommendation(simulation_world, monkeypatch):
    execute = r.simulate_plan

    def failed(*args):
        result = execute(*args)
        result.status = PlanStatus.FAILED
        return result

    monkeypatch.setattr(r, "simulate_plan", failed)
    result = analyze(simulation_world)
    assert result.baseline_recommended_plan_id is None
    assert result.recommendation_stability_rate is None
    assert sum(s.first_place_trial_count for s in result.summaries) == 3


def test_synthetic_id_collision(world_state):
    c = config(additional_request_count=1)
    collision = "synthetic-" + r._digest(c.seed, 0, "new-request", "0")[:24]
    world_state.rescue_requests[0].id = collision
    _, audit = r.generate_trial(world_state, c, 0, 60)
    assert not audit.synthetic_additional_request_ids
    assert any(s.reason_code == "synthetic_id_collision" for s in audit.skipped)


def test_shelter_positive_minimum(simulation_world):
    simulation_world.shelters[0].capacity = 1
    world, audit = r.generate_trial(
        simulation_world, config(shelter_capacity_reduction_percent=(40, 40)), 0, 60
    )
    assert world.shelters[0].capacity == 1
    assert audit.shelter_capacity_changes[0].clamped


def test_multiple_unavailable_selection_stable(simulation_world):
    simulation_world.responders.extend(
        [
            simulation_world.responders[0].model_copy(update={"id": name})
            for name in ("c", "a", "b")
        ]
    )
    c = config(responder_unavailability_count=2)
    _, first = r.generate_trial(simulation_world, c, 0, 60)
    simulation_world.responders.reverse()
    _, second = r.generate_trial(simulation_world, c, 0, 60)
    assert first.unavailable_responder_ids == second.unavailable_responder_ids
    assert len(first.unavailable_responder_ids) == 2
    assert first.unavailable_responder_ids == tuple(
        sorted(first.unavailable_responder_ids)
    )
