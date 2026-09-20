from decimal import localcontext
from itertools import permutations

import pytest
from pydantic import ValidationError

from ark_api.simulation.engine import simulate_plan
from ark_api.simulation.models import (
    PlanStatus,
    ScenarioMetrics,
    ScenarioResult,
    ScoreContribution,
    SimulationResponse,
    TimelineEvent,
)
from ark_api.simulation.plans import generate_candidate_plans
from ark_api.simulation.scoring import (
    DEFAULT_SCORING_POLICY,
    HardConstraints,
    ScoringPolicy,
    ScoringWeights,
    rank_scenario_results,
    recommend_plan_id,
    score_scenario_result,
)
from ark_api.simulation.validation import ReasonCode


def result(plan_id="plan", **metrics):
    values = dict.fromkeys(ScoringWeights.model_fields, 0)
    values["average_response_minutes"] = None
    values.update(metrics)
    return ScenarioResult(
        plan_id=plan_id,
        status="completed",
        simulation_minutes=60,
        metrics=ScenarioMetrics(**values),
    )


def zero_policy():
    return ScoringPolicy(
        weights=ScoringWeights(**dict.fromkeys(ScoringWeights.model_fields, 0.0))
    )


def test_exact_default_contributions_and_total():
    scored = score_scenario_result(
        result(
            people_rescued=2,
            people_evacuated=3,
            people_isolated=1,
            responders_stranded=1,
            critical_calls_completed=1,
            critical_calls_unanswered=2,
            average_response_minutes=4.0,
            shelter_peak_overflow=2,
            rejected_actions=3,
        )
    )
    expected = {
        "people_rescued": (2, 10, 20),
        "people_evacuated": (3, 6, 18),
        "people_isolated": (1, -15, -15),
        "responders_stranded": (1, -100, -100),
        "critical_calls_completed": (1, 25, 25),
        "critical_calls_unanswered": (2, -40, -80),
        "average_response_minutes": (4, -0.5, -2),
        "shelter_peak_overflow": (2, -20, -40),
        "rejected_actions": (3, -5, -15),
    }
    assert {
        c.metric: (c.raw_value, c.weight, c.contribution)
        for c in scored.score_breakdown
    } == expected
    assert scored.score == -189.0
    assert all(
        c.explanation and "ark-response-priorities@1.0.0" in c.explanation
        for c in scored.score_breakdown
    )
    assert any("subtracts" in c.explanation for c in scored.score_breakdown)


def test_null_average_is_preserved_and_contributes_zero():
    scored = score_scenario_result(result())
    response = next(
        c for c in scored.score_breakdown if c.metric == "average_response_minutes"
    )
    assert response.raw_value is None
    assert response.contribution == 0.0
    assert "unavailable" in response.explanation
    assert scored.metrics.average_response_minutes is None
    assert scored.score == 0.0
    assert scored.viable is True


def test_zero_average_is_distinct_from_unknown():
    scored = score_scenario_result(result(average_response_minutes=0.0))
    response = next(
        c for c in scored.score_breakdown if c.metric == "average_response_minutes"
    )
    assert response.raw_value == 0.0
    assert "unavailable" not in response.explanation


def test_negative_score_is_valid():
    scored = score_scenario_result(result(people_isolated=10))
    assert scored.score == -150.0
    assert scored.viable is True


def test_inputs_preserved_and_existing_fields_recomputed():
    original = result(people_rescued=1)
    original.score = 999.0
    original.score_breakdown = [
        ScoreContribution(
            metric="fake",
            raw_value=999.0,
            weight=1.0,
            contribution=999.0,
            explanation="Stale",
        )
    ]
    original.viable = False
    original.nonviable_reasons = ["stale"]
    original.timeline = [
        TimelineEvent(
            id="event",
            minute=10,
            event_type="simulation_completed",
            message="Horizon",
            metadata={"nested": [1]},
        )
    ]
    original.violations = ["A free-text note"]
    before = original.model_dump_json()
    scored = score_scenario_result(original)
    assert scored.score == 10.0
    assert len(scored.score_breakdown) == 9
    assert scored.viable is True
    assert scored.nonviable_reasons == []
    assert scored.metrics == original.metrics
    assert scored.timeline == original.timeline
    assert scored.violations == original.violations
    assert scored.status == original.status
    scored.timeline[0].metadata["nested"].append(2)
    scored.metrics.people_rescued = 9
    assert original.model_dump_json() == before


def test_custom_policy_and_decimal_arithmetic():
    policy = ScoringPolicy(
        policy_id="custom",
        policy_version="2.1.0",
        weights=ScoringWeights(people_rescued=0.1, people_evacuated=0.2),
    )
    scored = score_scenario_result(result(people_rescued=1, people_evacuated=1), policy)
    assert scored.score == 0.3
    assert scored.score_breakdown[0].contribution == 0.1
    assert "custom@2.1.0" in scored.score_breakdown[0].explanation
    with localcontext() as context:
        context.prec = 2
        assert (
            score_scenario_result(result(people_rescued=1, people_evacuated=1), policy)
            == scored
        )


@pytest.mark.parametrize(
    "weight", [float("nan"), float("inf"), -float("inf"), "wrong", "10", True]
)
def test_invalid_weights_rejected(weight):
    with pytest.raises(ValidationError):
        ScoringWeights(people_rescued=weight)


@pytest.mark.parametrize(
    "version", ["", "1", "1.0", "v1.0.0", "01.0.0", "1.0.0\n", " 1.0.0", 1]
)
def test_invalid_policy_version(version):
    with pytest.raises(ValidationError):
        ScoringPolicy(policy_version=version)


def test_policy_is_deeply_immutable():
    with pytest.raises(ValidationError):
        DEFAULT_SCORING_POLICY.policy_version = "2.0.0"
    with pytest.raises(ValidationError):
        DEFAULT_SCORING_POLICY.weights.people_rescued = 99.0
    with pytest.raises(ValidationError):
        DEFAULT_SCORING_POLICY.hard_constraints.max_responders_stranded = 9
    assert isinstance(
        DEFAULT_SCORING_POLICY.hard_constraints.safety_failure_codes, frozenset
    )


def test_stranding_is_nonviable_but_still_scored():
    scored = score_scenario_result(result(responders_stranded=1))
    assert scored.viable is False
    assert scored.nonviable_reasons == ["responders_stranded"]
    assert scored.score == -100.0
    assert len(scored.score_breakdown) == 9
    assert scored.status == PlanStatus.COMPLETED


@pytest.mark.parametrize(
    "code", sorted(DEFAULT_SCORING_POLICY.hard_constraints.safety_failure_codes)
)
def test_exact_stable_hard_safety_violation(code):
    original = result()
    original.violations = [code.value]
    scored = score_scenario_result(original)
    assert scored.viable is False
    assert scored.nonviable_reasons == [f"hard_safety_failure:{code.value}"]


def test_structured_failure_and_deterministic_reasons():
    original = result(responders_stranded=1)
    original.timeline = [
        TimelineEvent(
            id="failed",
            minute=10,
            event_type="action_failed",
            actor_id="responder",
            message="Failure",
            metadata={"reason_code": "capacity_exceeded"},
        )
    ]
    original.violations = ["capacity_exceeded", "no_route", "capacity_exceeded"]
    assert score_scenario_result(original).nonviable_reasons == [
        "hard_safety_failure:capacity_exceeded",
        "hard_safety_failure:no_route",
        "responders_stranded",
    ]


def test_rejected_action_does_not_make_plan_nonviable():
    original = result(rejected_actions=1)
    original.violations = [
        "action-1: capacity_exceeded: people_count exceeds capacity."
    ]
    original.timeline = [
        TimelineEvent(
            id="rejected",
            minute=10,
            event_type="action_rejected",
            message="Rejected",
            metadata={"reason_code": "capacity_exceeded"},
        )
    ]
    scored = score_scenario_result(original)
    assert scored.score == -5.0
    assert scored.viable is True


@pytest.mark.parametrize(
    "text",
    [
        "Something says no_route",
        "unsafe",
        "capacity_exceeded happened",
        "new_unknown_safety_code",
        "people_unavailable",
    ],
)
def test_never_infer_hard_failure_from_prose_or_unknown_codes(text):
    original = result()
    original.violations = [text]
    assert score_scenario_result(original).viable is True


def test_custom_hard_constraints():
    policy = ScoringPolicy(
        hard_constraints=HardConstraints(
            max_responders_stranded=1,
            safety_failure_codes=frozenset({ReasonCode.NO_ROUTE}),
        )
    )
    original = result(responders_stranded=1)
    original.violations = ["capacity_exceeded"]
    assert score_scenario_result(original, policy).viable is True


def test_viability_dominates_score():
    unsafe = result("unsafe", people_rescued=1000, responders_stranded=1)
    viable = result("viable", people_isolated=100)
    ranked = rank_scenario_results([unsafe, viable])
    assert [r.plan_id for r in ranked] == ["viable", "unsafe"]
    assert ranked[0].score < ranked[1].score
    assert recommend_plan_id(ranked) == "viable"


def test_higher_score_precedes_lower_isolation():
    higher = result("higher", people_rescued=100, people_isolated=1)
    lower = result("lower")
    assert rank_scenario_results([lower, higher])[0].plan_id == "higher"


@pytest.mark.parametrize(
    "good,bad",
    [
        ({"people_isolated": 0, "responders_stranded": 4}, {"people_isolated": 1}),
        (
            {"responders_stranded": 1, "critical_calls_unanswered": 5},
            {"responders_stranded": 2},
        ),
        (
            {"critical_calls_unanswered": 0, "average_response_minutes": 10.0},
            {"critical_calls_unanswered": 1, "average_response_minutes": 0.0},
        ),
        ({"average_response_minutes": 1.0}, {"average_response_minutes": 2.0}),
        ({"average_response_minutes": 0.0}, {"average_response_minutes": None}),
        ({"average_response_minutes": 50.0}, {"average_response_minutes": None}),
    ],
)
def test_metric_tie_breakers_in_exact_order(good, bad):
    policy = ScoringPolicy(
        weights=zero_policy().weights,
        hard_constraints=HardConstraints(max_responders_stranded=10),
    )
    assert (
        rank_scenario_results([result("a", **bad), result("z", **good)], policy)[
            0
        ].plan_id
        == "z"
    )


def test_lexicographic_final_tie_breaker_and_input_order():
    inputs = [result("c"), result("a"), result("b")]
    snapshots = [r.model_dump_json() for r in inputs]
    expected = [r.model_dump_json() for r in rank_scenario_results(inputs)]
    for ordering in permutations(inputs):
        assert [
            r.model_dump_json() for r in rank_scenario_results(list(ordering))
        ] == expected
    assert [r.plan_id for r in rank_scenario_results(inputs)] == ["a", "b", "c"]
    assert [r.model_dump_json() for r in inputs] == snapshots
    assert [r.plan_id for r in inputs] == ["c", "a", "b"]


def test_duplicate_ids_rejected():
    for function in (rank_scenario_results, recommend_plan_id):
        with pytest.raises(ValueError, match="Duplicate"):
            function([result(), result()])


@pytest.mark.parametrize(
    "status", [PlanStatus.DRAFT, PlanStatus.READY, PlanStatus.RUNNING]
)
def test_nonterminal_rejected(status):
    original = result()
    original.status = status
    with pytest.raises(ValueError, match="terminal"):
        score_scenario_result(original)
    for function in (rank_scenario_results, recommend_plan_id):
        with pytest.raises(ValueError, match="terminal"):
            function([original])


@pytest.mark.parametrize("status", [PlanStatus.FAILED, PlanStatus.CANCELLED])
def test_failed_or_cancelled_terminal_runs_are_not_recommended(status):
    original = result(people_rescued=1)
    original.status = status
    scored = score_scenario_result(original)
    assert scored.score == 10.0
    assert scored.nonviable_reasons == [f"run_status:{status.value}"]
    assert recommend_plan_id([original]) is None


def test_empty_and_single_results():
    assert rank_scenario_results([]) == []
    assert recommend_plan_id([]) is None
    assert recommend_plan_id([result("single")]) == "single"


def test_all_nonviable_no_recommendation():
    assert (
        recommend_plan_id(
            [result("a", responders_stranded=1), result("b", responders_stranded=2)]
        )
        is None
    )


def test_recommendation_recomputes_untrusted_flags_and_custom_scores():
    bad = result("bad", responders_stranded=1)
    bad.viable = True
    bad.score = 999999.0
    good = result("good")
    assert recommend_plan_id([bad, good]) == "good"
    policy = ScoringPolicy(weights=ScoringWeights(people_rescued=-10.0))
    assert (
        recommend_plan_id(
            [result("rescued", people_rescued=1), result("empty")], policy
        )
        == "empty"
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_metric_attempts_rejected(value):
    original = result()
    original.metrics.average_response_minutes = (
        value  # Bypass constructor deliberately.
    )
    with pytest.raises(ValidationError):
        score_scenario_result(original)


def test_nonfinite_policy_copy_bypass_rejected():
    invalid = ScoringPolicy().model_copy(
        update={
            "weights": ScoringWeights().model_copy(
                update={"people_rescued": float("inf")}
            ),
        }
    )
    with pytest.raises(ValidationError):
        score_scenario_result(result(), invalid)


def test_finite_output_overflow_is_explicit():
    with pytest.raises(ValueError, match="finite float"):
        score_scenario_result(result(people_rescued=10**400))


def test_viability_and_null_raw_value_schema_round_trip():
    original = result()
    assert original.viable is None
    assert original.nonviable_reasons == []
    scored = score_scenario_result(original)
    assert ScenarioResult.model_validate_json(scored.model_dump_json()) == scored
    with pytest.raises(ValidationError):
        ScenarioResult.model_validate(original.model_dump() | {"viable": "true"})


def test_full_pipeline_integration(simulation_world):
    before = simulation_world.model_dump_json()
    plans = generate_candidate_plans(simulation_world)
    results = [simulate_plan(simulation_world.model_copy(deep=True), p) for p in plans]
    scored = [score_scenario_result(r) for r in results]
    ranked = rank_scenario_results(scored)
    assert len(ranked) == 3
    assert all(r.score is not None and len(r.score_breakdown) == 9 for r in ranked)
    assert [r.model_dump_json() for r in ranked] == [
        r.model_dump_json() for r in rank_scenario_results(list(reversed(results)))
    ]
    recommendation = recommend_plan_id(ranked)
    if any(r.viable for r in ranked):
        assert recommendation == next(r.plan_id for r in ranked if r.viable)
    else:
        assert recommendation is None
    response = SimulationResponse(
        recommended_plan_id=recommendation,
        results=ranked,
        disclaimer="Simulation comparison only.",
        model_version="0.1.0",
    )
    assert (
        SimulationResponse.model_validate_json(response.model_dump_json()) == response
    )
    assert simulation_world.model_dump_json() == before
