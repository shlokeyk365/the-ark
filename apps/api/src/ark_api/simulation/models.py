"""Validated data contracts, independent of geography and decision providers.

Physical observations are inputs, never computed here. These schemas do not
authorize actions: execution must later pass through a deterministic validator.
Times are absolute integer minutes on the scenario clock, not wall-clock times.
"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

NonemptyString = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)
]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Priority = Annotated[int, Field(strict=True, ge=1, le=5)]
FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class HazardType(StrEnum):
    FLOOD = "flood"
    FIRE = "fire"
    LANDSLIDE = "landslide"
    EARTHQUAKE = "earthquake"
    DEBRIS = "debris"


class RouteStatus(StrEnum):
    OPEN = "open"
    RESTRICTED = "restricted"
    CLOSED = "closed"


class ResponderType(StrEnum):
    BOAT = "boat"
    AMBULANCE = "ambulance"
    RESCUE_TEAM = "rescue_team"
    BUS = "bus"
    POLICE = "police"
    SHELTER = "shelter"
    INCIDENT_COMMAND = "incident_command"


class ResponderStatus(StrEnum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    IN_TRANSIT = "in_transit"
    BUSY = "busy"
    STRANDED = "stranded"
    UNAVAILABLE = "unavailable"


class Capability(StrEnum):
    ROAD_TRAVEL = "road_travel"
    WATER_TRAVEL = "water_travel"
    FOOT_TRAVEL = "foot_travel"
    RESCUE = "rescue"
    EVACUATION = "evacuation"
    MEDICAL = "medical"
    TRAFFIC_CONTROL = "traffic_control"
    SHELTER = "shelter"
    COORDINATION = "coordination"


class RequestStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CommunityStatus(StrEnum):
    SAFE = "safe"
    AT_RISK = "at_risk"
    EVACUATING = "evacuating"
    EVACUATED = "evacuated"
    ISOLATED = "isolated"


class ShelterStatus(StrEnum):
    OPEN = "open"
    FULL = "full"
    CLOSED = "closed"


class ActionType(StrEnum):
    MOVE = "move"
    RESCUE = "rescue"
    EVACUATE = "evacuate"
    TRANSPORT = "transport"
    PROVIDE_MEDICAL_AID = "provide_medical_aid"
    ADMIT_TO_SHELTER = "admit_to_shelter"
    CONTROL_TRAFFIC = "control_traffic"
    COORDINATE = "coordinate"
    WAIT = "wait"


class ActionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(StrEnum):
    ACTION_ACCEPTED = "action_accepted"
    ACTION_REJECTED = "action_rejected"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"
    HAZARD_OBSERVED = "hazard_observed"
    ROUTE_CLOSED = "route_closed"
    REQUEST_COMPLETED = "request_completed"
    COMMUNITY_ISOLATED = "community_isolated"
    RESPONDER_STRANDED = "responder_stranded"
    SHELTER_OVERFLOW = "shelter_overflow"
    SIMULATION_STARTED = "simulation_started"
    SIMULATION_COMPLETED = "simulation_completed"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContractModel(BaseModel):
    # Scalars are strict. Enum strings and JSON arrays remain accepted at the
    # transport boundary so model_validate() also works with decoded JSON.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class LocationNode(ContractModel):
    id: NonemptyString
    name: NonemptyString
    latitude: Annotated[FiniteFloat, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[FiniteFloat, Field(ge=-180, le=180)] | None = None
    is_safe_zone: Annotated[bool, Field(strict=True)] = False


class Hazard(ContractModel):
    id: NonemptyString
    type: HazardType
    affected_node_ids: list[NonemptyString]
    start_minute: NonnegativeInt
    severity: Priority
    source: NonemptyString
    observed: Annotated[bool, Field(strict=True)]


class RouteEdge(ContractModel):
    id: NonemptyString
    origin_node_id: NonemptyString
    destination_node_id: NonemptyString
    base_travel_minutes: PositiveInt
    status: RouteStatus
    closure_minute: NonnegativeInt | None = None
    bidirectional: Annotated[bool, Field(strict=True)] = True
    allowed_capabilities: set[Capability]
    hazard_reason: NonemptyString | None = None

    @model_validator(mode="after")
    def distinct_endpoints(self) -> Self:
        if self.origin_node_id == self.destination_node_id:
            raise ValueError("route origin and destination must be different")
        return self


class Responder(ContractModel):
    id: NonemptyString
    name: NonemptyString
    type: ResponderType
    current_node_id: NonemptyString
    capacity: NonnegativeInt
    speed_multiplier: Annotated[FiniteFloat, Field(gt=0)] = 1.0
    capabilities: Annotated[set[Capability], Field(min_length=1)]
    status: ResponderStatus
    current_assignment_id: NonemptyString | None = None


class RescueRequest(ContractModel):
    id: NonemptyString
    node_id: NonemptyString
    people_count: PositiveInt
    urgency: Priority
    reported_minute: NonnegativeInt
    isolation_minute: NonnegativeInt | None = None
    required_capabilities: set[Capability]
    medical_priority: Annotated[bool, Field(strict=True)] = False
    status: RequestStatus


class Community(ContractModel):
    id: NonemptyString
    name: NonemptyString
    node_id: NonemptyString
    population: PositiveInt
    evacuated_count: NonnegativeInt = 0
    isolation_minute: NonnegativeInt | None = None
    status: CommunityStatus

    @model_validator(mode="after")
    def evacuation_within_population(self) -> Self:
        if self.evacuated_count > self.population:
            raise ValueError("evacuated_count cannot exceed population")
        return self


class Shelter(ContractModel):
    id: NonemptyString
    name: NonemptyString
    node_id: NonemptyString
    capacity: PositiveInt
    occupancy: NonnegativeInt = 0
    status: ShelterStatus

    @model_validator(mode="after")
    def initial_occupancy_within_capacity(self) -> Self:
        if self.occupancy > self.capacity:
            raise ValueError("initial occupancy cannot exceed capacity")
        return self


class WorldState(ContractModel):
    scenario_id: NonemptyString
    current_minute: NonnegativeInt
    nodes: list[LocationNode]
    hazards: list[Hazard] = Field(default_factory=list)
    routes: list[RouteEdge] = Field(default_factory=list)
    responders: list[Responder] = Field(default_factory=list)
    rescue_requests: list[RescueRequest] = Field(default_factory=list)
    communities: list[Community] = Field(default_factory=list)
    shelters: list[Shelter] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator(
        "nodes",
        "hazards",
        "routes",
        "responders",
        "rescue_requests",
        "communities",
        "shelters",
    )
    @classmethod
    def unique_collection_ids(cls, items: list) -> list:
        ids = [item.id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("IDs must be unique within each collection")
        return items

    @model_validator(mode="after")
    def existing_node_references(self) -> Self:
        node_ids = {node.id for node in self.nodes}
        references: list[tuple[str, str]] = []
        for hazard in self.hazards:
            references.extend((hazard.id, node) for node in hazard.affected_node_ids)
        for route in self.routes:
            references.extend(
                [
                    (route.id, route.origin_node_id),
                    (route.id, route.destination_node_id),
                ]
            )
        references.extend((r.id, r.current_node_id) for r in self.responders)
        for collection in (self.rescue_requests, self.communities, self.shelters):
            references.extend((item.id, item.node_id) for item in collection)
        for owner_id, node_id in references:
            if node_id not in node_ids:
                raise ValueError(f"{owner_id!r} references missing node {node_id!r}")
        return self


class PlanAction(ContractModel):
    id: NonemptyString
    responder_id: NonemptyString
    action_type: ActionType
    target_node_id: NonemptyString
    start_minute: NonnegativeInt
    people_count: PositiveInt | None = None
    request_id: NonemptyString | None = None
    community_id: NonemptyString | None = None
    shelter_id: NonemptyString | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ResponsePlan(ContractModel):
    id: NonemptyString
    name: NonemptyString
    description: Annotated[str, Field(strict=True)]
    actions: list[PlanAction]
    objectives: list[NonemptyString] = Field(default_factory=list)
    status: PlanStatus

    @field_validator("actions")
    @classmethod
    def unique_action_ids(cls, actions: list[PlanAction]) -> list[PlanAction]:
        if len({action.id for action in actions}) != len(actions):
            raise ValueError("action IDs must be unique within a plan")
        return actions


class TimelineEvent(ContractModel):
    id: NonemptyString
    minute: NonnegativeInt
    event_type: EventType
    actor_id: NonemptyString | None = None
    target_id: NonemptyString | None = None
    message: NonemptyString
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ScenarioMetrics(ContractModel):
    people_rescued: NonnegativeInt
    people_evacuated: NonnegativeInt
    people_isolated: NonnegativeInt
    responders_stranded: NonnegativeInt
    critical_calls_completed: NonnegativeInt
    critical_calls_unanswered: NonnegativeInt
    average_response_minutes: Annotated[FiniteFloat, Field(ge=0)] | None = None
    shelter_peak_overflow: NonnegativeInt
    rejected_actions: NonnegativeInt


class ScoreContribution(ContractModel):
    metric: NonemptyString
    raw_value: FiniteFloat | None
    weight: FiniteFloat
    contribution: FiniteFloat
    explanation: NonemptyString


class ScenarioResult(ContractModel):
    plan_id: NonemptyString
    status: PlanStatus
    metrics: ScenarioMetrics
    score: FiniteFloat | None = None
    score_breakdown: list[ScoreContribution] = Field(default_factory=list)
    # None means viability has not yet been evaluated by a scoring policy.
    viable: Annotated[bool, Field(strict=True)] | None = None
    nonviable_reasons: list[NonemptyString] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    violations: list[NonemptyString] = Field(default_factory=list)
    simulation_minutes: NonnegativeInt


class FrozenRobustnessModel(ContractModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_default=True, allow_inf_nan=False
    )


ClosureShift = Annotated[int, Field(strict=True, ge=-15, le=15)]
DegradationPercent = Annotated[int, Field(strict=True, ge=0, le=40)]
ReportingDelay = Annotated[int, Field(strict=True, ge=0, le=15)]


class RobustnessConfig(FrozenRobustnessModel):
    enabled: Annotated[bool, Field(strict=True)] = False
    trial_count: Annotated[int, Field(strict=True, ge=1, le=100)] = 20
    seed: Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)] = 42
    route_closure_shift_minutes: tuple[ClosureShift, ClosureShift] = (-15, 15)
    travel_time_increase_percent: tuple[DegradationPercent, DegradationPercent] = (
        0,
        40,
    )
    responder_unavailability_count: Annotated[int, Field(strict=True, ge=0, le=20)] = 0
    shelter_capacity_reduction_percent: tuple[
        DegradationPercent, DegradationPercent
    ] = (0, 40)
    request_reporting_delay_minutes: tuple[ReportingDelay, ReportingDelay] = (0, 15)
    additional_request_count: Annotated[int, Field(strict=True, ge=0, le=3)] = 0

    @field_validator(
        "route_closure_shift_minutes",
        "travel_time_increase_percent",
        "shelter_capacity_reduction_percent",
        "request_reporting_delay_minutes",
    )
    @classmethod
    def ordered_range(cls, value):
        if value[0] > value[1]:
            raise ValueError("Range minimum must not exceed maximum")
        return value


class PerturbationChange(FrozenRobustnessModel):
    entity_id: NonemptyString
    original: NonnegativeInt
    perturbed: NonnegativeInt
    sampled_value: Annotated[int, Field(strict=True)]
    clamped: Annotated[bool, Field(strict=True)] = False
    reason_code: NonemptyString | None = None


class SkippedPerturbation(FrozenRobustnessModel):
    category: NonemptyString
    entity_id: NonemptyString
    reason_code: NonemptyString


class PerturbationAudit(FrozenRobustnessModel):
    trial_index: NonnegativeInt
    trial_id: NonemptyString
    seed: Annotated[int, Field(strict=True)]
    route_changes: tuple[PerturbationChange, ...] = ()
    travel_time_changes: tuple[PerturbationChange, ...] = ()
    unavailable_responder_ids: tuple[NonemptyString, ...] = ()
    shelter_capacity_changes: tuple[PerturbationChange, ...] = ()
    request_reporting_delays: tuple[PerturbationChange, ...] = ()
    synthetic_additional_request_ids: tuple[NonemptyString, ...] = ()
    skipped: tuple[SkippedPerturbation, ...] = ()
    synthetic_provenance: NonemptyString = (
        "Hypothetical disjoint additional cohorts; not historical people."
    )


class RobustnessMetrics(ScenarioMetrics):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class TrialFailureReason(FrozenRobustnessModel):
    action_id: NonemptyString | None = None
    responder_id: NonemptyString | None = None
    reason_code: NonemptyString


class RobustnessTrialOutcome(FrozenRobustnessModel):
    trial_id: NonemptyString
    plan_id: NonemptyString
    status: PlanStatus
    viable: Annotated[bool, Field(strict=True)]
    score: FiniteFloat | None
    score_unavailable_reason: NonemptyString | None = None
    metrics: RobustnessMetrics
    violations: tuple[NonemptyString, ...] = ()
    nonviable_reasons: tuple[NonemptyString, ...] = ()
    failure_reasons: tuple[TrialFailureReason, ...] = ()

    @field_validator("status")
    @classmethod
    def terminal(cls, value):
        if value not in {PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED}:
            raise ValueError("A trial outcome must be terminal")
        return value


class RobustnessTrial(FrozenRobustnessModel):
    audit: PerturbationAudit
    outcomes: tuple[RobustnessTrialOutcome, ...]
    ranking: tuple[NonemptyString, ...]


class ReasonCount(FrozenRobustnessModel):
    reason_code: NonemptyString
    count: NonnegativeInt


class PlanRobustnessSummary(FrozenRobustnessModel):
    plan_id: NonemptyString
    completed_trial_count: NonnegativeInt
    viable_trial_count: NonnegativeInt
    nonviable_trial_count: NonnegativeInt
    viability_rate: Annotated[FiniteFloat, Field(ge=0, le=1)]
    baseline_score: FiniteFloat | None
    minimum_score: FiniteFloat | None
    median_score: FiniteFloat | None
    maximum_score: FiniteFloat | None
    mean_score: FiniteFloat | None
    minimum_rescued: NonnegativeInt
    median_rescued: FiniteFloat
    maximum_rescued: NonnegativeInt
    minimum_evacuated: NonnegativeInt
    median_evacuated: FiniteFloat
    maximum_evacuated: NonnegativeInt
    maximum_isolated_population: NonnegativeInt
    maximum_unanswered_critical_requests: NonnegativeInt
    maximum_stranded_responders: NonnegativeInt
    reason_counts: tuple[ReasonCount, ...]
    best_trial_id: NonemptyString | None
    worst_trial_id: NonemptyString | None
    first_place_trial_count: NonnegativeInt


class RobustnessResult(FrozenRobustnessModel):
    seed: Annotated[int, Field(strict=True)]
    trial_count: PositiveInt
    completed_matched_trials: NonnegativeInt
    baseline_recommended_plan_id: NonemptyString | None
    recommendation_stability_rate: Annotated[FiniteFloat, Field(ge=0, le=1)] | None
    robustness_order: tuple[NonemptyString, ...]
    summaries: tuple[PlanRobustnessSummary, ...]
    trials: tuple[RobustnessTrial, ...]
    disclaimer: NonemptyString = (
        "Synthetic sensitivity tests, not outcome probabilities or AI confidence. "
        "Scenario variations are not historical reconstructions."
    )


class SimulationRequest(ContractModel):
    world_state: WorldState
    plans: list[ResponsePlan] | None = None
    duration_minutes: PositiveInt = 60
    random_seed: Annotated[int, Field(strict=True)] = 42
    robustness: RobustnessConfig | None = None


class SimulationResponse(ContractModel):
    recommended_plan_id: NonemptyString | None = None
    results: list[ScenarioResult]
    disclaimer: NonemptyString
    model_version: NonemptyString
    robustness: RobustnessResult | None = None
