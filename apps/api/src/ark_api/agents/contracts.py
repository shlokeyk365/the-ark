"""Bounded proposal contracts; no provider is a source of physical truth."""

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, JsonValue, field_validator, model_validator

from ark_api.simulation.models import (
    ActionType,
    ContractModel,
    NonemptyString,
    NonnegativeInt,
    PlanAction,
    PositiveInt,
    WorldState,
)

UPSTREAM_COMMIT = "39d849138ef254f6c737ab4c4705e5545dbe31d4"
SUPPORTED = {ActionType.MOVE, ActionType.RESCUE, ActionType.EVACUATE}
ActionLimit = Annotated[int, Field(strict=True, ge=1, le=10)]
StrictBool = Annotated[bool, Field(strict=True)]


class ProviderType(StrEnum):
    RULE_BASED = "rule_based"
    FIXTURE = "fixture"
    MIROFISH_HTTP = "mirofish_http"


class ProviderErrorCode(StrEnum):
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INVALID_ENVELOPE = "invalid_envelope"
    INVALID_JSON = "invalid_json"
    INVALID_SCHEMA = "invalid_schema"
    STALE_SNAPSHOT = "stale_snapshot"
    IDENTITY_MISMATCH = "identity_mismatch"
    UNKNOWN_RESPONDER = "unknown_responder"
    UNKNOWN_TARGET = "unknown_target"
    UNSUPPORTED_ACTION = "unsupported_action"
    TOO_MANY_ACTIONS = "too_many_actions"
    UNSAFE_PROPOSAL = "unsafe_proposal"
    FIXTURE_MISSING = "fixture_missing"
    FIXTURE_MISMATCH = "fixture_mismatch"
    FALLBACK_EXHAUSTED = "fallback_exhausted"


class ProposalRequest(ContractModel):
    request_id: NonemptyString
    snapshot_hash: NonemptyString
    world_state: WorldState
    simulation_minute: NonnegativeInt
    horizon_minutes: PositiveInt
    allowed_action_types: list[ActionType] = Field(
        default_factory=lambda: sorted(SUPPORTED)
    )
    maximum_actions: ActionLimit = 5
    objectives: list[NonemptyString] = Field(default_factory=list)
    responder_ids: list[NonemptyString] | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("allowed_action_types")
    @classmethod
    def allowlist(cls, value):
        if not value or not set(value) <= SUPPORTED or len(value) != len(set(value)):
            raise ValueError("Require unique implemented actions")
        return value

    @field_validator("responder_ids")
    @classmethod
    def unique_responders(cls, value):
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Responder IDs must be unique")
        return value

    @model_validator(mode="after")
    def frozen_time(self):
        if self.simulation_minute != self.world_state.current_minute:
            raise ValueError("Proposal minute must match the frozen world")
        return self


def canonical(value):
    if hasattr(value, "model_dump"):
        return canonical(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        return sorted(canonical(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    return value


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(
            canonical(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def snapshot_hash(request: ProposalRequest) -> str:
    world = request.world_state.model_dump(mode="python", exclude={"metadata"})
    return fingerprint(
        {
            "version": 1,
            "world": world,
            "minute": request.simulation_minute,
            "horizon": request.horizon_minutes,
            "allowed": sorted(request.allowed_action_types),
            "maximum_actions": request.maximum_actions,
            "objectives": request.objectives,
            "responders": sorted(request.responder_ids)
            if request.responder_ids is not None
            else None,
        }
    )


def make_request(world: WorldState, horizon_minutes: int, **kwargs) -> ProposalRequest:
    request = ProposalRequest(
        request_id=kwargs.pop("request_id", "agent-proposals"),
        snapshot_hash="pending",
        world_state=world.model_copy(deep=True),
        simulation_minute=world.current_minute,
        horizon_minutes=horizon_minutes,
        **kwargs,
    )
    return request.model_copy(update={"snapshot_hash": snapshot_hash(request)})


class ProposalRejection(ContractModel):
    source_index: NonnegativeInt | None = None
    responder_id: NonemptyString | None = None
    error_code: ProviderErrorCode
    message: NonemptyString
    raw_fragment: Annotated[str, Field(strict=True, max_length=256)] | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ProviderAudit(ContractModel):
    provider_type: ProviderType
    provider_version: NonemptyString = "ark-agents/0.1.0"
    request_id: NonemptyString
    snapshot_hash: NonemptyString
    upstream_commit: str | None = None
    configuration_hash: NonemptyString
    prompt_hashes: list[str] = Field(default_factory=list)
    raw_response_hashes: list[str] = Field(default_factory=list)
    raw_output_retained: StrictBool = False
    fallback_used: StrictBool = False
    fallback_origin: ProviderType | None = None
    proposal_count: NonnegativeInt = 0
    accepted_count: NonnegativeInt = 0
    rejected_count: NonnegativeInt = 0
    simulation_id: str | None = None
    platform: str | None = None
    agent_ids: list[NonnegativeInt] = Field(default_factory=list)
    provenance: Literal["live", "recorded", "synthetic", "rule_based", "unavailable"]
    failures: list[ProposalRejection] = Field(default_factory=list)


class ProposalBatch(ContractModel):
    request_id: NonemptyString
    provider_type: ProviderType
    snapshot_hash: NonemptyString
    proposals: list[PlanAction] = Field(default_factory=list)
    rejections: list[ProposalRejection] = Field(default_factory=list)
    audit: ProviderAudit
    raw_output: str | None = None
    status: Literal["proposed", "accepted", "partial", "failed"] = "proposed"


class RuleBasedProviderConfig(ContractModel):
    strategy: Literal[
        "immediate-rescue", "balanced-response", "preventive-evacuation"
    ] = "balanced-response"


class FixtureProviderConfig(ContractModel):
    fixture_path: Path
    expected_request_id: str | None = None
    expected_scenario_id: str | None = None
    retain_raw_output: StrictBool = False


class MiroFishProviderConfig(ContractModel):
    base_url: NonemptyString
    expected_upstream_commit: Literal[UPSTREAM_COMMIT] = UPSTREAM_COMMIT
    simulation_id: NonemptyString
    platform: Literal["twitter", "reddit"]
    responder_agent_mapping: dict[NonemptyString, NonnegativeInt]
    connect_timeout: Annotated[float, Field(strict=True, gt=0, le=20)] = 2.0
    total_timeout: Annotated[float, Field(strict=True, gt=0, le=120)] = 20.0
    maximum_agents: ActionLimit = 5
    maximum_actions: ActionLimit = 5
    maximum_response_bytes: Annotated[int, Field(strict=True, ge=256, le=1048576)] = (
        65536
    )
    maximum_prompt_bytes: Annotated[int, Field(strict=True, ge=256, le=262144)] = 65536
    retain_raw_output: StrictBool = False
    model_label: NonemptyString | None = None
    fallback_enabled: StrictBool = True

    @field_validator("base_url")
    @classmethod
    def trusted_url(cls, value):
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("Require an HTTP(S) origin without credentials")
        return value.rstrip("/")

    @model_validator(mode="after")
    def bounded_mapping(self):
        values = list(self.responder_agent_mapping.values())
        if (
            not values
            or len(values) > self.maximum_agents
            or len(set(values)) != len(values)
        ):
            raise ValueError("Require a bounded one-to-one agent mapping")
        if self.connect_timeout > self.total_timeout:
            raise ValueError("Connect timeout exceeds batch timeout")
        return self


class AgentProposalServiceConfig(ContractModel):
    fallback_enabled: StrictBool = True
    fallback_on_zero_accepted: StrictBool = True


class ProposedAction(ContractModel):
    action_type: ActionType
    responder_id: NonemptyString
    target_node_id: NonemptyString
    start_minute: NonnegativeInt
    people_count: PositiveInt | None = None
    request_id: NonemptyString | None = None
    community_id: NonemptyString | None = None
    shelter_id: NonemptyString | None = None


class ProposalDocument(ContractModel):
    snapshot_hash: NonemptyString
    actions: list[ProposedAction]


class FixtureDocument(ProposalDocument):
    provenance: Literal["recorded", "synthetic"]
    scenario_id: NonemptyString
    request_id: NonemptyString | None = None
