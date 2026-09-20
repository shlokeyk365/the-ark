"""Small, generic world fixture reusable by future simulation tests."""

import pytest

from ark_api.simulation.models import Capability, PlanAction, ResponsePlan, WorldState


@pytest.fixture
def world_state() -> WorldState:
    return WorldState.model_validate(
        {
            "scenario_id": "river-response",
            "current_minute": 10,
            "nodes": [
                {
                    "id": "riverside",
                    "name": "Riverside",
                    "latitude": 40.0,
                    "longitude": -75.0,
                },
                {"id": "hill", "name": "Hill", "is_safe_zone": True},
            ],
            "hazards": [
                {
                    "id": "flood-1",
                    "type": "flood",
                    "affected_node_ids": ["riverside"],
                    "start_minute": 0,
                    "severity": 3,
                    "source": "recorded-physics",
                    "observed": True,
                }
            ],
            "routes": [
                {
                    "id": "road-1",
                    "origin_node_id": "riverside",
                    "destination_node_id": "hill",
                    "base_travel_minutes": 5,
                    "status": "open",
                    "closure_minute": 30,
                    "allowed_capabilities": ["road_travel"],
                }
            ],
            "responders": [
                {
                    "id": "bus-1",
                    "name": "Bus One",
                    "type": "bus",
                    "current_node_id": "hill",
                    "capacity": 20,
                    "capabilities": ["road_travel", "evacuation"],
                    "status": "available",
                }
            ],
            "rescue_requests": [
                {
                    "id": "call-1",
                    "node_id": "riverside",
                    "people_count": 5,
                    "urgency": 4,
                    "reported_minute": 5,
                    "isolation_minute": 30,
                    "required_capabilities": ["evacuation"],
                    "status": "pending",
                }
            ],
            "communities": [
                {
                    "id": "community-1",
                    "name": "Riverside Community",
                    "node_id": "riverside",
                    "population": 20,
                    "isolation_minute": 30,
                    "status": "at_risk",
                }
            ],
            "shelters": [
                {
                    "id": "shelter-1",
                    "name": "Hill Shelter",
                    "node_id": "hill",
                    "capacity": 40,
                    "status": "open",
                }
            ],
            "metadata": {"source": "test", "tags": ["generic"], "revision": 1},
        }
    )


@pytest.fixture
def simulation_world(world_state):
    world = world_state.model_copy(deep=True)
    world.routes[0].closure_minute = None
    world.responders[0].capabilities.add(Capability.RESCUE)
    return world


@pytest.fixture
def make_action():
    def factory(**changes):
        data = dict(
            id="action-1",
            responder_id="bus-1",
            action_type="move",
            target_node_id="riverside",
            start_minute=10,
        )
        data.update(changes)
        return PlanAction.model_validate(data)

    return factory


@pytest.fixture
def make_plan():
    def factory(*actions):
        return ResponsePlan(
            id="plan-1",
            name="Test plan",
            description="Test execution",
            actions=list(actions),
            status="ready",
        )

    return factory
