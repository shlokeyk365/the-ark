"""Transparent policy utility scores; never probabilities or confidence values."""

from fractions import Fraction
from math import isfinite
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ark_api.simulation.models import (
    EventType,
    FiniteFloat,
    NonemptyString,
    NonnegativeInt,
    PlanStatus,
    ScenarioResult,
    ScoreContribution,
)
from ark_api.simulation.validation import ReasonCode


class _FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class ScoringWeights(_FrozenConfig):
    """All default weights live here, in stable contribution order."""

    people_rescued: FiniteFloat = 10.0
    people_evacuated: FiniteFloat = 6.0
    people_isolated: FiniteFloat = -15.0
    responders_stranded: FiniteFloat = -100.0
    critical_calls_completed: FiniteFloat = 25.0
    critical_calls_unanswered: FiniteFloat = -40.0
    average_response_minutes: FiniteFloat = -0.5
    shelter_peak_overflow: FiniteFloat = -20.0
    rejected_actions: FiniteFloat = -5.0


class HardConstraints(_FrozenConfig):
    max_responders_stranded: NonnegativeInt = 0
    # These existing validator codes are hard failures ONLY when explicitly
    # reported as standalone violations or in ACTION_FAILED event metadata.
    # ACTION_REJECTED events and the engine's rejection prose are never hard.
    safety_failure_codes: frozenset[ReasonCode] = frozenset(
        {
            ReasonCode.CAPACITY_EXCEEDED,
            ReasonCode.SHELTER_CAPACITY_EXCEEDED,
            ReasonCode.SHELTER_CLOSED,
            ReasonCode.MISSING_CAPABILITY,
            ReasonCode.NO_ROUTE,
        }
    )


class ScoringPolicy(_FrozenConfig):
    policy_id: NonemptyString = "ark-response-priorities"
    policy_version: Annotated[
        str,
        Field(
            strict=True,
            pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$",
        ),
    ] = "1.0.0"
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    description: NonemptyString = (
        "Configurable operating priorities for comparing simulated response outcomes."
    )

    @field_validator("policy_version")
    @classmethod
    def reject_trailing_newline(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError(
                "policy_version must be an exact major.minor.patch version"
            )
        return value


DEFAULT_SCORING_POLICY = ScoringPolicy()
_TERMINAL_STATUSES = {PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED}


def _finite_output(value: Fraction | int | float) -> float:
    """The only arithmetic rounding boundary is conversion to JSON float fields."""
    try:
        output = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError("Scoring output exceeds the finite float range") from error
    if not isfinite(output):
        raise ValueError("Scoring output exceeds the finite float range")
    return 0.0 if output == 0 else output


def _nonviable_reasons(result: ScenarioResult, policy: ScoringPolicy) -> list[str]:
    reasons = set()
    if result.status != PlanStatus.COMPLETED:
        reasons.add(f"run_status:{result.status.value}")
    if (
        result.metrics.responders_stranded
        > policy.hard_constraints.max_responders_stranded
    ):
        reasons.add("responders_stranded")
    allowed = {code.value for code in policy.hard_constraints.safety_failure_codes}
    # Exact codes only: never parse substrings, messages, or rejection prose.
    explicit = allowed.intersection(result.violations)
    for event in result.timeline:
        code = event.metadata.get("reason_code")
        if (
            event.event_type == EventType.ACTION_FAILED
            and isinstance(code, str)
            and code in allowed
        ):
            explicit.add(code)
    reasons.update(f"hard_safety_failure:{code}" for code in explicit)
    return sorted(reasons)


def score_scenario_result(
    result: ScenarioResult,
    policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
) -> ScenarioResult:
    """Recompute a terminal result on a deep independent copy.

    Failed/cancelled runs retain numerical breakdowns but cannot be recommended.
    Fraction arithmetic uses exact decimal representations of metric/weight inputs;
    only final public float fields round to IEEE-754. No intermediate rounding.
    """
    policy = ScoringPolicy.model_validate(policy.model_dump())
    # Revalidate even model_copy(update=...) callers; ignore stale scoring fields.
    scored = ScenarioResult.model_validate(
        result.model_dump(
            exclude={
                "score",
                "score_breakdown",
                "viable",
                "nonviable_reasons",
            }
        )
    )
    if scored.status not in _TERMINAL_STATUSES:
        raise ValueError("Only terminal scenario results can be scored or ranked")
    total = Fraction(0)
    breakdown = []
    for metric in ScoringWeights.model_fields:
        raw = getattr(scored.metrics, metric)
        weight = getattr(policy.weights, metric)
        contribution = (
            Fraction(0) if raw is None else Fraction(str(raw)) * Fraction(str(weight))
        )
        total += contribution
        output = _finite_output(contribution)
        label = metric.replace("_", " ")
        provenance = f"Policy {policy.policy_id}@{policy.policy_version}."
        if raw is None:
            explanation = (
                f"{label.capitalize()} is unavailable; contributes 0 points. "
                f"{provenance}"
            )
        else:
            effect = (
                "adds"
                if contribution > 0
                else "subtracts"
                if contribution < 0
                else "contributes"
            )
            explanation = (
                f"{label.capitalize()}: {raw} at weight {weight} {effect} "
                f"{abs(output)} points. {provenance}"
            )
        breakdown.append(
            ScoreContribution(
                metric=metric,
                raw_value=None if raw is None else _finite_output(raw),
                weight=weight,
                contribution=output,
                explanation=explanation,
            )
        )
    scored.score = _finite_output(total)
    scored.score_breakdown = breakdown
    scored.nonviable_reasons = _nonviable_reasons(scored, policy)
    scored.viable = not scored.nonviable_reasons
    return scored


def rank_scenario_results(
    results: list[ScenarioResult],
    policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
) -> list[ScenarioResult]:
    """Recompute scores, then apply the documented total ordering."""
    policy = ScoringPolicy.model_validate(policy.model_dump())
    ids = [result.plan_id for result in results]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate plan IDs cannot be ranked")
    scored = [score_scenario_result(result, policy) for result in results]
    return sorted(
        scored,
        key=lambda result: (
            not result.viable,
            -result.score,
            result.metrics.people_isolated,
            result.metrics.responders_stranded,
            result.metrics.critical_calls_unanswered,
            result.metrics.average_response_minutes is None,
            result.metrics.average_response_minutes or 0.0,
            result.plan_id,
        ),
    )


def recommend_plan_id(
    ranked_results: list[ScenarioResult],
    policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
) -> str | None:
    """Defensively re-rank; never trust supplied scores, order, or viability flags."""
    return next(
        (
            result.plan_id
            for result in rank_scenario_results(ranked_results, policy)
            if result.viable
        ),
        None,
    )
