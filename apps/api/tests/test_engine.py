import pytest

from ark_api.simulation.engine import simulate_plan
from ark_api.simulation.models import (
    Capability,
    EventType,
    LocationNode,
    RequestStatus,
    RouteEdge,
)


def rescue(make_action, **changes):
    data = dict(action_type="rescue", request_id="call-1", people_count=5)
    return make_action(**(data | changes))


def evacuate(make_action, **changes):
    data = dict(
        action_type="evacuate",
        community_id="community-1",
        shelter_id="shelter-1",
        people_count=20,
    )
    return make_action(**(data | changes))


def final_state(result):
    return result.timeline[-1].metadata


def test_movement(simulation_world, make_action, make_plan):
    result = simulate_plan(simulation_world, make_plan(make_action()))
    responder = final_state(result)["responders"]["bus-1"]
    assert responder["node_id"] == "riverside"
    assert responder["available_minute"] == 15
    assert responder["assignment_id"] is None
    assert [
        (e.minute, e.metadata["phase"])
        for e in result.timeline
        if "phase" in e.metadata
    ] == [(10, "dispatch"), (15, "arrival"), (15, "completed")]


def test_full_rescue_and_metrics(simulation_world, make_action, make_plan):
    result = simulate_plan(simulation_world, make_plan(rescue(make_action)))
    assert result.metrics.people_rescued == 5
    assert result.metrics.critical_calls_completed == 1
    assert result.metrics.critical_calls_unanswered == 0
    assert result.metrics.average_response_minutes == 10
    assert final_state(result)["requests"]["call-1"]["status"] == "completed"
    assert result.score is None
    assert result.score_breakdown == []


def test_partial_rescue(simulation_world, make_action, make_plan):
    result = simulate_plan(
        simulation_world, make_plan(rescue(make_action, people_count=2))
    )
    assert result.metrics.people_rescued == 2
    assert result.metrics.critical_calls_unanswered == 1
    assert final_state(result)["requests"]["call-1"]["status"] == "in_progress"


def test_multiple_partial_rescues_first_response_only(
    simulation_world, make_action, make_plan
):
    plan = make_plan(
        rescue(make_action, people_count=2),
        rescue(make_action, id="second", people_count=3, start_minute=16),
    )
    result = simulate_plan(simulation_world, plan)
    assert result.metrics.people_rescued == 5
    assert result.metrics.critical_calls_completed == 1
    assert result.metrics.average_response_minutes == 10


def test_duplicate_rescue_prevented(simulation_world, make_action, make_plan):
    plan = make_plan(
        rescue(make_action), rescue(make_action, id="second", start_minute=16)
    )
    result = simulate_plan(simulation_world, plan)
    assert result.metrics.people_rescued == 5
    assert result.metrics.rejected_actions == 1
    assert "people_unavailable" in result.violations[0]


@pytest.mark.parametrize("count", [7, 20])
def test_full_and_partial_evacuation(simulation_world, make_action, make_plan, count):
    result = simulate_plan(
        simulation_world, make_plan(evacuate(make_action, people_count=count))
    )
    assert result.metrics.people_evacuated == count
    assert final_state(result)["communities"]["community-1"]["evacuated_count"] == count
    assert final_state(result)["shelters"]["shelter-1"] == {
        "occupancy": count,
        "reserved": 0,
    }
    phases = [(e.minute, e.metadata.get("phase")) for e in result.timeline]
    assert (15, "pickup") in phases
    assert (20, "shelter_arrival") in phases


def test_route_closure_and_execution_time_revalidation(
    simulation_world, make_action, make_plan
):
    simulation_world.routes[0].closure_minute = 20
    plan = make_plan(
        make_action(), make_action(id="return", target_node_id="hill", start_minute=20)
    )
    result = simulate_plan(simulation_world, plan)
    assert result.metrics.rejected_actions == 1
    assert "no_route" in result.violations[0]
    closures = [e for e in result.timeline if e.event_type == EventType.ROUTE_CLOSED]
    assert len(closures) == 1
    assert closures[0].minute == 20
    assert final_state(result)["closed_route_ids"] == ["road-1"]
    assert result.metrics.people_isolated == 25
    assert result.metrics.responders_stranded == 1


def test_continues_after_rejection(simulation_world, make_action, make_plan):
    plan = make_plan(
        make_action(id="bad", responder_id="absent"),
        rescue(make_action, start_minute=11),
    )
    result = simulate_plan(simulation_world, plan)
    assert result.metrics.rejected_actions == 1
    assert result.metrics.people_rescued == 5


def test_empty_plan(simulation_world, make_plan):
    result = simulate_plan(simulation_world, make_plan())
    assert result.status == "completed"
    assert result.metrics.people_rescued == 0
    assert result.metrics.critical_calls_unanswered == 1
    assert result.metrics.average_response_minutes is None
    assert result.metrics.rejected_actions == 0
    assert len(result.timeline) == 2


def test_all_rejected(simulation_world, make_action, make_plan):
    result = simulate_plan(
        simulation_world,
        make_plan(
            make_action(responder_id="absent"), make_action(id="second", start_minute=9)
        ),
    )
    assert result.status == "completed"
    assert result.metrics.rejected_actions == 2
    assert len(result.violations) == 2
    assert sum(e.event_type == EventType.ACTION_REJECTED for e in result.timeline) == 2


def test_inputs_unchanged_and_runs_isolated(simulation_world, make_action, make_plan):
    plan = make_plan(evacuate(make_action))
    before_world = simulation_world.model_dump_json()
    before_plan = plan.model_dump_json()
    first = simulate_plan(simulation_world, plan)
    second = simulate_plan(simulation_world, plan)
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    first.timeline[-1].metadata["shelters"]["shelter-1"]["occupancy"] = 999
    assert final_state(second)["shelters"]["shelter-1"]["occupancy"] == 20
    assert simulation_world.model_dump_json() == before_world
    assert plan.model_dump_json() == before_plan


def test_stable_action_order_and_overlap(simulation_world, make_action, make_plan):
    a = make_action(id="a")
    z = make_action(id="z", target_node_id="hill")
    first = simulate_plan(simulation_world, make_plan(z, a))
    second = simulate_plan(simulation_world, make_plan(a, z))
    assert first == second
    assert first.metrics.rejected_actions == 1
    assert "z: overlapping_assignment" in first.violations[0]


def test_arrival_before_same_minute_dispatch(simulation_world, make_action, make_plan):
    result = simulate_plan(
        simulation_world,
        make_plan(
            make_action(),
            make_action(id="return", start_minute=15, target_node_id="hill"),
        ),
    )
    assert result.metrics.rejected_actions == 0
    assert final_state(result)["responders"]["bus-1"]["node_id"] == "hill"


def test_overflow_attempt(simulation_world, make_action, make_plan):
    simulation_world.shelters[0].occupancy = 35
    result = simulate_plan(
        simulation_world, make_plan(evacuate(make_action, people_count=10))
    )
    assert result.metrics.shelter_peak_overflow == 5
    assert result.metrics.rejected_actions == 1
    assert result.metrics.people_evacuated == 0
    assert final_state(result)["shelters"]["shelter-1"]["occupancy"] == 35


def test_civilian_isolation_excludes_water_routes(simulation_world, make_plan):
    simulation_world.routes[0].allowed_capabilities = {Capability.WATER_TRAVEL}
    simulation_world.responders[0].current_node_id = "riverside"
    simulation_world.responders[0].capabilities.add(Capability.WATER_TRAVEL)
    result = simulate_plan(simulation_world, make_plan())
    assert result.metrics.people_isolated == 25
    assert result.metrics.responders_stranded == 0


def test_horizon_mid_evacuation(simulation_world, make_action, make_plan):
    result = simulate_plan(
        simulation_world, make_plan(evacuate(make_action)), duration_minutes=7
    )
    assert result.status == "completed"
    assert result.metrics.people_evacuated == 0
    runtime = final_state(result)["responders"]["bus-1"]
    assert runtime["node_id"] is None
    assert runtime["route_id"] == "road-1"
    assert runtime["carrying"] == 20
    assert final_state(result)["shelters"]["shelter-1"] == {
        "occupancy": 0,
        "reserved": 20,
    }
    assert all(event.minute <= 17 for event in result.timeline)
    assert_incomplete_at_horizon(result, "action-1", "bus-1", 17)


def test_horizon_arrival_inclusive(simulation_world, make_action, make_plan):
    result = simulate_plan(
        simulation_world, make_plan(evacuate(make_action)), duration_minutes=10
    )
    assert result.status == "completed"
    assert result.metrics.people_evacuated == 20
    assert not any(
        e.metadata.get("phase") == "incomplete_at_horizon" for e in result.timeline
    )


def test_future_actions_remain_pending(simulation_world, make_action, make_plan):
    result = simulate_plan(
        simulation_world, make_plan(make_action(start_minute=100)), duration_minutes=5
    )
    assert result.status == "completed"
    assert result.metrics.rejected_actions == 0
    assert len(result.timeline) == 2
    assert final_state(result)["pending_action_ids"] == ["action-1"]


def assert_incomplete_at_horizon(result, action_id, responder_id, minute):
    events = [
        e
        for e in result.timeline
        if e.metadata.get("phase") == "incomplete_at_horizon"
        and e.metadata.get("action_id") == action_id
    ]
    assert len(events) == 1
    event = events[0]
    assert event.minute == minute
    assert event.actor_id == responder_id
    assert event.event_type == EventType.SIMULATION_COMPLETED
    assert event.metadata["action_status"] == "in_progress"
    assert "incomplete at the end of the simulation horizon" in event.message
    assert not any(
        e.event_type in {EventType.ACTION_COMPLETED, EventType.ACTION_FAILED}
        and e.metadata.get("action_id") == action_id
        for e in result.timeline
    )
    assert result.violations == []


def test_unfinished_move_has_terminal_run_status(
    simulation_world, make_action, make_plan
):
    result = simulate_plan(simulation_world, make_plan(make_action()), 2)
    assert result.status == "completed"
    assert final_state(result)["responders"]["bus-1"]["node_id"] is None
    assert_incomplete_at_horizon(result, "action-1", "bus-1", 12)


def test_unfinished_rescue_does_not_count_service(
    simulation_world, make_action, make_plan
):
    result = simulate_plan(simulation_world, make_plan(rescue(make_action)), 2)
    assert result.status == "completed"
    assert result.metrics.people_rescued == 0
    assert result.metrics.critical_calls_completed == 0
    assert result.metrics.critical_calls_unanswered == 1
    assert result.metrics.average_response_minutes is None
    assert final_state(result)["requests"]["call-1"]["rescued"] == 0
    assert_incomplete_at_horizon(result, "action-1", "bus-1", 12)


def test_incomplete_event_order_is_deterministic(
    simulation_world, make_action, make_plan
):
    other = simulation_world.responders[0].model_copy(deep=True)
    other.id = "bus-2"
    simulation_world.responders.append(other)
    first = make_action(id="z")
    second = make_action(id="a", responder_id="bus-2")
    result = simulate_plan(simulation_world, make_plan(second, first), 2)
    repeated = simulate_plan(simulation_world, make_plan(first, second), 2)
    assert result.model_dump_json() == repeated.model_dump_json()
    events = [
        e for e in result.timeline if e.metadata.get("phase") == "incomplete_at_horizon"
    ]
    assert [(e.minute, e.actor_id, e.metadata["action_id"]) for e in events] == [
        (12, "bus-1", "z"),
        (12, "bus-2", "a"),
    ]
    assert result.timeline[-3:-1] == events
    assert result.status == "completed"


def test_competing_rescues_reserve_people(simulation_world, make_action, make_plan):
    other = simulation_world.responders[0].model_copy(deep=True)
    other.id = "bus-2"
    simulation_world.responders.append(other)
    plan = make_plan(
        rescue(make_action), rescue(make_action, id="second", responder_id="bus-2")
    )
    result = simulate_plan(simulation_world, plan)
    assert result.metrics.people_rescued == 5
    assert result.metrics.rejected_actions == 1
    assert "people_unavailable" in result.violations[0]


def test_competing_evacuations_reserve_shelter(
    simulation_world, make_action, make_plan
):
    simulation_world.shelters[0].capacity = 15
    other = simulation_world.responders[0].model_copy(deep=True)
    other.id = "bus-2"
    simulation_world.responders.append(other)
    plan = make_plan(
        evacuate(make_action, people_count=10),
        evacuate(make_action, id="second", responder_id="bus-2", people_count=10),
    )
    result = simulate_plan(simulation_world, plan)
    assert result.metrics.people_evacuated == 10
    assert result.metrics.rejected_actions == 1
    assert result.metrics.shelter_peak_overflow == 5
    assert final_state(result)["shelters"]["shelter-1"]["occupancy"] == 10


def test_initial_completed_requests_not_rescued_again(
    simulation_world, make_action, make_plan
):
    simulation_world.rescue_requests[0].status = RequestStatus.COMPLETED
    result = simulate_plan(simulation_world, make_plan(rescue(make_action)))
    assert result.metrics.people_rescued == 0
    assert result.metrics.critical_calls_completed == 1
    assert result.metrics.average_response_minutes is None
    assert result.metrics.rejected_actions == 1


@pytest.mark.parametrize("duration", [0, -1, True, 1.5])
def test_invalid_duration(simulation_world, make_plan, duration):
    with pytest.raises(ValueError, match="positive integer"):
        simulate_plan(simulation_world, make_plan(), duration)


def test_timeline_total_order(simulation_world, make_action, make_plan):
    result = simulate_plan(
        simulation_world,
        make_plan(evacuate(make_action), make_action(id="second", start_minute=30)),
    )
    assert [(e.minute, e.id) for e in result.timeline] == sorted(
        (e.minute, e.id) for e in result.timeline
    )
    assert len({e.id for e in result.timeline}) == len(result.timeline)


def test_zero_distance_service(simulation_world, make_action, make_plan):
    simulation_world.responders[0].current_node_id = "riverside"
    result = simulate_plan(simulation_world, make_plan(rescue(make_action)), 1)
    assert result.metrics.people_rescued == 5
    assert result.metrics.average_response_minutes == 5
    assert final_state(result)["responders"]["bus-1"]["assignment_id"] is None


def test_zero_distance_pickup_and_delivery(simulation_world, make_action, make_plan):
    simulation_world.responders[0].current_node_id = "riverside"
    simulation_world.shelters[0].node_id = "riverside"
    result = simulate_plan(simulation_world, make_plan(evacuate(make_action)), 1)
    assert result.metrics.people_evacuated == 20
    assert final_state(result)["communities"]["community-1"]["status"] == "evacuated"
    assert final_state(result)["responders"]["bus-1"]["carrying"] == 0
    assert result.status == "completed"


def test_multiple_edge_arrivals(simulation_world, make_action, make_plan):
    simulation_world.nodes.append(LocationNode(id="mid", name="Midpoint"))
    simulation_world.routes = [
        RouteEdge(
            id="first",
            origin_node_id="hill",
            destination_node_id="mid",
            base_travel_minutes=2,
            status="open",
            allowed_capabilities=set(),
        ),
        RouteEdge(
            id="second",
            origin_node_id="mid",
            destination_node_id="riverside",
            base_travel_minutes=2,
            status="open",
            allowed_capabilities=set(),
        ),
    ]
    plan = make_plan(make_action())
    partial = simulate_plan(simulation_world, plan, 3)
    assert final_state(partial)["responders"]["bus-1"]["route_id"] == "second"
    assert final_state(partial)["responders"]["bus-1"]["node_id"] is None
    complete = simulate_plan(simulation_world, plan, 4)
    arrivals = [
        (e.minute, e.target_id)
        for e in complete.timeline
        if e.metadata.get("phase") == "arrival"
    ]
    assert arrivals == [(12, "mid"), (14, "riverside")]
    assert complete.status == "completed"


@pytest.mark.parametrize("count", [1, 4, 10, 20])
def test_repeated_evacuation_conserves_people(
    simulation_world, make_action, make_plan, count
):
    plan = make_plan(
        *(
            evacuate(
                make_action,
                id=f"action-{i:02d}",
                start_minute=10 + 10 * i,
                people_count=count,
            )
            for i in range(6)
        )
    )
    result = simulate_plan(simulation_world, plan, 60)
    expected = min(6, 20 // count) * count
    assert result.metrics.people_evacuated == expected
    assert (
        final_state(result)["communities"]["community-1"]["evacuated_count"] == expected
    )
    assert final_state(result)["shelters"]["shelter-1"]["occupancy"] == expected
    assert result.metrics.rejected_actions == 6 - expected // count


def test_initial_population_and_occupancy_preserved(
    simulation_world, make_action, make_plan
):
    simulation_world.communities[0].evacuated_count = 12
    simulation_world.shelters[0].occupancy = 12
    result = simulate_plan(
        simulation_world, make_plan(evacuate(make_action, people_count=8))
    )
    assert result.metrics.people_evacuated == 8
    assert final_state(result)["communities"]["community-1"]["evacuated_count"] == 20
    assert final_state(result)["shelters"]["shelter-1"]["occupancy"] == 20


def test_no_safe_nodes_and_cancelled_requests(simulation_world, make_plan):
    simulation_world.nodes[1].is_safe_zone = False
    simulation_world.rescue_requests[0].status = RequestStatus.CANCELLED
    result = simulate_plan(simulation_world, make_plan())
    assert result.metrics.people_isolated == 20
    assert result.metrics.responders_stranded == 1
    assert result.metrics.critical_calls_unanswered == 0
    assert final_state(result)["responders"]["bus-1"]["status"] == "stranded"
    assert final_state(result)["communities"]["community-1"]["status"] == "isolated"


def test_average_response_across_requests(simulation_world, make_action, make_plan):
    other = simulation_world.rescue_requests[0].model_copy(deep=True)
    other.id = "call-2"
    other.reported_minute = 9
    simulation_world.rescue_requests.append(other)
    plan = make_plan(
        rescue(make_action),
        rescue(make_action, id="second", request_id="call-2", start_minute=17),
    )
    result = simulate_plan(simulation_world, plan)
    assert result.metrics.average_response_minutes == 9.0  # (15 - 5 + 17 - 9) / 2
    assert result.metrics.people_rescued == 10
    assert result.metrics.critical_calls_completed == 2


def test_schema_serialization_of_engine_result(
    simulation_world, make_action, make_plan
):
    result = simulate_plan(simulation_world, make_plan(evacuate(make_action)))
    assert type(result).model_validate_json(result.model_dump_json()) == result
