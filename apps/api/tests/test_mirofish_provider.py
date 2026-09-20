import asyncio
import json

import httpx
import pytest

from ark_api.agents.contracts import MiroFishProviderConfig, make_request
from ark_api.agents.providers.base import ProviderFailure
from ark_api.agents.providers.mirofish import MiroFishHttpProposalProvider


def config(**changes):
    data = dict(
        base_url="http://mirofish.invalid",
        simulation_id="sim-test",
        platform="twitter",
        responder_agent_mapping={"bus-1": 0},
    )
    data.update(changes)
    return MiroFishProviderConfig(**data)


def document(request):
    return {
        "snapshot_hash": request.snapshot_hash,
        "actions": [
            {
                "action_type": "move",
                "responder_id": "bus-1",
                "target_node_id": "riverside",
                "start_minute": 10,
            }
        ],
    }


def envelope(content):
    return {
        "success": True,
        "data": {
            "success": True,
            "agent_id": 0,
            "result": {"agent_id": 0, "platform": "twitter", "response": content},
        },
    }


def invoke(request, response, configuration=None):
    async def handler(http_request):
        return httpx.Response(200, json=response)

    return asyncio.run(
        MiroFishHttpProposalProvider(
            configuration or config(),
            transport=httpx.MockTransport(handler),
        ).propose_actions(request)
    )


def test_route_shape_and_no_secrets(world_state):
    world_state.metadata = {"api_key": "DO-NOT-SEND"}
    request = make_request(world_state, 60)
    calls = []

    def handler(http_request):
        calls.append(http_request)
        assert (
            str(http_request.url) == "http://mirofish.invalid/api/simulation/interview"
        )
        assert http_request.method == "POST"
        body = json.loads(http_request.content)
        assert set(body) == {
            "simulation_id",
            "agent_id",
            "platform",
            "prompt",
            "timeout",
        }
        assert "DO-NOT-SEND" not in body["prompt"]
        assert "disjoint" in body["prompt"]
        return httpx.Response(200, json=envelope(json.dumps(document(request))))

    result = asyncio.run(
        MiroFishHttpProposalProvider(
            config(),
            transport=httpx.MockTransport(handler),
        ).propose_actions(request)
    )
    assert len(calls) == 1 and len(result.proposals) == 1
    assert result.raw_output is None
    assert "DO-NOT-SEND" not in result.model_dump_json()
    assert result.audit.raw_response_hashes and result.audit.prompt_hashes


@pytest.mark.parametrize("value", [None, 1, {}, [], True])
def test_invalid_response_type(world_state, value):
    with pytest.raises(ProviderFailure) as error:
        invoke(make_request(world_state, 60), envelope(value))
    assert error.value.rejection.error_code == "invalid_envelope"


@pytest.mark.parametrize(
    "value", [{}, {"success": False}, {"success": True, "data": {}}]
)
def test_invalid_envelope(world_state, value):
    with pytest.raises(ProviderFailure) as error:
        invoke(make_request(world_state, 60), value)
    assert error.value.rejection.error_code == "invalid_envelope"


@pytest.mark.parametrize(
    "value", ["bad", "```json\n{}\n```", "Here: {}", "{} trailing"]
)
def test_invalid_json(world_state, value):
    with pytest.raises(ProviderFailure) as error:
        invoke(make_request(world_state, 60), envelope(value))
    assert error.value.rejection.error_code == "invalid_json"


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("action_type", "wait", "unsupported_action"),
        ("responder_id", "ghost", "identity_mismatch"),
        ("target_node_id", "ghost", "unknown_target"),
        ("people_count", 0, "invalid_schema"),
        ("start_minute", -1, "invalid_schema"),
        ("extra", True, "invalid_schema"),
    ],
)
def test_invalid_actions(world_state, field, value, code):
    request = make_request(world_state, 60)
    doc = document(request)
    doc["actions"][0][field] = value
    with pytest.raises(ProviderFailure) as error:
        invoke(request, envelope(json.dumps(doc)))
    assert error.value.rejection.error_code == code


def test_stale_and_limit(world_state):
    request = make_request(world_state, 60)
    for change, code in [
        ({"snapshot_hash": "wrong"}, "stale_snapshot"),
        ({"actions": document(request)["actions"] * 6}, "too_many_actions"),
    ]:
        with pytest.raises(ProviderFailure) as error:
            invoke(request, envelope(json.dumps(document(request) | change)))
        assert error.value.rejection.error_code == code


@pytest.mark.parametrize(
    "exception,code",
    [(httpx.ConnectError, "unavailable"), (httpx.ReadTimeout, "timeout")],
)
def test_transport_failure(world_state, exception, code):
    calls = []

    def handler(request):
        calls.append(request)
        raise exception("secret transport diagnostic")

    with pytest.raises(ProviderFailure) as error:
        asyncio.run(
            MiroFishHttpProposalProvider(
                config(), transport=httpx.MockTransport(handler)
            ).propose_actions(make_request(world_state, 60))
        )
    assert error.value.rejection.error_code == code
    assert "secret" not in str(error.value)
    assert len(calls) == 1


def test_total_deadline(world_state):
    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200)

    with pytest.raises(ProviderFailure) as error:
        asyncio.run(
            MiroFishHttpProposalProvider(
                config(total_timeout=0.02, connect_timeout=0.01),
                transport=httpx.MockTransport(handler),
            ).propose_actions(make_request(world_state, 60))
        )
    assert error.value.rejection.error_code == "timeout"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "http://other"}),
        httpx.Response(200, content=b"x" * 65537),
    ],
)
def test_redirect_and_size(world_state, response):
    calls = []

    def handler(request):
        calls.append(request)
        return response

    with pytest.raises(ProviderFailure):
        asyncio.run(
            MiroFishHttpProposalProvider(
                config(), transport=httpx.MockTransport(handler)
            ).propose_actions(make_request(world_state, 60))
        )
    assert len(calls) == 1


def test_serial_stable_order_and_retention(world_state):
    world_state.responders.append(
        world_state.responders[0].model_copy(update={"id": "bus-2"})
    )
    request = make_request(world_state, 60)
    order = []
    active = False

    async def handler(http_request):
        nonlocal active
        assert not active
        active = True
        body = json.loads(http_request.content)
        order.append(body["agent_id"])
        await asyncio.sleep(0)
        doc = document(request)
        doc["actions"][0]["responder_id"] = {1: "bus-1", 2: "bus-2"}[body["agent_id"]]
        result = envelope(json.dumps(doc))
        result["data"]["agent_id"] = body["agent_id"]
        result["data"]["result"]["agent_id"] = body["agent_id"]
        active = False
        return httpx.Response(200, json=result)

    provider = MiroFishHttpProposalProvider(
        config(
            responder_agent_mapping={"bus-2": 2, "bus-1": 1},
            retain_raw_output=True,
        ),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(provider.propose_actions(request))
    assert order == [1, 2]
    assert len({a.id for a in result.proposals}) == 2
    assert result.raw_output and result.audit.raw_output_retained


def test_unknown_mapping(world_state):
    with pytest.raises(ProviderFailure) as error:
        asyncio.run(
            MiroFishHttpProposalProvider(
                config(responder_agent_mapping={"ghost": 0})
            ).propose_actions(make_request(world_state, 60))
        )
    assert error.value.rejection.error_code == "unknown_responder"
