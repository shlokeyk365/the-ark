import pytest

from ark_api.simulation.models import Capability, ResponderStatus, ShelterStatus
from ark_api.simulation.validation import ExecutionState, ReasonCode, validate_action


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"responder_id": "missing"}, ReasonCode.RESPONDER_NOT_FOUND),
        ({"target_node_id": "missing"}, ReasonCode.TARGET_NOT_FOUND),
        ({"request_id": "missing"}, ReasonCode.REQUEST_NOT_FOUND),
        ({"community_id": "missing"}, ReasonCode.COMMUNITY_NOT_FOUND),
        ({"shelter_id": "missing"}, ReasonCode.SHELTER_NOT_FOUND),
        ({"start_minute": 9}, ReasonCode.BEFORE_CURRENT_TIME),
        ({"action_type": "wait"}, ReasonCode.UNSUPPORTED_ACTION),
        ({"people_count": 1}, ReasonCode.INVALID_TARGET),
        ({"request_id": "call-1"}, ReasonCode.INVALID_TARGET),
        ({"action_type": "rescue"}, ReasonCode.INVALID_TARGET),
        (
            {"action_type": "evacuate", "community_id": "community-1"},
            ReasonCode.INVALID_TARGET,
        ),
    ],
)
def test_invalid_action_reasons(simulation_world, make_action, changes, reason):
    result = validate_action(
        ExecutionState.from_world(simulation_world), make_action(**changes), 10
    )
    assert not result.accepted
    assert result.reason_code == reason


def rescue(make_action, **changes):
    return make_action(
        action_type="rescue", request_id="call-1", people_count=5, **changes
    )


def evacuation(make_action, **changes):
    return make_action(
        action_type="evacuate",
        community_id="community-1",
        shelter_id="shelter-1",
        people_count=10,
        **changes,
    )


def test_wrong_capability(simulation_world, make_action):
    simulation_world.responders[0].capabilities.remove(Capability.RESCUE)
    result = validate_action(
        ExecutionState.from_world(simulation_world), rescue(make_action), 10
    )
    assert result.reason_code == ReasonCode.MISSING_CAPABILITY


def test_medical_priority_requires_medical_capability(simulation_world, make_action):
    simulation_world.rescue_requests[0].medical_priority = True
    assert (
        validate_action(
            ExecutionState.from_world(simulation_world), rescue(make_action), 10
        ).reason_code
        == ReasonCode.MISSING_CAPABILITY
    )


def test_over_capacity(simulation_world, make_action):
    simulation_world.responders[0].capacity = 4
    assert (
        validate_action(
            ExecutionState.from_world(simulation_world), rescue(make_action), 10
        ).reason_code
        == ReasonCode.CAPACITY_EXCEEDED
    )


def test_overlap(simulation_world, make_action):
    state = ExecutionState.from_world(simulation_world)
    state.responders["bus-1"].assignment_id = "busy"
    assert (
        validate_action(state, make_action(), 10).reason_code
        == ReasonCode.OVERLAPPING_ASSIGNMENT
    )


def test_unavailable(simulation_world, make_action):
    simulation_world.responders[0].status = ResponderStatus.STRANDED
    assert (
        validate_action(
            ExecutionState.from_world(simulation_world), make_action(), 10
        ).reason_code
        == ReasonCode.RESPONDER_UNAVAILABLE
    )


@pytest.mark.parametrize(
    "status,occupancy,reason,overflow",
    [
        (ShelterStatus.CLOSED, 0, ReasonCode.SHELTER_CLOSED, 0),
        (ShelterStatus.FULL, 40, ReasonCode.SHELTER_CAPACITY_EXCEEDED, 10),
        (ShelterStatus.OPEN, 35, ReasonCode.SHELTER_CAPACITY_EXCEEDED, 5),
    ],
)
def test_shelter_admission(
    simulation_world, make_action, status, occupancy, reason, overflow
):
    simulation_world.shelters[0].status = status
    simulation_world.shelters[0].occupancy = occupancy
    result = validate_action(
        ExecutionState.from_world(simulation_world), evacuation(make_action), 10
    )
    assert result.reason_code == reason
    assert result.shelter_overflow == overflow


def test_wrong_target_node(simulation_world, make_action):
    assert (
        validate_action(
            ExecutionState.from_world(simulation_world),
            rescue(make_action, target_node_id="hill"),
            10,
        ).reason_code
        == ReasonCode.INVALID_TARGET
    )


def test_no_route_for_delivery(simulation_world, make_action):
    simulation_world.routes[0].closure_minute = 20
    assert (
        validate_action(
            ExecutionState.from_world(simulation_world), evacuation(make_action), 10
        ).reason_code
        == ReasonCode.NO_ROUTE
    )


def test_reservations_prevent_duplicate_service(simulation_world, make_action):
    state = ExecutionState.from_world(simulation_world)
    state.request_reserved["call-1"] = 3
    assert (
        validate_action(state, rescue(make_action), 10).reason_code
        == ReasonCode.PEOPLE_UNAVAILABLE
    )


def test_valid_evacuation_and_pure_validation(simulation_world, make_action):
    state = ExecutionState.from_world(simulation_world)
    result = validate_action(state, evacuation(make_action), 10)
    assert result.accepted
    assert result.outbound.arrival_minute == 15
    assert result.delivery.arrival_minute == 20
    assert state.community_reserved == {}
    assert state.shelter_reserved == {}
    assert state.responders["bus-1"].assignment_id is None
