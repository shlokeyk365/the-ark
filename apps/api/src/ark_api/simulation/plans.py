"""Auditable deterministic proposal policies, not a dispatch optimizer."""

from dataclasses import dataclass
from urllib.parse import quote

from ark_api.simulation.models import (
    ActionType,
    Community,
    PlanAction,
    PlanStatus,
    RescueRequest,
    ResponderStatus,
    ResponsePlan,
    WorldState,
)
from ark_api.simulation.validation import (
    ExecutionState,
    ValidationResult,
    validate_action,
)


@dataclass(frozen=True)
class _Candidate:
    action: PlanAction
    validation: ValidationResult
    order: tuple


class _Planner:
    def __init__(self, world: WorldState, strategy: str):
        self.state = ExecutionState.from_world(world)
        self.strategy = strategy
        self.actions: list[PlanAction] = []
        self.responders = {r.id: r for r in self.state.world.responders}
        self.available = {
            r.id
            for r in self.state.world.responders
            if r.status == ResponderStatus.AVAILABLE
            and r.current_assignment_id is None
            and r.capacity > 0
        }
        self.requests = sorted(
            self.state.world.rescue_requests,
            key=lambda r: (
                -r.urgency,
                r.isolation_minute is None,
                r.isolation_minute or 0,
                r.reported_minute,
                r.id,
            ),
        )
        self.communities = sorted(
            self.state.world.communities,
            key=lambda c: (
                c.isolation_minute is None,
                c.isolation_minute or 0,
                -(c.population - c.evacuated_count),
                c.id,
            ),
        )

    def candidates(
        self,
        target: RescueRequest | Community,
        pool: set[str],
    ) -> list[_Candidate]:
        """Validator supplies feasibility AND existing routing's projected times."""
        rescue = isinstance(target, RescueRequest)
        state = self.state
        remaining = (
            target.people_count
            - state.rescued[target.id]
            - state.request_reserved.get(target.id, 0)
            if rescue
            else target.population
            - state.evacuated[target.id]
            - state.community_reserved.get(target.id, 0)
        )
        if remaining <= 0:
            return []
        options = []
        shelters = (
            [None] if rescue else sorted(state.world.shelters, key=lambda s: s.id)
        )
        for responder_id in sorted(pool & self.available):
            responder = self.responders[responder_id]
            for shelter in shelters:
                count = min(responder.capacity, remaining)
                if shelter is not None:
                    free = (
                        shelter.capacity
                        - state.occupancy[shelter.id]
                        - state.shelter_reserved.get(shelter.id, 0)
                    )
                    count = min(count, free)
                if count <= 0:
                    continue
                # Percent encoding keeps separators unambiguous for arbitrary IDs.
                action_id = ":".join(
                    quote(part, safe="")
                    for part in (
                        self.strategy,
                        responder_id,
                        target.id,
                        str(len(self.actions) + 1),
                    )
                )
                action = PlanAction(
                    id=action_id,
                    responder_id=responder_id,
                    action_type=ActionType.RESCUE if rescue else ActionType.EVACUATE,
                    target_node_id=target.node_id,
                    start_minute=state.world.current_minute,
                    people_count=count,
                    request_id=target.id if rescue else None,
                    community_id=None if rescue else target.id,
                    shelter_id=shelter.id if shelter is not None else None,
                )
                result = validate_action(state, action, state.world.current_minute)
                if not result.accepted:
                    continue
                if rescue:
                    order = (result.outbound.arrival_minute, responder_id)
                else:
                    # Prefer serving the most people in one trip; then earliest
                    # delivery/pickup and stable responder/shelter IDs.
                    order = (
                        -count,
                        result.delivery.arrival_minute,
                        result.outbound.arrival_minute,
                        responder_id,
                        shelter.id,
                    )
                options.append(_Candidate(action, result, order))
        return options

    def reserve(self, candidate: _Candidate) -> None:
        action = candidate.action
        count = action.people_count
        self.actions.append(action)
        self.available.remove(action.responder_id)
        runtime = self.state.responders[action.responder_id]
        runtime.assignment_id = action.id
        runtime.available_minute = (
            candidate.validation.delivery or candidate.validation.outbound
        ).arrival_minute
        if action.action_type == ActionType.RESCUE:
            ledger = self.state.request_reserved
            ledger[action.request_id] = ledger.get(action.request_id, 0) + count
        else:
            ledger = self.state.community_reserved
            ledger[action.community_id] = ledger.get(action.community_id, 0) + count
            ledger = self.state.shelter_reserved
            ledger[action.shelter_id] = ledger.get(action.shelter_id, 0) + count

    def assign(self, rescue: bool, pool: set[str], critical_only: bool = False) -> None:
        targets = self.requests if rescue else self.communities
        for target in targets:
            if rescue and critical_only and target.urgency < 4:
                continue
            while options := self.candidates(target, pool):
                self.reserve(min(options, key=lambda candidate: candidate.order))

    def balanced(self) -> None:
        # Preserve specialists before dividing flexible responders by stable ID.
        rescue_eligible = {
            r
            for r in self.available
            if any(self.candidates(t, {r}) for t in self.requests)
        }
        evacuation_eligible = {
            r
            for r in self.available
            if any(self.candidates(t, {r}) for t in self.communities)
        }
        rescue_only = rescue_eligible - evacuation_eligible
        evacuation_only = evacuation_eligible - rescue_eligible
        flexible = sorted(rescue_eligible & evacuation_eligible)
        useful_count = len(rescue_eligible | evacuation_eligible)
        rescue_quota = (useful_count + 1) // 2
        flexible_rescue_count = max(0, rescue_quota - len(rescue_only))
        rescue_pool = rescue_only | set(flexible[:flexible_rescue_count])
        evacuation_pool = evacuation_only | set(flexible[flexible_rescue_count:])
        self.assign(True, rescue_pool)
        self.assign(False, evacuation_pool)
        # Reservations may exhaust a category's work. Reuse idle responders
        # wherever feasible, with rescue first, without assigning anyone twice.
        self.assign(True, set(self.available))
        self.assign(False, set(self.available))


def generate_candidate_plans(world_state: WorldState) -> list[ResponsePlan]:
    """Return three independent READY plans without running any simulation."""
    strategies = (
        (
            "immediate-rescue",
            "Immediate Rescue",
            "Prioritize currently reported rescue calls.",
            ["Serve highest-urgency requests first", "Use nearest feasible responders"],
        ),
        (
            "balanced-response",
            "Balanced Response",
            "Share responders between rescue and evacuation.",
            [
                "Balance rescue and preventive evacuation",
                "Reallocate unsuitable or idle responders",
            ],
        ),
        (
            "preventive-evacuation",
            "Preventive Evacuation",
            "Evacuate communities before access closes.",
            [
                "Prioritize communities approaching isolation",
                "Use spare responders for critical calls",
            ],
        ),
    )
    plans = []
    for strategy, name, description, objectives in strategies:
        planner = _Planner(world_state, strategy)
        if strategy == "immediate-rescue":
            planner.assign(True, set(planner.available))
        elif strategy == "balanced-response":
            planner.balanced()
        else:
            planner.assign(False, set(planner.available))
            planner.assign(True, set(planner.available), critical_only=True)
        plans.append(
            ResponsePlan(
                id=strategy,
                name=name,
                description=description,
                objectives=objectives,
                status=PlanStatus.READY,
                actions=sorted(
                    planner.actions,
                    key=lambda a: (a.start_minute, a.responder_id, a.id),
                ),
            )
        )
    return plans
