"""Matched deterministic sensitivity trials; no planning or model calls."""

import hashlib
import json
from collections import Counter
from fractions import Fraction

from ark_api.simulation.engine import simulate_plan
from ark_api.simulation.models import (
    EventType,
    PerturbationAudit,
    PerturbationChange,
    PlanRobustnessSummary,
    PlanStatus,
    ReasonCount,
    RequestStatus,
    RescueRequest,
    ResponderStatus,
    ResponsePlan,
    RobustnessConfig,
    RobustnessMetrics,
    RobustnessResult,
    RobustnessTrial,
    RobustnessTrialOutcome,
    RouteStatus,
    ScenarioResult,
    SkippedPerturbation,
    TrialFailureReason,
    WorldState,
)
from ark_api.simulation.scoring import (
    DEFAULT_SCORING_POLICY,
    ScoringPolicy,
    rank_scenario_results,
    recommend_plan_id,
)


class RobustnessInputError(ValueError):
    """Expected invalid analysis configuration, suitable for a structured 400."""


def _digest(seed: int, index: int, kind: str, entity_id: str) -> str:
    value = json.dumps(
        ["ark-robustness-v1", seed, index, kind, entity_id],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sample(config, index, kind, entity_id, bounds):
    low, high = bounds
    return low + int(_digest(config.seed, index, kind, entity_id), 16) % (
        high - low + 1
    )


def _available(world):
    return [
        r
        for r in world.responders
        if r.status == ResponderStatus.AVAILABLE and r.current_assignment_id is None
    ]


def validate_configuration(world, config):
    if config.responder_unavailability_count > len(_available(world)):
        raise RobustnessInputError("Unavailability count exceeds available responders.")


def generate_trial(
    world: WorldState, config: RobustnessConfig, index: int, duration_minutes: int
) -> tuple[WorldState, PerturbationAudit]:
    """One isolated variation per trial, shared by all plans. Integer-only draws."""
    validate_configuration(world, config)
    varied = world.model_copy(deep=True)
    routes, travel, shelters, delays, skipped = [], [], [], [], []
    suffix = _digest(config.seed, index, "trial", world.scenario_id)[:16]
    trial_id = f"trial-{index:03d}-{suffix}"

    def skip(category, entity_id, code):
        skipped.append(
            SkippedPerturbation(
                category=category, entity_id=entity_id, reason_code=code
            )
        )

    for edge in sorted(varied.routes, key=lambda r: r.id):
        if edge.closure_minute is None:
            skip("route_closure", edge.id, "no_scheduled_closure")
        elif (
            edge.status == RouteStatus.CLOSED
            or edge.closure_minute <= world.current_minute
        ):
            skip("route_closure", edge.id, "closure_not_future")
        else:
            shift = _sample(
                config, index, "closure", edge.id, config.route_closure_shift_minutes
            )
            original = edge.closure_minute
            edge.closure_minute = max(world.current_minute, original + shift)
            clamped = edge.closure_minute != original + shift
            routes.append(
                PerturbationChange(
                    entity_id=edge.id,
                    original=original,
                    perturbed=edge.closure_minute,
                    sampled_value=shift,
                    clamped=clamped,
                    reason_code="clamped_to_current_minute" if clamped else None,
                )
            )
        percent = _sample(
            config, index, "travel", edge.id, config.travel_time_increase_percent
        )
        original = edge.base_travel_minutes
        # Exact ceiling of original * (100 + percent) / 100; never faster.
        edge.base_travel_minutes = (original * (100 + percent) + 99) // 100
        travel.append(
            PerturbationChange(
                entity_id=edge.id,
                original=original,
                perturbed=edge.base_travel_minutes,
                sampled_value=percent,
            )
        )

    selected = sorted(
        _available(varied),
        key=lambda r: (_digest(config.seed, index, "unavailable", r.id), r.id),
    )
    unavailable = selected[: config.responder_unavailability_count]
    for responder in unavailable:
        responder.status = ResponderStatus.UNAVAILABLE
    for shelter in sorted(varied.shelters, key=lambda s: s.id):
        percent = _sample(
            config,
            index,
            "shelter",
            shelter.id,
            config.shelter_capacity_reduction_percent,
        )
        original = shelter.capacity
        proposed = original * (100 - percent) // 100
        shelter.capacity = max(1, shelter.occupancy, proposed)
        clamped = proposed != shelter.capacity
        shelters.append(
            PerturbationChange(
                entity_id=shelter.id,
                original=original,
                perturbed=shelter.capacity,
                sampled_value=percent,
                clamped=clamped,
                reason_code="clamped_to_occupancy_or_positive_minimum"
                if clamped
                else None,
            )
        )
    for request in sorted(varied.rescue_requests, key=lambda r: r.id):
        if request.status != RequestStatus.PENDING:
            skip("reporting_delay", request.id, "request_not_pending")
            continue
        if request.reported_minute < world.current_minute:
            skip("reporting_delay", request.id, "already_reported_before_snapshot")
            continue
        delay = _sample(
            config,
            index,
            "reporting",
            request.id,
            config.request_reporting_delay_minutes,
        )
        original = request.reported_minute
        request.reported_minute += delay
        delays.append(
            PerturbationChange(
                entity_id=request.id,
                original=original,
                perturbed=request.reported_minute,
                sampled_value=delay,
            )
        )

    # The schema has no person/cohort registry. Only unused non-safe nodes may
    # host explicitly new, hypothetical one-person cohorts. Never clone a call
    # or draw people from an existing community/request population.
    occupied = {r.node_id for r in world.rescue_requests} | {
        c.node_id for c in world.communities
    }
    occupied |= {s.node_id for s in world.shelters}
    candidates = sorted(
        (n for n in world.nodes if n.id not in occupied and not n.is_safe_zone),
        key=lambda n: (_digest(config.seed, index, "new-node", n.id), n.id),
    )
    added = []
    existing_ids = {r.id for r in world.rescue_requests}
    for slot in range(config.additional_request_count):
        request_id = (
            "synthetic-" + _digest(config.seed, index, "new-request", str(slot))[:24]
        )
        if request_id in existing_ids:
            skip("additional_request", request_id, "synthetic_id_collision")
        elif slot >= len(candidates):
            skip("additional_request", request_id, "no_disjoint_non_safe_node")
        else:
            varied.rescue_requests.append(
                RescueRequest(
                    id=request_id,
                    node_id=candidates[slot].id,
                    people_count=1,
                    urgency=4,
                    reported_minute=world.current_minute
                    + _sample(
                        config,
                        index,
                        "new-reporting",
                        request_id,
                        (0, duration_minutes),
                    ),
                    required_capabilities=set(),
                    status=RequestStatus.PENDING,
                )
            )
            existing_ids.add(request_id)
            added.append(request_id)
    if added:
        varied.metadata["robustness_synthetic_requests"] = {
            "ids": sorted(added),
            "provenance": "new hypothetical disjoint cohorts",
            "historical": False,
        }
    varied = WorldState.model_validate(varied.model_dump())
    return varied, PerturbationAudit(
        trial_index=index,
        trial_id=trial_id,
        seed=config.seed,
        route_changes=tuple(routes),
        travel_time_changes=tuple(travel),
        unavailable_responder_ids=tuple(sorted(r.id for r in unavailable)),
        shelter_capacity_changes=tuple(shelters),
        request_reporting_delays=tuple(delays),
        synthetic_additional_request_ids=tuple(sorted(added)),
        skipped=tuple(
            sorted(skipped, key=lambda s: (s.category, s.entity_id, s.reason_code))
        ),
    )


def trial_outcome(trial_id: str, result: ScenarioResult) -> RobustnessTrialOutcome:
    reasons = []
    for event in result.timeline:
        if event.event_type not in {EventType.ACTION_REJECTED, EventType.ACTION_FAILED}:
            continue
        code = event.metadata.get("reason_code")
        if isinstance(code, str) and code:
            action_id = event.metadata.get("action_id")
            reasons.append(
                TrialFailureReason(
                    action_id=action_id if isinstance(action_id, str) else None,
                    responder_id=event.actor_id,
                    reason_code=code,
                )
            )
    return RobustnessTrialOutcome(
        trial_id=trial_id,
        plan_id=result.plan_id,
        status=result.status,
        viable=result.viable is True,
        score=result.score,
        score_unavailable_reason="numeric_score_unavailable"
        if result.score is None
        else None,
        metrics=RobustnessMetrics.model_validate(result.metrics.model_dump()),
        violations=tuple(result.violations),
        nonviable_reasons=tuple(result.nonviable_reasons),
        failure_reasons=tuple(
            sorted(
                reasons,
                key=lambda r: (r.reason_code, r.action_id or "", r.responder_id or ""),
            )
        ),
    )


def stable_median(values) -> float | None:
    """Middle value, or exact arithmetic mean of the two middle values."""
    ordered = sorted(Fraction(str(v)) for v in values)
    if not ordered:
        return None
    size = len(ordered)
    return float((ordered[(size - 1) // 2] + ordered[size // 2]) / 2)


def summarize_plan(
    plan_id: str,
    baseline_score: float | None,
    outcomes: tuple[RobustnessTrialOutcome, ...],
    first_place_count: int,
) -> PlanRobustnessSummary:
    if not outcomes:
        raise ValueError("At least one completed trial is required")
    numeric = [o for o in outcomes if o.score is not None]
    scores = [o.score for o in numeric]
    rescued = [o.metrics.people_rescued for o in outcomes]
    evacuated = [o.metrics.people_evacuated for o in outcomes]
    viable = sum(o.viable for o in outcomes)
    reasons = Counter(r.reason_code for o in outcomes for r in o.failure_reasons)
    reasons.update(reason for o in outcomes for reason in o.nonviable_reasons)
    reasons.update(
        o.score_unavailable_reason for o in outcomes if o.score_unavailable_reason
    )
    best = min(numeric, key=lambda o: (-o.score, o.trial_id)) if numeric else None
    worst = min(numeric, key=lambda o: (o.score, o.trial_id)) if numeric else None
    return PlanRobustnessSummary(
        plan_id=plan_id,
        completed_trial_count=len(outcomes),
        viable_trial_count=viable,
        nonviable_trial_count=len(outcomes) - viable,
        viability_rate=float(Fraction(viable, len(outcomes))),
        baseline_score=baseline_score,
        minimum_score=min(scores) if scores else None,
        median_score=stable_median(scores),
        maximum_score=max(scores) if scores else None,
        mean_score=float(
            sum((Fraction(str(s)) for s in scores), Fraction()) / len(scores)
        )
        if scores
        else None,
        minimum_rescued=min(rescued),
        median_rescued=stable_median(rescued),
        maximum_rescued=max(rescued),
        minimum_evacuated=min(evacuated),
        median_evacuated=stable_median(evacuated),
        maximum_evacuated=max(evacuated),
        maximum_isolated_population=max(o.metrics.people_isolated for o in outcomes),
        maximum_unanswered_critical_requests=max(
            o.metrics.critical_calls_unanswered for o in outcomes
        ),
        maximum_stranded_responders=max(
            o.metrics.responders_stranded for o in outcomes
        ),
        reason_counts=tuple(
            ReasonCount(reason_code=k, count=v) for k, v in sorted(reasons.items())
        ),
        best_trial_id=best.trial_id if best else None,
        worst_trial_id=worst.trial_id if worst else None,
        first_place_trial_count=first_place_count,
    )


def robustness_order(summaries) -> tuple[str, ...]:
    def descending(value):
        return (value is None, -value if value is not None else 0)

    return tuple(
        s.plan_id
        for s in sorted(
            summaries,
            key=lambda s: (
                -Fraction(s.viable_trial_count, s.completed_trial_count),
                descending(s.median_score),
                descending(s.minimum_score),
                descending(s.baseline_score),
                s.plan_id,
            ),
        )
    )


def analyze_robustness(
    world_state: WorldState,
    plans: list[ResponsePlan],
    duration_minutes: int,
    config: RobustnessConfig,
    policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
    *,
    baseline_results: list[ScenarioResult] | None = None,
) -> RobustnessResult | None:
    """Baseline is separate; each matched trial validates through simulate_plan."""
    config = RobustnessConfig.model_validate(config.model_dump())
    if not config.enabled:
        return None
    world = WorldState.model_validate(world_state.model_dump())
    validate_configuration(world, config)
    if type(duration_minutes) is not int or not 1 <= duration_minutes <= 1440:
        raise RobustnessInputError("Duration must be between 1 and 1440 minutes.")
    if not 1 <= len(plans) <= 20 or len({p.id for p in plans}) != len(plans):
        raise RobustnessInputError("Require 1 to 20 plans with unique IDs.")
    plans = sorted(
        (ResponsePlan.model_validate(p.model_dump()) for p in plans), key=lambda p: p.id
    )
    if any(p.status != PlanStatus.READY for p in plans):
        raise RobustnessInputError("Plans must be ready before robustness analysis.")
    policy = ScoringPolicy.model_validate(policy.model_dump())
    if baseline_results is None:
        baseline_results = [simulate_plan(world, p, duration_minutes) for p in plans]
    if {r.plan_id for r in baseline_results} != {p.id for p in plans}:
        raise RobustnessInputError("Baseline results must match plan IDs.")
    baseline = rank_scenario_results(baseline_results, policy)
    baseline_recommendation = recommend_plan_id(baseline, policy)
    baseline_scores = {r.plan_id: r.score for r in baseline}
    trials = []
    first_place = Counter()
    for index in range(config.trial_count):
        varied, audit = generate_trial(world, config, index, duration_minutes)
        # The existing engine copies both inputs and records action rejection as
        # normal terminal outcomes. No action is deleted and no plan is regenerated.
        results = [simulate_plan(varied, plan, duration_minutes) for plan in plans]
        ranked = rank_scenario_results(results, policy)
        first_place[ranked[0].plan_id] += 1
        trials.append(
            RobustnessTrial(
                audit=audit,
                outcomes=tuple(
                    trial_outcome(audit.trial_id, r)
                    for r in sorted(ranked, key=lambda r: r.plan_id)
                ),
                ranking=tuple(r.plan_id for r in ranked),
            )
        )
    summaries = tuple(
        summarize_plan(
            plan.id,
            baseline_scores[plan.id],
            tuple(o for t in trials for o in t.outcomes if o.plan_id == plan.id),
            first_place[plan.id],
        )
        for plan in plans
    )
    return RobustnessResult(
        seed=config.seed,
        trial_count=config.trial_count,
        completed_matched_trials=len(trials),
        baseline_recommended_plan_id=baseline_recommendation,
        recommendation_stability_rate=(
            float(Fraction(first_place[baseline_recommendation], len(trials)))
            if baseline_recommendation is not None
            else None
        ),
        robustness_order=robustness_order(summaries),
        summaries=summaries,
        trials=tuple(trials),
    )
