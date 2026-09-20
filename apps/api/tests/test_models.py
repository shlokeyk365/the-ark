import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from ark_api.simulation import models as m


@pytest.fixture
def action():
    return m.PlanAction(
        id="action-1",
        responder_id="bus-1",
        action_type="evacuate",
        target_node_id="riverside",
        start_minute=10,
        people_count=5,
        request_id="call-1",
        community_id="community-1",
        shelter_id="shelter-1",
    )


@pytest.fixture
def plan(action):
    return m.ResponsePlan(
        id="plan-1",
        name="Evacuate Riverside",
        description="A sample plan.",
        actions=[action],
        objectives=["Evacuate people safely"],
        status="ready",
    )


@pytest.fixture
def result():
    return m.ScenarioResult(
        plan_id="plan-1",
        status="completed",
        simulation_minutes=60,
        score=10.0,
        metrics=m.ScenarioMetrics(
            people_rescued=0,
            people_evacuated=5,
            people_isolated=0,
            responders_stranded=0,
            critical_calls_completed=1,
            critical_calls_unanswered=0,
            average_response_minutes=5.0,
            shelter_peak_overflow=0,
            rejected_actions=0,
        ),
        score_breakdown=[
            m.ScoreContribution(
                metric="people_evacuated",
                raw_value=5.0,
                weight=2.0,
                contribution=10.0,
                explanation="Example supplied score.",
            )
        ],
        timeline=[
            m.TimelineEvent(
                id="event-1",
                minute=15,
                event_type="action_completed",
                actor_id="bus-1",
                target_id="riverside",
                message="Evacuation completed.",
            )
        ],
        violations=[],
    )


@pytest.fixture
def contract_examples(world_state, action, plan, result):
    """An instance of every requested contract, including nested envelopes."""
    return [
        world_state.nodes[0],
        world_state.hazards[0],
        world_state.routes[0],
        world_state.responders[0],
        world_state.rescue_requests[0],
        world_state.communities[0],
        world_state.shelters[0],
        world_state,
        action,
        plan,
        result.timeline[0],
        result.metrics,
        result.score_breakdown[0],
        result,
        m.SimulationRequest(world_state=world_state, plans=[plan]),
        m.SimulationResponse(
            recommended_plan_id="plan-1",
            results=[result],
            disclaimer="Simulation only.",
            model_version="0.1.0",
        ),
    ]


def test_all_contracts_round_trip(contract_examples):
    assert len(contract_examples) == 16
    for model in contract_examples:
        assert type(model).model_validate_json(model.model_dump_json()) == model
        assert type(model).model_validate(model.model_dump(mode="json")) == model


def test_unknown_fields_rejected_for_every_contract(contract_examples):
    for model in contract_examples:
        payload = model.model_dump(mode="json")
        payload["misspelled_field"] = 1
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            type(model).model_validate(payload)


COLLECTIONS = [
    "nodes",
    "hazards",
    "routes",
    "responders",
    "rescue_requests",
    "communities",
    "shelters",
]


@pytest.mark.parametrize("collection", COLLECTIONS)
def test_duplicate_ids(world_state, collection):
    payload = world_state.model_dump(mode="json")
    payload[collection].append(deepcopy(payload[collection][0]))
    with pytest.raises(ValidationError, match="unique"):
        m.WorldState.model_validate(payload)


@pytest.mark.parametrize(
    "collection,field",
    [
        ("hazards", "affected_node_ids"),
        ("routes", "origin_node_id"),
        ("routes", "destination_node_id"),
        ("responders", "current_node_id"),
        ("rescue_requests", "node_id"),
        ("communities", "node_id"),
        ("shelters", "node_id"),
    ],
)
def test_missing_node_references(world_state, collection, field):
    payload = world_state.model_dump(mode="json")
    payload[collection][0][field] = (
        ["missing"] if field == "affected_node_ids" else "missing"
    )
    with pytest.raises(ValidationError, match="missing node"):
        m.WorldState.model_validate(payload)


@pytest.mark.parametrize(
    "collection,field,value",
    [
        ("responders", "capacity", -1),
        ("shelters", "capacity", -1),
        ("shelters", "capacity", 0),
        ("routes", "base_travel_minutes", -1),
        ("routes", "base_travel_minutes", 0),
        ("responders", "speed_multiplier", 0),
        ("responders", "speed_multiplier", -1.0),
        ("responders", "speed_multiplier", float("inf")),
        ("responders", "capabilities", []),
        ("rescue_requests", "urgency", 0),
        ("rescue_requests", "urgency", 6),
        ("hazards", "severity", 0),
        ("hazards", "severity", 6),
        ("hazards", "start_minute", -1),
        ("routes", "closure_minute", -1),
        ("rescue_requests", "reported_minute", -1),
        ("rescue_requests", "isolation_minute", -1),
        ("communities", "isolation_minute", -1),
        ("rescue_requests", "people_count", 0),
        ("communities", "population", 0),
        ("communities", "evacuated_count", -1),
        ("shelters", "occupancy", -1),
        ("nodes", "latitude", -90.1),
        ("nodes", "latitude", 90.1),
        ("nodes", "longitude", -180.1),
        ("nodes", "longitude", 180.1),
        ("nodes", "latitude", float("nan")),
        ("nodes", "id", "  "),
        ("nodes", "name", ""),
        ("responders", "capacity", "20"),
        ("responders", "capacity", True),
        ("routes", "base_travel_minutes", 1.5),
        ("hazards", "observed", "true"),
        ("nodes", "is_safe_zone", 1),
        ("responders", "speed_multiplier", "1.0"),
    ],
)
def test_invalid_world_fields(world_state, collection, field, value):
    payload = world_state.model_dump(mode="json")
    payload[collection][0][field] = value
    with pytest.raises(ValidationError):
        m.WorldState.model_validate(payload)


@pytest.mark.parametrize(
    "collection,field,value",
    [
        ("communities", "evacuated_count", 21),
        ("shelters", "occupancy", 41),
        ("routes", "destination_node_id", "riverside"),
    ],
)
def test_cross_field_constraints(world_state, collection, field, value):
    payload = world_state.model_dump(mode="json")
    payload[collection][0][field] = value
    with pytest.raises(ValidationError):
        m.WorldState.model_validate(payload)


def test_boundary_values_and_historical_times(world_state):
    payload = world_state.model_dump(mode="json")
    payload["nodes"][0].update(latitude=-90.0, longitude=-180.0)
    payload["nodes"][1].update(latitude=90.0, longitude=180.0)
    payload["responders"][0]["capacity"] = 0
    payload["communities"][0].update(evacuated_count=20, isolation_minute=0)
    payload["shelters"][0]["occupancy"] = 40
    payload["routes"][0].update(status="closed", closure_minute=0)
    # Calls can be reported after a community has become isolated.
    payload["rescue_requests"][0]["isolation_minute"] = 0
    assert m.WorldState.model_validate(payload).current_minute == 10


def test_optional_times_can_be_absent(world_state):
    payload = world_state.model_dump(mode="json")
    for collection, field in [
        ("routes", "closure_minute"),
        ("communities", "isolation_minute"),
        ("rescue_requests", "isolation_minute"),
    ]:
        payload[collection][0].pop(field)
    model = m.WorldState.model_validate(payload)
    assert model.routes[0].closure_minute is None
    assert model.communities[0].isolation_minute is None
    assert model.rescue_requests[0].isolation_minute is None


@pytest.mark.parametrize(
    "field",
    [
        "people_rescued",
        "people_evacuated",
        "people_isolated",
        "responders_stranded",
        "critical_calls_completed",
        "critical_calls_unanswered",
        "shelter_peak_overflow",
        "rejected_actions",
        "average_response_minutes",
    ],
)
def test_negative_metrics_rejected(result, field):
    payload = result.metrics.model_dump()
    payload[field] = -1
    with pytest.raises(ValidationError):
        m.ScenarioMetrics.model_validate(payload)


@pytest.mark.parametrize(
    "enum",
    [
        m.HazardType,
        m.RouteStatus,
        m.ResponderType,
        m.ResponderStatus,
        m.Capability,
        m.RequestStatus,
        m.CommunityStatus,
        m.ShelterStatus,
        m.ActionType,
        m.ActionStatus,
        m.EventType,
        m.PlanStatus,
    ],
)
def test_enum_values_are_stable_strings(enum):
    for member in enum:
        assert enum(json.loads(json.dumps(member))) is member
    with pytest.raises(ValueError):
        enum("unknown-value")


def test_unknown_enum_in_nested_payload_rejected(world_state):
    payload = world_state.model_dump(mode="json")
    payload["routes"][0]["status"] = "magically_passable"
    with pytest.raises(ValidationError):
        m.WorldState.model_validate(payload)


def test_response_serialization(result):
    response = m.SimulationResponse(
        recommended_plan_id="plan-1",
        results=[result],
        disclaimer="Simulation only.",
        model_version="0.1.0",
    )
    payload = json.loads(response.model_dump_json())
    assert payload["recommended_plan_id"] == "plan-1"
    assert payload["results"][0]["status"] == "completed"
    assert payload["results"][0]["metrics"]["people_evacuated"] == 5
    assert payload["results"][0]["score_breakdown"][0]["contribution"] == 10.0
    assert payload["results"][0]["timeline"][0]["event_type"] == "action_completed"
    assert (
        m.SimulationResponse.model_validate_json(response.model_dump_json()) == response
    )


def test_simulation_request_defaults(world_state):
    request = m.SimulationRequest(world_state=world_state)
    assert request.duration_minutes == 60
    assert request.random_seed == 42
    assert request.plans is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("duration_minutes", 0),
        ("duration_minutes", -1),
        ("duration_minutes", "60"),
        ("random_seed", 1.5),
        ("random_seed", True),
    ],
)
def test_invalid_request_fields(world_state, field, value):
    with pytest.raises(ValidationError):
        m.SimulationRequest(world_state=world_state, **{field: value})


def test_unique_plan_actions(plan):
    payload = plan.model_dump(mode="json")
    payload["actions"].append(deepcopy(payload["actions"][0]))
    with pytest.raises(ValidationError, match="unique"):
        m.ResponsePlan.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("start_minute", -1),
        ("people_count", 0),
        ("people_count", -1),
        ("responder_id", " "),
        ("request_id", ""),
    ],
)
def test_invalid_action_fields(action, field, value):
    payload = action.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        m.PlanAction.model_validate(payload)


def test_result_optional_scores_and_undefined_response_average(result):
    payload = result.model_dump(mode="json")
    payload["score"] = None
    payload["metrics"]["average_response_minutes"] = None
    model = m.ScenarioResult.model_validate(payload)
    assert model.score is None
    assert model.metrics.average_response_minutes is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("score", float("inf")),
        ("simulation_minutes", -1),
    ],
)
def test_invalid_result_fields(result, field, value):
    payload = result.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        m.ScenarioResult.model_validate(payload)


def test_mutable_defaults_are_independent(world_state, action):
    other = m.WorldState(scenario_id="other", current_minute=0, nodes=[])
    world_state.metadata["new"] = True
    assert other.metadata == {}
    first = m.PlanAction.model_validate(action.model_dump())
    first.metadata["new"] = True
    assert action.metadata == {}


def test_metadata_must_be_json_serializable(world_state):
    payload = world_state.model_dump(mode="json")
    payload["metadata"] = {"invalid": object()}
    with pytest.raises(ValidationError):
        m.WorldState.model_validate(payload)
