"""Contracts for unverified field reports and operator-approved updates."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from ark_api.simulation.models import ContractModel, NonemptyString, WorldState

Score = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class SourceType(StrEnum):
    OPERATOR = "operator"
    FIELD_RESPONDER = "field_responder"
    OFFICIAL = "official"
    PUBLIC = "public"
    UNKNOWN = "unknown"


class ReportStatus(StrEnum):
    POSSIBLE = "possible"
    PROBABLE = "probable"
    CONFIRMED = "confirmed"
    UNRESOLVED = "unresolved"
    DISPUTED = "disputed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class AssetType(StrEnum):
    ROUTE = "route"
    NODE = "node"
    SHELTER = "shelter"
    COMMUNITY = "community"


class ClaimType(StrEnum):
    ROUTE_BLOCKED = "route_blocked"
    ROUTE_FLOODED = "route_flooded"
    FLOOD_OBSERVED = "flood_observed"
    UNKNOWN = "unknown"


class ChangeType(StrEnum):
    CLOSE_ROUTE = "close_route"
    RESTRICT_ROUTE = "restrict_route"
    ADD_FLOOD_HAZARD = "add_flood_hazard"
    NONE = "none"


class OperatorDecision(StrEnum):
    CONFIRM = "confirm"
    KEEP_TENTATIVE = "keep_tentative"
    REJECT = "reject"


class MessageSource(ContractModel):
    type: SourceType = SourceType.UNKNOWN
    name: NonemptyString
    channel: NonemptyString | None = None
    reliability: Score | None = None


class EvidenceScores(ContractModel):
    source_reliability: Score
    extraction_confidence: Score
    location_confidence: Score
    corroboration: Score = 0.0
    freshness: Score = 1.0
    physical_plausibility: Score
    operational_impact: Score


class AssetMatch(ContractModel):
    asset_type: AssetType
    asset_id: NonemptyString
    display_name: NonemptyString
    confidence: Score


class ExtractedClaim(ContractModel):
    claim_type: ClaimType
    summary: NonemptyString
    asset_match: AssetMatch | None = None
    water_depth_m: (
        Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)] | None
    ) = None
    trend: NonemptyString | None = None


class ProposedStateChange(ContractModel):
    change_type: ChangeType
    target_id: NonemptyString | None = None
    reason: NonemptyString


class FieldMessageRequest(ContractModel):
    message: NonemptyString
    source: MessageSource
    world_state: WorldState
    reported_minute: Annotated[int, Field(strict=True, ge=0)] | None = None


class IntelligenceReport(ContractModel):
    id: NonemptyString
    scenario_id: NonemptyString
    original_message: NonemptyString
    source: MessageSource
    reported_minute: Annotated[int, Field(strict=True, ge=0)]
    status: ReportStatus
    claim: ExtractedClaim
    scores: EvidenceScores
    proposed_change: ProposedStateChange
    verification_priority: Score
    requires_operator_confirmation: Annotated[bool, Field(strict=True)] = True
    decision_note: NonemptyString | None = None


class FieldMessageResponse(ContractModel):
    report: IntelligenceReport
    baseline_changed: Annotated[bool, Field(strict=True)] = False
    tentative_world_state: WorldState | None = None
    explanation: NonemptyString


class IntelligenceDecisionRequest(ContractModel):
    decision: OperatorDecision
    world_state: WorldState
    note: NonemptyString | None = None


class IntelligenceDecisionResponse(ContractModel):
    report: IntelligenceReport
    world_state: WorldState
    baseline_changed: Annotated[bool, Field(strict=True)]
