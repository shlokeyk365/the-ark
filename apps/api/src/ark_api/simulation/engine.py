"""Isolated, deterministic minute-by-minute response-plan execution."""

from heapq import heappop, heappush

from ark_api.simulation.models import (
    ActionType,
    CommunityStatus,
    EventType,
    PlanAction,
    PlanStatus,
    RequestStatus,
    ResponderStatus,
    ResponsePlan,
    ScenarioMetrics,
    ScenarioResult,
    TimelineEvent,
    WorldState,
)
from ark_api.simulation.routing import (
    CIVILIAN_CAPABILITIES,
    RoutePath,
    can_reach_safety,
)
from ark_api.simulation.validation import (
    ExecutionState,
    ValidationResult,
    validate_action,
)


def simulate_plan(
    world_state: WorldState,
    plan: ResponsePlan,
    duration_minutes: int = 60,
) -> ScenarioResult:
    """Execute through start + duration inclusive; no new external effects.

    Each minute processes closures, arrivals, then actions in responder/action-ID
    order. Zero-distance transitions complete immediately after their dispatch.
    Reaching the horizon completes the run, even with pending/unfinished actions.
    Rejected actions do not fail the simulation. Counts describe this run's work.
    """
    if type(duration_minutes) is not int or duration_minutes <= 0:
        raise ValueError("duration_minutes must be a positive integer")
    state = ExecutionState.from_world(world_state)
    world = state.world
    plan = plan.model_copy(deep=True)
    start = world.current_minute
    end = start + duration_minutes
    timeline: list[TimelineEvent] = []
    violations: list[str] = []
    # Heap keys guarantee stable transition order, independent of input order.
    transitions: list[tuple[int, str, str, int, int]] = []
    active: dict[str, tuple[PlanAction, ValidationResult]] = {}
    initial_rescued = sum(state.rescued.values())
    initial_evacuated = sum(state.evacuated.values())
    peak_overflow = 0
    rejected = 0

    def emit(minute, event_type, message, action=None, target=None, **metadata):
        timeline.append(
            TimelineEvent(
                id=f"event-{len(timeline):06d}",
                minute=minute,
                event_type=event_type,
                actor_id=action.responder_id if action else None,
                target_id=target
                if target is not None
                else (action.target_node_id if action else None),
                message=message,
                metadata={**({"action_id": action.id} if action else {}), **metadata},
            )
        )

    def begin_leg(action: PlanAction, path: RoutePath, leg: int):
        runtime = state.responders[action.responder_id]
        if path.route_ids:
            runtime.node_id = None
            runtime.route_id = path.route_ids[0]
            runtime.status = ResponderStatus.IN_TRANSIT
            for index, arrival in enumerate(path.arrival_minutes):
                heappush(
                    transitions, (arrival, action.responder_id, action.id, leg, index)
                )
        else:
            heappush(
                transitions,
                (path.arrival_minute, action.responder_id, action.id, leg, -1),
            )

    def finish(action: PlanAction, minute: int):
        runtime = state.responders[action.responder_id]
        runtime.status = ResponderStatus.AVAILABLE
        runtime.assignment_id = None
        runtime.available_minute = minute
        runtime.route_id = None
        emit(
            minute,
            EventType.ACTION_COMPLETED,
            "Action completed.",
            action,
            target=runtime.node_id,
            phase="completed",
            people_count=active[action.id][1].people_count,
        )
        del active[action.id]

    def process_arrivals(minute: int):
        while transitions and transitions[0][0] == minute:
            _, responder_id, action_id, leg, index = heappop(transitions)
            action, accepted = active[action_id]
            path = accepted.outbound if leg == 0 else accepted.delivery
            runtime = state.responders[responder_id]
            node = path.node_ids[index + 1] if index >= 0 else path.node_ids[0]
            runtime.node_id = node
            runtime.route_id = None
            emit(
                minute,
                EventType.ACTION_STARTED,
                "Responder arrived at node.",
                action,
                target=node,
                phase="arrival",
                route_id=path.route_ids[index] if index >= 0 else None,
            )
            if index >= 0 and index < len(path.route_ids) - 1:
                runtime.node_id = None
                runtime.route_id = path.route_ids[index + 1]
                continue
            count = accepted.people_count
            if action.action_type == ActionType.MOVE:
                finish(action, minute)
            elif action.action_type == ActionType.RESCUE:
                request_id = action.request_id
                state.rescued[request_id] += count
                state.request_reserved[request_id] -= count
                state.first_service.setdefault(request_id, minute)
                request = next(r for r in world.rescue_requests if r.id == request_id)
                completed = state.rescued[request_id] == request.people_count
                state.request_status[request_id] = (
                    RequestStatus.COMPLETED if completed else RequestStatus.IN_PROGRESS
                )
                emit(
                    minute,
                    EventType.REQUEST_COMPLETED
                    if completed
                    else EventType.ACTION_STARTED,
                    "Rescue service completed."
                    if completed
                    else "Partial rescue service completed.",
                    action,
                    target=request_id,
                    phase="rescue_service",
                    people_count=count,
                    remaining_people=request.people_count - state.rescued[request_id],
                )
                finish(action, minute)
            elif leg == 0:
                runtime.carrying = count
                state.community_status[action.community_id] = CommunityStatus.EVACUATING
                emit(
                    minute,
                    EventType.ACTION_STARTED,
                    "Community members picked up.",
                    action,
                    target=action.community_id,
                    phase="pickup",
                    people_count=count,
                )
                begin_leg(action, accepted.delivery, 1)
            else:
                state.evacuated[action.community_id] += count
                state.community_reserved[action.community_id] -= count
                state.occupancy[action.shelter_id] += count
                state.shelter_reserved[action.shelter_id] -= count
                runtime.carrying = 0
                community = next(
                    c for c in world.communities if c.id == action.community_id
                )
                if state.evacuated[community.id] == community.population:
                    state.community_status[community.id] = CommunityStatus.EVACUATED
                emit(
                    minute,
                    EventType.ACTION_STARTED,
                    "People admitted at shelter.",
                    action,
                    target=action.shelter_id,
                    phase="shelter_arrival",
                    people_count=count,
                    occupancy=state.occupancy[action.shelter_id],
                )
                finish(action, minute)

    emit(start, EventType.SIMULATION_STARTED, "Simulation started.", plan_id=plan.id)
    actions_by_minute: dict[int, list[PlanAction]] = {}
    for action in sorted(
        plan.actions, key=lambda a: (a.start_minute, a.responder_id, a.id)
    ):
        actions_by_minute.setdefault(max(start, action.start_minute), []).append(action)
    for minute in range(start, end + 1):
        for route in sorted(world.routes, key=lambda route: route.id):
            if route.id in state.closed_route_ids:
                continue
            if route.status == "closed" or (
                route.closure_minute is not None and route.closure_minute <= minute
            ):
                state.closed_route_ids.add(route.id)
                if route.status != "closed":
                    emit(
                        minute,
                        EventType.ROUTE_CLOSED,
                        "Authoritative route closure applied.",
                        target=route.id,
                        closure_minute=route.closure_minute,
                    )
        process_arrivals(minute)
        for action in actions_by_minute.get(minute, []):
            accepted = validate_action(state, action, minute)
            if not accepted.accepted:
                rejected += 1
                peak_overflow = max(peak_overflow, accepted.shelter_overflow)
                code = accepted.reason_code.value
                violations.append(f"{action.id}: {code}: {accepted.message}")
                emit(
                    minute,
                    EventType.ACTION_REJECTED,
                    accepted.message,
                    action,
                    reason_code=code,
                    shelter_overflow=accepted.shelter_overflow,
                )
                if accepted.shelter_overflow:
                    emit(
                        minute,
                        EventType.SHELTER_OVERFLOW,
                        "Attempted admission exceeds capacity.",
                        action,
                        target=action.shelter_id,
                        overflow=accepted.shelter_overflow,
                    )
                continue
            runtime = state.responders[action.responder_id]
            runtime.assignment_id = action.id
            runtime.available_minute = (
                accepted.delivery or accepted.outbound
            ).arrival_minute
            if action.action_type == ActionType.RESCUE:
                state.request_reserved[action.request_id] = (
                    state.request_reserved.get(action.request_id, 0)
                    + accepted.people_count
                )
                state.request_status[action.request_id] = RequestStatus.IN_PROGRESS
            elif action.action_type == ActionType.EVACUATE:
                state.community_reserved[action.community_id] = (
                    state.community_reserved.get(action.community_id, 0)
                    + accepted.people_count
                )
                state.shelter_reserved[action.shelter_id] = (
                    state.shelter_reserved.get(action.shelter_id, 0)
                    + accepted.people_count
                )
            active[action.id] = (action, accepted)
            emit(
                minute,
                EventType.ACTION_ACCEPTED,
                "Action validated and resources reserved.",
                action,
                people_count=accepted.people_count,
            )
            emit(
                minute,
                EventType.ACTION_STARTED,
                "Responder dispatched.",
                action,
                phase="dispatch",
                origin_node_id=runtime.node_id,
                route_ids=list(accepted.outbound.route_ids),
                delivery_route_ids=list(accepted.delivery.route_ids)
                if accepted.delivery
                else [],
                available_minute=runtime.available_minute,
            )
            begin_leg(action, accepted.outbound, 0)
            process_arrivals(minute)

    isolated = 0
    for request in sorted(world.rescue_requests, key=lambda r: r.id):
        if request.status == RequestStatus.CANCELLED or request.reported_minute > end:
            continue
        if not can_reach_safety(world, request.node_id, end, CIVILIAN_CAPABILITIES):
            isolated += request.people_count - state.rescued[request.id]
    for community in sorted(world.communities, key=lambda c: c.id):
        onboard = sum(
            state.responders[a.responder_id].carrying
            for a, _ in active.values()
            if a.community_id == community.id
        )
        remaining = community.population - state.evacuated[community.id] - onboard
        if remaining and not can_reach_safety(
            world, community.node_id, end, CIVILIAN_CAPABILITIES
        ):
            isolated += remaining
            state.community_status[community.id] = CommunityStatus.ISOLATED
            emit(
                end,
                EventType.COMMUNITY_ISOLATED,
                "Remaining community members cannot reach safety.",
                target=community.id,
                people_count=remaining,
            )
    stranded = 0
    for responder in sorted(world.responders, key=lambda r: r.id):
        runtime = state.responders[responder.id]
        if runtime.node_id is not None and not can_reach_safety(
            world,
            runtime.node_id,
            end,
            responder.capabilities,
            responder.speed_multiplier,
        ):
            stranded += 1
            runtime.status = ResponderStatus.STRANDED
            emit(
                end,
                EventType.RESPONDER_STRANDED,
                "Responder node has no usable route to safety.",
                target=responder.id,
                node_id=runtime.node_id,
            )
    critical = [
        r
        for r in world.rescue_requests
        if r.urgency >= 4
        and r.status != RequestStatus.CANCELLED
        and r.reported_minute <= end
    ]
    completed = sum(state.rescued[r.id] == r.people_count for r in critical)
    response_times = [
        state.first_service[r.id] - r.reported_minute
        for r in sorted(world.rescue_requests, key=lambda r: r.id)
        if r.id in state.first_service
    ]
    metrics = ScenarioMetrics(
        people_rescued=sum(state.rescued.values()) - initial_rescued,
        people_evacuated=sum(state.evacuated.values()) - initial_evacuated,
        people_isolated=isolated,
        responders_stranded=stranded,
        critical_calls_completed=completed,
        critical_calls_unanswered=len(critical) - completed,
        average_response_minutes=sum(response_times) / len(response_times)
        if response_times
        else None,
        shelter_peak_overflow=peak_overflow,
        rejected_actions=rejected,
    )
    # These are horizon observations, not action completions or failures.
    for action, _ in sorted(
        active.values(), key=lambda item: (item[0].responder_id, item[0].id)
    ):
        emit(
            end,
            EventType.SIMULATION_COMPLETED,
            "Action incomplete at the end of the simulation horizon.",
            action,
            phase="incomplete_at_horizon",
            action_status="in_progress",
        )
    # Auditable final ledger, including in-transit people who are not yet evacuated.
    emit(
        end,
        EventType.SIMULATION_COMPLETED,
        "Simulation horizon reached.",
        pending_action_ids=[
            a.id
            for a in sorted(
                plan.actions, key=lambda a: (a.start_minute, a.responder_id, a.id)
            )
            if a.start_minute > end
        ],
        closed_route_ids=sorted(state.closed_route_ids),
        responders={
            key: {
                "node_id": value.node_id,
                "route_id": value.route_id,
                "carrying": value.carrying,
                "assignment_id": value.assignment_id,
                "status": value.status.value,
                "available_minute": value.available_minute,
            }
            for key, value in sorted(state.responders.items())
        },
        requests={
            key: {"rescued": value, "status": state.request_status[key].value}
            for key, value in sorted(state.rescued.items())
        },
        communities={
            key: {"evacuated_count": value, "status": state.community_status[key].value}
            for key, value in sorted(state.evacuated.items())
        },
        shelters={
            key: {"occupancy": value, "reserved": state.shelter_reserved.get(key, 0)}
            for key, value in sorted(state.occupancy.items())
        },
    )
    return ScenarioResult(
        plan_id=plan.id,
        status=PlanStatus.COMPLETED,
        metrics=metrics,
        timeline=timeline,
        violations=violations,
        simulation_minutes=duration_minutes,
    )
