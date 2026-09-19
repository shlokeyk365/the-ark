from collections import Counter

import pytest

from ark_api.simulation.engine import simulate_plan
from ark_api.simulation.models import (
    ActionType,
    Capability,
    RequestStatus,
    ResponderStatus,
    RouteStatus,
    ShelterStatus,
)
from ark_api.simulation.plans import generate_candidate_plans
from ark_api.simulation.validation import ExecutionState, validate_action

IDS = ["immediate-rescue", "balanced-response", "preventive-evacuation"]


@pytest.fixture
def mixed_world(simulation_world):
    world = simulation_world
    original = world.responders[0]
    world.responders = []
    for i in range(4):
        responder = original.model_copy(deep=True)
        responder.id = f"responder-{i}"
        responder.capacity = 5
        world.responders.append(responder)
    world.rescue_requests[0].people_count = 20
    world.rescue_requests[0].required_capabilities = set()
    return world


def plan(world, strategy=0):
    return generate_candidate_plans(world)[strategy]


def test_three_stable_ready_plans(mixed_world):
    plans = generate_candidate_plans(mixed_world)
    assert [p.id for p in plans] == IDS
    assert all(
        p.status == "ready" and p.name and p.description and p.objectives for p in plans
    )
    assert all(type(p).model_validate_json(p.model_dump_json()) == p for p in plans)


def test_determinism_immutability_and_independent_plans(mixed_world):
    original = mixed_world.model_dump_json()
    first = generate_candidate_plans(mixed_world)
    second = generate_candidate_plans(mixed_world)
    assert [p.model_dump_json() for p in first] == [p.model_dump_json() for p in second]
    assert mixed_world.model_dump_json() == original
    first[0].actions[0].people_count = 999
    assert second[0].actions[0].people_count == 5
    assert first[1].actions[0].people_count == 5


def test_strategies_differ(mixed_world):
    counts = [
        Counter(a.action_type for a in p.actions)
        for p in generate_candidate_plans(mixed_world)
    ]
    assert counts == [
        {ActionType.RESCUE: 4},
        {ActionType.RESCUE: 2, ActionType.EVACUATE: 2},
        {ActionType.EVACUATE: 4},
    ]


@pytest.mark.parametrize(
    "first,second,expected",
    [
        ({"urgency": 3}, {"urgency": 5}, "second"),
        ({"isolation_minute": None}, {"isolation_minute": 50}, "second"),
        ({"isolation_minute": 40}, {"isolation_minute": 30}, "second"),
        ({"reported_minute": 9}, {"reported_minute": 1}, "second"),
        ({}, {}, "call-1"),
    ],
)
def test_request_priority(simulation_world, first, second, expected):
    request = simulation_world.rescue_requests[0]
    other = request.model_copy(deep=True)
    other.id = "second"
    for key, value in first.items():
        setattr(request, key, value)
    for key, value in second.items():
        setattr(other, key, value)
    simulation_world.rescue_requests.append(other)
    assert plan(simulation_world).actions[0].request_id == expected


def test_nearest_feasible_capable_responder(mixed_world):
    mixed_world.rescue_requests[0].people_count = 5
    mixed_world.responders[0].current_node_id = "riverside"
    mixed_world.responders[0].capabilities.remove(Capability.RESCUE)
    mixed_world.responders[2].current_node_id = "riverside"
    actions = plan(mixed_world).actions
    assert len(actions) == 1
    assert actions[0].responder_id == "responder-2"


def test_nearest_uses_speed(mixed_world):
    mixed_world.rescue_requests[0].people_count = 5
    mixed_world.responders[3].speed_multiplier = 2.0
    assert plan(mixed_world).actions[0].responder_id == "responder-3"


@pytest.mark.parametrize(
    "people,counts", [(3, [3]), (5, [5]), (7, [5, 2]), (25, [5, 5, 5, 5])]
)
def test_split_request_only_as_needed(mixed_world, people, counts):
    mixed_world.rescue_requests[0].people_count = people
    assert [a.people_count for a in plan(mixed_world).actions] == counts


def test_balanced_odd_extra_goes_to_rescue(mixed_world):
    mixed_world.responders.pop()
    counts = Counter(a.action_type for a in plan(mixed_world, 1).actions)
    assert counts == {ActionType.RESCUE: 2, ActionType.EVACUATE: 1}


def test_balanced_preserves_specialists(mixed_world):
    mixed_world.responders = mixed_world.responders[:2]
    # The low-ID flexible responder must be preserved for evacuation.
    mixed_world.responders[1].capabilities.remove(Capability.EVACUATION)
    actions = {a.responder_id: a.action_type for a in plan(mixed_world, 1).actions}
    assert actions == {
        "responder-0": ActionType.EVACUATE,
        "responder-1": ActionType.RESCUE,
    }


@pytest.mark.parametrize(
    "capability,action_type",
    [
        (Capability.RESCUE, ActionType.EVACUATE),
        (Capability.EVACUATION, ActionType.RESCUE),
    ],
)
def test_balanced_reallocates_incompatible_responders(
    mixed_world, capability, action_type
):
    for responder in mixed_world.responders:
        responder.capabilities.remove(capability)
    actions = plan(mixed_world, 1).actions
    assert len(actions) == 4
    assert all(a.action_type == action_type for a in actions)


def test_balanced_reuses_responders_after_work_exhausted(mixed_world):
    mixed_world.rescue_requests[0].people_count = 2
    counts = Counter(a.action_type for a in plan(mixed_world, 1).actions)
    assert counts == {ActionType.RESCUE: 1, ActionType.EVACUATE: 3}


@pytest.mark.parametrize(
    "first,second,expected",
    [
        ({"isolation_minute": 40}, {"isolation_minute": 30}, "second"),
        ({"isolation_minute": None}, {"isolation_minute": 30}, "second"),
        ({"population": 10}, {"population": 20}, "second"),
        ({"evacuated_count": 15}, {"evacuated_count": 0}, "second"),
        ({}, {}, "community-1"),
    ],
)
def test_community_priority(simulation_world, first, second, expected):
    community = simulation_world.communities[0]
    other = community.model_copy(deep=True)
    other.id = "second"
    for key, value in first.items():
        setattr(community, key, value)
    for key, value in second.items():
        setattr(other, key, value)
    simulation_world.communities.append(other)
    assert plan(simulation_world, 2).actions[0].community_id == expected


def test_evacuation_reserves_shelter_capacity(mixed_world):
    mixed_world.rescue_requests = []
    mixed_world.shelters[0].occupancy = 33
    actions = plan(mixed_world, 2).actions
    assert [a.people_count for a in actions] == [5, 2]
    assert sum(a.people_count for a in actions) == 7


def test_evacuation_prefers_one_sufficient_responder(mixed_world):
    mixed_world.responders[3].capacity = 20
    actions = [
        a for a in plan(mixed_world, 2).actions if a.action_type == ActionType.EVACUATE
    ]
    assert len(actions) == 1
    assert actions[0].responder_id == "responder-3"
    assert actions[0].people_count == 20


def test_selects_operational_shelter(simulation_world):
    original = simulation_world.shelters[0]
    original.status = ShelterStatus.CLOSED
    alternative = original.model_copy(deep=True)
    alternative.id = "open-shelter"
    alternative.status = ShelterStatus.OPEN
    simulation_world.shelters.append(alternative)
    assert plan(simulation_world, 2).actions[0].shelter_id == "open-shelter"


@pytest.mark.parametrize(
    "closure,expected_rescue,expected_evacuation",
    [
        (14, 0, 0),
        (15, 0, 0),
        (16, 1, 0),
        (20, 1, 0),
        (21, 1, 1),
    ],
)
def test_closures_and_exact_arrival_boundary(
    simulation_world, closure, expected_rescue, expected_evacuation
):
    simulation_world.routes[0].closure_minute = closure
    assert len(plan(simulation_world).actions) == expected_rescue
    evacuation = [
        a
        for a in plan(simulation_world, 2).actions
        if a.action_type == ActionType.EVACUATE
    ]
    assert len(evacuation) == expected_evacuation


@pytest.mark.parametrize("status", [RequestStatus.COMPLETED, RequestStatus.CANCELLED])
def test_inactive_requests_skipped(simulation_world, status):
    simulation_world.rescue_requests[0].status = status
    assert plan(simulation_world).actions == []


def test_unreported_request_skipped(simulation_world):
    simulation_world.rescue_requests[0].reported_minute = 11
    assert plan(simulation_world).actions == []


def test_fully_evacuated_community_skipped(simulation_world):
    simulation_world.communities[0].evacuated_count = 20
    assert all(
        a.action_type != ActionType.EVACUATE for a in plan(simulation_world, 2).actions
    )


@pytest.mark.parametrize(
    "status,occupancy",
    [(ShelterStatus.CLOSED, 0), (ShelterStatus.FULL, 40), (ShelterStatus.OPEN, 40)],
)
def test_closed_and_full_shelters_skipped(simulation_world, status, occupancy):
    simulation_world.shelters[0].status = status
    simulation_world.shelters[0].occupancy = occupancy
    assert all(
        a.action_type != ActionType.EVACUATE for a in plan(simulation_world, 2).actions
    )


@pytest.mark.parametrize("empty", ["responders", "work", "routes", "capabilities"])
def test_three_empty_plans(mixed_world, empty):
    if empty == "responders":
        mixed_world.responders = []
    elif empty == "work":
        mixed_world.rescue_requests = []
        mixed_world.communities = []
    elif empty == "routes":
        mixed_world.routes[0].status = RouteStatus.CLOSED
    else:
        for responder in mixed_world.responders:
            responder.capabilities = {Capability.ROAD_TRAVEL}
    plans = generate_candidate_plans(mixed_world)
    assert [p.id for p in plans] == IDS
    assert all(p.actions == [] for p in plans)


@pytest.mark.parametrize("collection", ["shelters", "communities", "rescue_requests"])
def test_missing_work_collection(mixed_world, collection):
    setattr(mixed_world, collection, [])
    assert len(generate_candidate_plans(mixed_world)) == 3


def test_preventive_fallback_only_critical(simulation_world):
    simulation_world.communities = []
    assert plan(simulation_world, 2).actions[0].action_type == ActionType.RESCUE
    simulation_world.rescue_requests[0].urgency = 3
    assert plan(simulation_world, 2).actions == []


def test_unavailable_assigned_and_zero_capacity_skipped(mixed_world):
    mixed_world.responders[0].status = ResponderStatus.BUSY
    mixed_world.responders[1].current_assignment_id = "existing"
    mixed_world.responders[2].capacity = 0
    for candidate in generate_candidate_plans(mixed_world):
        assert [a.responder_id for a in candidate.actions] == ["responder-3"]


def test_equal_costs_priorities_and_collection_permutations(mixed_world):
    other = mixed_world.rescue_requests[0].model_copy(deep=True)
    other.id = "z-request"
    mixed_world.rescue_requests[0].people_count = 5
    other.people_count = 5
    mixed_world.rescue_requests.append(other)
    first = [p.model_dump_json() for p in generate_candidate_plans(mixed_world)]
    for collection in (
        mixed_world.nodes,
        mixed_world.routes,
        mixed_world.responders,
        mixed_world.rescue_requests,
        mixed_world.communities,
        mixed_world.shelters,
    ):
        collection.reverse()
    assert [p.model_dump_json() for p in generate_candidate_plans(mixed_world)] == first
    assert plan(mixed_world).actions[0].responder_id == "responder-0"
    assert plan(mixed_world).actions[0].request_id == "call-1"


def test_generated_actions_validate_with_reservations_and_execute(mixed_world):
    for candidate in generate_candidate_plans(mixed_world):
        state = ExecutionState.from_world(mixed_world)
        assert len({a.responder_id for a in candidate.actions}) == len(
            candidate.actions
        )
        assert len({a.id for a in candidate.actions}) == len(candidate.actions)
        assert candidate.actions == sorted(
            candidate.actions, key=lambda a: (a.start_minute, a.responder_id, a.id)
        )
        for action in candidate.actions:
            checked = validate_action(state, action, mixed_world.current_minute)
            assert checked.accepted, checked
            assert action.start_minute == mixed_world.current_minute
            assert action.id.startswith(candidate.id + ":")
            state.responders[action.responder_id].assignment_id = action.id
            if action.action_type == ActionType.RESCUE:
                state.request_reserved[action.request_id] = (
                    state.request_reserved.get(action.request_id, 0)
                    + action.people_count
                )
            else:
                state.community_reserved[action.community_id] = (
                    state.community_reserved.get(action.community_id, 0)
                    + action.people_count
                )
                state.shelter_reserved[action.shelter_id] = (
                    state.shelter_reserved.get(action.shelter_id, 0)
                    + action.people_count
                )
        # Execution is a test oracle, never part of production generation.
        result = simulate_plan(mixed_world, candidate)
        assert result.metrics.rejected_actions == 0
        assert result.status == "completed"


def test_generator_does_not_simulate(mixed_world, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Plan generation must not execute a simulation")

    monkeypatch.setattr("ark_api.simulation.engine.simulate_plan", forbidden)
    assert len(generate_candidate_plans(mixed_world)) == 3
