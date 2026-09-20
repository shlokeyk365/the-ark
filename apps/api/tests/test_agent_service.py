import asyncio
from pathlib import Path

import pytest

from ark_api.agents.contracts import (
    AgentProposalServiceConfig,
    ProviderType,
    RuleBasedProviderConfig,
    make_request,
)
from ark_api.agents.providers.base import batch
from ark_api.agents.providers.rule_based import RuleBasedProposalProvider
from ark_api.agents.service import AgentProposalService, to_response_plan
from ark_api.simulation.models import ActionType
from ark_api.simulation.plans import generate_candidate_plans


class StaticProvider:
    provider_type = ProviderType.RULE_BASED

    def __init__(self, actions):
        self.actions = actions

    async def propose_actions(self, request):
        result = batch(request, self.provider_type, {}, "rule_based")
        result.proposals = self.actions
        return result


def admit(world, actions):
    request = make_request(world, 60)
    before = request.model_dump_json()
    result = asyncio.run(
        AgentProposalService(
            [StaticProvider(actions)],
            AgentProposalServiceConfig(fallback_on_zero_accepted=False),
        ).propose_actions(request)
    )
    assert request.model_dump_json() == before
    return result


@pytest.mark.parametrize(
    "strategy",
    [
        "immediate-rescue",
        "balanced-response",
        "preventive-evacuation",
    ],
)
def test_wraps_planner(simulation_world, strategy):
    request = make_request(simulation_world, 60, maximum_actions=1)
    provider = RuleBasedProposalProvider(RuleBasedProviderConfig(strategy=strategy))
    first = asyncio.run(provider.propose_actions(request))
    second = asyncio.run(provider.propose_actions(request))
    expected = next(
        p for p in generate_candidate_plans(simulation_world) if p.id == strategy
    )
    assert first.proposals == expected.actions[:1]
    assert first == second


def test_overlap_and_no_execution(simulation_world, make_action, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Service must not execute or score")

    monkeypatch.setattr("ark_api.simulation.engine.simulate_plan", forbidden)
    monkeypatch.setattr("ark_api.simulation.scoring.score_scenario_result", forbidden)
    first = make_action()
    second = make_action(id="second", start_minute=20)
    result = admit(simulation_world, [first, second])
    assert result.proposals == [first]
    assert result.rejections[0].metadata["reason_code"] == "overlapping_assignment"
    assert to_response_plan(result).actions == [first]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"people_count": 21}, "capacity_exceeded"),
        ({"target_node_id": "missing"}, "target_not_found"),
        ({"responder_id": "missing"}, "responder_not_found"),
    ],
)
def test_invalid_action(simulation_world, make_action, change, reason):
    values = dict(
        action_type=ActionType.EVACUATE,
        community_id="community-1",
        shelter_id="shelter-1",
        people_count=10,
    )
    values.update(change)
    result = admit(simulation_world, [make_action(**values)])
    assert result.rejections[0].metadata["reason_code"] == reason


@pytest.mark.parametrize("closure", [10, 12])
def test_closed_or_closing_route(simulation_world, make_action, closure):
    simulation_world.routes[0].closure_minute = closure
    result = admit(simulation_world, [make_action()])
    assert result.rejections[0].metadata["reason_code"] == "no_route"


@pytest.mark.parametrize(
    "population,shelter,reason",
    [
        (10, 40, "people_unavailable"),
        (20, 10, "shelter_capacity_exceeded"),
    ],
)
def test_reservations(simulation_world, make_action, population, shelter, reason):
    world = simulation_world
    world.responders.append(world.responders[0].model_copy(update={"id": "bus-2"}))
    world.communities[0].population = population
    world.shelters[0].capacity = shelter
    values = dict(
        action_type=ActionType.EVACUATE,
        community_id="community-1",
        shelter_id="shelter-1",
        people_count=10,
    )
    result = admit(
        world,
        [
            make_action(**values),
            make_action(id="second", responder_id="bus-2", **values),
        ],
    )
    assert len(result.proposals) == 1
    assert result.rejections[0].metadata["reason_code"] == reason


def test_nepal_offline_repeat():
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts/run_agent_proposals.py"
    outputs = [
        subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True, check=True
        ).stdout
        for _ in range(2)
    ]
    assert outputs[0] == outputs[1]
    assert '"provenance": "synthetic"' in outputs[0]
    assert '"provider": "fixture"' in outputs[0]
    assert '"score":' in outputs[0]


def test_capability_rejection(world_state, make_action):
    action = make_action(
        action_type=ActionType.RESCUE, request_id="call-1", people_count=1
    )
    result = admit(world_state, [action])
    assert result.rejections[0].metadata["reason_code"] == "missing_capability"


def test_rescue_population_reserved(simulation_world, make_action):
    simulation_world.responders.append(
        simulation_world.responders[0].model_copy(update={"id": "bus-2"})
    )
    values = dict(action_type=ActionType.RESCUE, request_id="call-1", people_count=5)
    result = admit(
        simulation_world,
        [
            make_action(**values),
            make_action(id="second", responder_id="bus-2", **values),
        ],
    )
    assert len(result.proposals) == 1
    assert result.rejections[0].metadata["reason_code"] == "people_unavailable"


@pytest.mark.parametrize(
    "field,value", [("request_id", "other"), ("snapshot_hash", "stale")]
)
def test_batch_identity(simulation_world, make_action, field, value):
    class WrongIdentity(StaticProvider):
        async def propose_actions(self, request):
            result = await super().propose_actions(request)
            setattr(result, field, value)
            return result

    result = asyncio.run(
        AgentProposalService([WrongIdentity([make_action()])]).propose_actions(
            make_request(simulation_world, 60)
        )
    )
    assert result.status == "failed"
    assert result.audit.failures[0].error_code in {
        "identity_mismatch",
        "stale_snapshot",
    }
