import asyncio
import json
from pathlib import Path

import httpx
import pytest

from ark_api.agents.contracts import FixtureProviderConfig, make_request
from ark_api.agents.providers.base import ProviderFailure
from ark_api.agents.providers.fixture import FixtureProposalProvider
from ark_api.agents.providers.mirofish import MiroFishHttpProposalProvider
from ark_api.agents.providers.rule_based import RuleBasedProposalProvider
from ark_api.agents.service import AgentProposalService
from ark_api.simulation.models import SimulationRequest
from tests.test_mirofish_provider import config

FIXTURES = Path(__file__).parent / "fixtures/mirofish"
WORLD = (
    Path(__file__).resolve().parents[3]
    / "data/scenarios/kantipur-river/nepal_nakkhu_demo_v1.json"
)


def nepal_request():
    scenario = SimulationRequest.model_validate_json(WORLD.read_text())
    return make_request(scenario.world_state, scenario.duration_minutes)


def fixture(name="interview_success.json"):
    return FixtureProposalProvider(FixtureProviderConfig(fixture_path=FIXTURES / name))


def test_fixture_offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No network permitted")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    request = nepal_request()
    provider = fixture()
    first = asyncio.run(provider.propose_actions(request))
    assert first == asyncio.run(provider.propose_actions(request))
    assert first.audit.provenance == "synthetic"
    assert first.raw_output is None


@pytest.mark.parametrize(
    "name,code",
    [
        ("missing.json", "fixture_missing"),
        ("interview_stale.json", "fixture_mismatch"),
        ("interview_invalid.json", "invalid_schema"),
    ],
)
def test_fixture_failures(name, code):
    with pytest.raises(ProviderFailure) as error:
        asyncio.run(fixture(name).propose_actions(nepal_request()))
    assert error.value.rejection.error_code == code


@pytest.mark.parametrize(
    "change,code",
    [
        ({"responder_id": "ghost"}, "unknown_responder"),
        ({"target_node_id": "ghost"}, "unknown_target"),
        ({"action_type": "wait"}, "unsupported_action"),
        ({"extra": True}, "invalid_schema"),
    ],
)
def test_fixture_actions(tmp_path, change, code):
    data = json.loads((FIXTURES / "interview_success.json").read_text())
    data["actions"][0].update(change)
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ProviderFailure) as error:
        asyncio.run(
            FixtureProposalProvider(
                FixtureProviderConfig(fixture_path=path)
            ).propose_actions(nepal_request())
        )
    assert error.value.rejection.error_code == code


def test_unsafe_fixture():
    result = asyncio.run(
        AgentProposalService([fixture("interview_unsafe.json")]).propose_actions(
            nepal_request()
        )
    )
    assert result.rejections[0].metadata["reason_code"] == "capacity_exceeded"
    assert result.status == "partial"


@pytest.mark.parametrize("failure", ["timeout", "malformed"])
def test_live_fallback(failure):
    request = nepal_request()

    def handler(http_request):
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout")
        return httpx.Response(200, json={})

    live = MiroFishHttpProposalProvider(
        config(responder_agent_mapping={request.world_state.responders[0].id: 0}),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        AgentProposalService(
            [live, fixture(), RuleBasedProposalProvider()]
        ).propose_actions(request)
    )
    assert result.provider_type == "fixture" and result.audit.provenance == "synthetic"
    assert result.audit.fallback_used
    assert result.audit.fallback_origin == "mirofish_http"
    assert result.audit.failures[0].error_code == (
        "timeout" if failure == "timeout" else "invalid_envelope"
    )


def test_missing_to_rule_based():
    service = AgentProposalService(
        [fixture("missing.json"), RuleBasedProposalProvider()]
    )
    first = asyncio.run(service.propose_actions(nepal_request()))
    assert first == asyncio.run(service.propose_actions(nepal_request()))
    assert first.provider_type == "rule_based"
    assert first.audit.fallback_used and first.audit.fallback_origin == "fixture"


def test_exhausted():
    result = asyncio.run(
        AgentProposalService([fixture("missing.json")]).propose_actions(nepal_request())
    )
    assert result.status == "failed"
    assert result.rejections[0].error_code == "fallback_exhausted"


def test_fallback_disabled():
    from ark_api.agents.contracts import AgentProposalServiceConfig

    result = asyncio.run(
        AgentProposalService(
            [fixture("missing.json"), RuleBasedProposalProvider()],
            AgentProposalServiceConfig(fallback_enabled=False),
        ).propose_actions(nepal_request())
    )
    assert result.status == "failed"
    assert not result.audit.fallback_used
    assert result.audit.provenance == "unavailable"


def test_recorded_and_identity(tmp_path):
    data = json.loads((FIXTURES / "interview_success.json").read_text())
    data["provenance"] = "recorded"
    path = tmp_path / "recorded.json"
    path.write_text(json.dumps(data))
    provider = FixtureProposalProvider(
        FixtureProviderConfig(
            fixture_path=path,
            retain_raw_output=True,
        )
    )
    result = asyncio.run(provider.propose_actions(nepal_request()))
    assert result.audit.provenance == "recorded" and result.raw_output
    data["request_id"] = "other"
    path.write_text(json.dumps(data))
    with pytest.raises(ProviderFailure) as error:
        asyncio.run(provider.propose_actions(nepal_request()))
    assert error.value.rejection.error_code == "fixture_mismatch"


def test_unexpected_failure_does_not_mutate_fallback():
    from ark_api.agents.contracts import ProviderType

    class BrokenProvider:
        provider_type = ProviderType.MIROFISH_HTTP

        async def propose_actions(self, request):
            request.world_state.responders.clear()
            raise RuntimeError("secret diagnostic")

    request = nepal_request()
    before = request.model_dump_json()
    result = asyncio.run(
        AgentProposalService([BrokenProvider(), fixture()]).propose_actions(request)
    )
    assert request.model_dump_json() == before
    assert result.provider_type == "fixture"
    assert "secret diagnostic" not in result.model_dump_json()
