"""Private execution ledgers and the deterministic action admission boundary."""

from dataclasses import dataclass, field
from enum import StrEnum

from ark_api.simulation.models import (
    ActionType,
    Capability,
    CommunityStatus,
    PlanAction,
    RequestStatus,
    ResponderStatus,
    ShelterStatus,
    WorldState,
)
from ark_api.simulation.routing import NoRouteError, RoutePath, shortest_path


class ReasonCode(StrEnum):
    RESPONDER_NOT_FOUND = "responder_not_found"
    TARGET_NOT_FOUND = "target_not_found"
    REQUEST_NOT_FOUND = "request_not_found"
    COMMUNITY_NOT_FOUND = "community_not_found"
    SHELTER_NOT_FOUND = "shelter_not_found"
    BEFORE_CURRENT_TIME = "before_current_time"
    UNSUPPORTED_ACTION = "unsupported_action"
    INVALID_TARGET = "invalid_target"
    RESPONDER_UNAVAILABLE = "responder_unavailable"
    OVERLAPPING_ASSIGNMENT = "overlapping_assignment"
    MISSING_CAPABILITY = "missing_capability"
    CAPACITY_EXCEEDED = "capacity_exceeded"
    PEOPLE_UNAVAILABLE = "people_unavailable"
    REQUEST_NOT_ACTIVE = "request_not_active"
    SHELTER_CLOSED = "shelter_closed"
    SHELTER_CAPACITY_EXCEEDED = "shelter_capacity_exceeded"
    NO_ROUTE = "no_route"


@dataclass
class ResponderState:
    # None while on an edge: a responder never occupies two nodes.
    node_id: str | None
    status: ResponderStatus
    assignment_id: str | None = None
    available_minute: int = 0
    carrying: int = 0
    route_id: str | None = None


@dataclass
class ExecutionState:
    world: WorldState
    responders: dict[str, ResponderState]
    rescued: dict[str, int]
    request_status: dict[str, RequestStatus]
    evacuated: dict[str, int]
    community_status: dict[str, CommunityStatus]
    occupancy: dict[str, int]
    request_reserved: dict[str, int] = field(default_factory=dict)
    community_reserved: dict[str, int] = field(default_factory=dict)
    shelter_reserved: dict[str, int] = field(default_factory=dict)
    first_service: dict[str, int] = field(default_factory=dict)
    closed_route_ids: set[str] = field(default_factory=set)

    @classmethod
    def from_world(cls, world: WorldState) -> "ExecutionState":
        # Never mutate public models, even within the isolated copy.
        snapshot = world.model_copy(deep=True)
        return cls(
            world=snapshot,
            responders={
                r.id: ResponderState(
                    r.current_node_id,
                    r.status,
                    r.current_assignment_id,
                    snapshot.current_minute,
                )
                for r in snapshot.responders
            },
            rescued={
                r.id: r.people_count if r.status == RequestStatus.COMPLETED else 0
                for r in snapshot.rescue_requests
            },
            request_status={r.id: r.status for r in snapshot.rescue_requests},
            evacuated={c.id: c.evacuated_count for c in snapshot.communities},
            community_status={c.id: c.status for c in snapshot.communities},
            occupancy={s.id: s.occupancy for s in snapshot.shelters},
        )


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reason_code: ReasonCode | None = None
    message: str = ""
    outbound: RoutePath | None = None
    delivery: RoutePath | None = None
    people_count: int = 0
    shelter_overflow: int = 0


def validate_action(
    state: ExecutionState, action: PlanAction, minute: int
) -> ValidationResult:
    """Pure validation against current ledgers, including outstanding reservations."""

    def reject(code: ReasonCode, message: str, overflow: int = 0) -> ValidationResult:
        return ValidationResult(False, code, message, shelter_overflow=overflow)

    world = state.world
    responders = {r.id: r for r in world.responders}
    requests = {r.id: r for r in world.rescue_requests}
    communities = {c.id: c for c in world.communities}
    shelters = {s.id: s for s in world.shelters}
    if action.responder_id not in responders:
        return reject(ReasonCode.RESPONDER_NOT_FOUND, "Responder does not exist.")
    if action.target_node_id not in {n.id for n in world.nodes}:
        return reject(ReasonCode.TARGET_NOT_FOUND, "Target node does not exist.")
    for reference, collection, code in (
        (action.request_id, requests, ReasonCode.REQUEST_NOT_FOUND),
        (action.community_id, communities, ReasonCode.COMMUNITY_NOT_FOUND),
        (action.shelter_id, shelters, ReasonCode.SHELTER_NOT_FOUND),
    ):
        if reference is not None and reference not in collection:
            return reject(code, f"Reference {reference!r} does not exist.")
    if action.start_minute < world.current_minute or action.start_minute < minute:
        return reject(
            ReasonCode.BEFORE_CURRENT_TIME, "Action starts before current time."
        )
    if action.action_type not in {
        ActionType.MOVE,
        ActionType.RESCUE,
        ActionType.EVACUATE,
    }:
        return reject(ReasonCode.UNSUPPORTED_ACTION, "Action type is not implemented.")
    responder = responders[action.responder_id]
    runtime = state.responders[action.responder_id]
    if runtime.assignment_id is not None or runtime.available_minute > minute:
        return reject(
            ReasonCode.OVERLAPPING_ASSIGNMENT, "Responder already has an assignment."
        )
    if runtime.status != ResponderStatus.AVAILABLE or runtime.node_id is None:
        return reject(ReasonCode.RESPONDER_UNAVAILABLE, "Responder is unavailable.")
    required = set()
    count = action.people_count or 0
    if action.action_type == ActionType.MOVE:
        if any(
            x is not None
            for x in (
                action.request_id,
                action.community_id,
                action.shelter_id,
                action.people_count,
            )
        ):
            return reject(ReasonCode.INVALID_TARGET, "MOVE accepts only a target node.")
    elif action.action_type == ActionType.RESCUE:
        if (
            action.request_id is None
            or action.community_id is not None
            or action.shelter_id is not None
            or not count
        ):
            return reject(
                ReasonCode.INVALID_TARGET,
                "RESCUE requires a request and people_count only.",
            )
        request = requests[action.request_id]
        if action.target_node_id != request.node_id:
            return reject(ReasonCode.INVALID_TARGET, "Target must be the request node.")
        if (
            request.reported_minute > minute
            or state.request_status[request.id] == RequestStatus.CANCELLED
        ):
            return reject(
                ReasonCode.REQUEST_NOT_ACTIVE,
                "Request is not active yet or is cancelled.",
            )
        required = {Capability.RESCUE} | request.required_capabilities
        if request.medical_priority:
            required.add(Capability.MEDICAL)
        remaining = (
            request.people_count
            - state.rescued[request.id]
            - state.request_reserved.get(request.id, 0)
        )
    else:
        if (
            action.community_id is None
            or action.shelter_id is None
            or action.request_id is not None
            or not count
        ):
            return reject(
                ReasonCode.INVALID_TARGET,
                "EVACUATE requires community, shelter, and people_count.",
            )
        community = communities[action.community_id]
        if action.target_node_id != community.node_id:
            return reject(
                ReasonCode.INVALID_TARGET, "Target must be the community node."
            )
        required = {Capability.EVACUATION}
        remaining = (
            community.population
            - state.evacuated[community.id]
            - state.community_reserved.get(community.id, 0)
        )
    if not required <= responder.capabilities:
        return reject(
            ReasonCode.MISSING_CAPABILITY, "Responder lacks required capabilities."
        )
    if count > responder.capacity:
        return reject(
            ReasonCode.CAPACITY_EXCEEDED, "people_count exceeds responder capacity."
        )
    if action.action_type != ActionType.MOVE and count > remaining:
        return reject(
            ReasonCode.PEOPLE_UNAVAILABLE,
            "People are already served/reserved or count exceeds remaining population.",
        )
    if action.action_type == ActionType.EVACUATE:
        shelter = shelters[action.shelter_id]
        if shelter.status == ShelterStatus.CLOSED:
            return reject(ReasonCode.SHELTER_CLOSED, "Shelter is closed.")
        free = (
            shelter.capacity
            - state.occupancy[shelter.id]
            - state.shelter_reserved.get(shelter.id, 0)
        )
        overflow = max(0, count - free)
        if overflow or shelter.status == ShelterStatus.FULL:
            return reject(
                ReasonCode.SHELTER_CAPACITY_EXCEEDED,
                "Shelter lacks available capacity.",
                overflow,
            )
    try:
        outbound = shortest_path(
            world,
            runtime.node_id,
            action.target_node_id,
            minute,
            responder.capabilities,
            responder.speed_multiplier,
        )
        delivery = None
        if action.action_type == ActionType.EVACUATE:
            delivery = shortest_path(
                world,
                action.target_node_id,
                shelter.node_id,
                outbound.arrival_minute,
                responder.capabilities,
                responder.speed_multiplier,
            )
    except NoRouteError as error:
        return reject(ReasonCode.NO_ROUTE, str(error))
    return ValidationResult(
        True, outbound=outbound, delivery=delivery, people_count=count
    )
