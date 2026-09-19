import pytest
from pydantic import ValidationError

from ark_api.agents.contracts import (
    MiroFishProviderConfig,
    ProposalRequest,
    make_request,
    snapshot_hash,
)


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": 1},
        {"allowed_action_types": ["wait"]},
        {"allowed_action_types": []},
        {"maximum_actions": 0},
        {"maximum_actions": 11},
        {"maximum_actions": True},
        {"horizon_minutes": 0},
        {"snapshot_hash": ""},
        {"responder_ids": ["bus-1", "bus-1"]},
        {"base_url": "http://attacker"},
        {"simulation_minute": 11},
    ],
)
def test_invalid_request(world_state, change):
    data = make_request(world_state, 60).model_dump()
    data.update(change)
    with pytest.raises(ValidationError):
        ProposalRequest.model_validate(data)


def test_canonical_hash(world_state):
    request = make_request(world_state, 60)
    other = make_request(world_state, 60, request_id="different")
    assert snapshot_hash(request) == snapshot_hash(other)
    data = world_state.model_dump()
    data = dict(reversed(list(data.items())))
    other.world_state = type(world_state).model_validate(data)
    assert snapshot_hash(request) == snapshot_hash(other)
    other.world_state.metadata = {"secret": "excluded", "timestamp": "now"}
    assert snapshot_hash(request) == snapshot_hash(other)
    other.world_state.responders[0].capacity += 1
    assert snapshot_hash(request) != snapshot_hash(other)


@pytest.mark.parametrize(
    "url",
    [
        "http://user:secret@localhost",
        "file:///tmp",
        "https://localhost/?key=secret",
        "http://localhost/#fragment",
        "http://localhost/path",
    ],
)
def test_unsafe_config_url(url):
    with pytest.raises(ValidationError):
        MiroFishProviderConfig(
            base_url=url,
            simulation_id="sim",
            platform="twitter",
            responder_agent_mapping={"bus-1": 0},
        )
