import pytest

from ark_api.simulation.models import Capability, LocationNode, RouteEdge, RouteStatus
from ark_api.simulation.routing import (
    CIVILIAN_CAPABILITIES,
    NoRouteError,
    shortest_path,
)


def route(
    world, origin="hill", target="riverside", minute=10, speed=1.0, capabilities=None
):
    return shortest_path(
        world,
        origin,
        target,
        minute,
        capabilities if capabilities is not None else {Capability.ROAD_TRAVEL},
        speed,
    )


def edge(id, origin, target, cost, **changes):
    return RouteEdge(
        id=id,
        origin_node_id=origin,
        destination_node_id=target,
        base_travel_minutes=cost,
        status="open",
        allowed_capabilities={Capability.ROAD_TRAVEL},
        **changes,
    )


def test_shortest_route(simulation_world):
    world = simulation_world
    world.nodes.append(LocationNode(id="mid", name="Midpoint"))
    world.routes.extend([edge("a", "hill", "mid", 1), edge("b", "mid", "riverside", 2)])
    result = route(world)
    assert result.node_ids == ("hill", "mid", "riverside")
    assert result.route_ids == ("a", "b")
    assert result.arrival_minutes == (11, 13)
    assert result.total_travel_minutes == 3
    assert result.arrival_minute == 13


def test_one_way(simulation_world):
    simulation_world.routes[0].bidirectional = False
    with pytest.raises(NoRouteError):
        route(simulation_world)
    assert route(simulation_world, "riverside", "hill").arrival_minute == 15


def test_closed_route(simulation_world):
    simulation_world.routes[0].status = RouteStatus.CLOSED
    with pytest.raises(NoRouteError):
        route(simulation_world)


@pytest.mark.parametrize("closure", [0, 10, 12, 15])
def test_closure_before_during_or_at_exit(simulation_world, closure):
    simulation_world.routes[0].closure_minute = closure
    with pytest.raises(NoRouteError):
        route(simulation_world)


def test_exit_before_closure(simulation_world):
    simulation_world.routes[0].closure_minute = 16
    assert route(simulation_world).arrival_minute == 15


def test_later_edge_closure_uses_projected_entry(simulation_world):
    world = simulation_world
    world.nodes.append(LocationNode(id="mid", name="Midpoint"))
    world.routes = [
        edge("a", "hill", "mid", 3),
        edge("b", "mid", "riverside", 3, closure_minute=16),
    ]
    with pytest.raises(NoRouteError):
        route(world)


def test_capabilities_and_civilians(simulation_world):
    simulation_world.routes[0].allowed_capabilities = {Capability.WATER_TRAVEL}
    with pytest.raises(NoRouteError):
        route(simulation_world, capabilities=CIVILIAN_CAPABILITIES)
    assert (
        route(simulation_world, capabilities={Capability.WATER_TRAVEL}).arrival_minute
        == 15
    )


def test_restricted_and_unrestricted_edges(simulation_world):
    simulation_world.routes[0].status = RouteStatus.RESTRICTED
    assert route(simulation_world).total_travel_minutes == 5
    simulation_world.routes[0].allowed_capabilities = set()
    assert (
        route(simulation_world, capabilities={Capability.FOOT_TRAVEL}).arrival_minute
        == 15
    )


def test_tie_breaking_independent_of_input_order(simulation_world):
    world = simulation_world
    world.nodes.extend([LocationNode(id="x", name="X"), LocationNode(id="y", name="Y")])
    world.routes = [
        edge("z", "hill", "x", 2),
        edge("b", "x", "riverside", 2),
        edge("a", "hill", "y", 2),
        edge("c", "y", "riverside", 2),
    ]
    expected = route(world)
    assert expected.route_ids == ("a", "c")
    world.routes.reverse()
    world.nodes.reverse()
    assert route(world) == expected


@pytest.mark.parametrize("speed,minutes", [(2.0, 3), (0.5, 10), (100.0, 1), (1.25, 4)])
def test_speed_rounding(simulation_world, speed, minutes):
    assert route(simulation_world, speed=speed).total_travel_minutes == minutes


def test_rounding_is_per_edge(simulation_world):
    simulation_world.nodes.append(LocationNode(id="mid", name="Midpoint"))
    simulation_world.routes = [
        edge("a", "hill", "mid", 1),
        edge("b", "mid", "riverside", 1),
    ]
    assert route(simulation_world, speed=2.0).total_travel_minutes == 2


def test_no_route_and_unknown_node(simulation_world):
    simulation_world.routes = []
    with pytest.raises(NoRouteError):
        route(simulation_world)
    with pytest.raises(NoRouteError):
        route(simulation_world, target="absent")


def test_same_node_zero_trip(simulation_world):
    path = route(simulation_world, target="hill")
    assert path.node_ids == ("hill",)
    assert path.route_ids == ()
    assert path.total_travel_minutes == 0
    assert path.arrival_minute == 10
