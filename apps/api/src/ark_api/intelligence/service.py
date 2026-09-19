"""Triage, store, branch, and explicitly promote field intelligence."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from ark_api.intelligence.extractor import extract_field_message
from ark_api.intelligence.models import (
    ChangeType,
    EvidenceScores,
    FieldMessageRequest,
    FieldMessageResponse,
    IntelligenceReport,
    OperatorDecision,
    ReportStatus,
    SourceType,
)
from ark_api.simulation.models import Hazard, HazardType, RouteStatus, WorldState

_DEFAULT_RELIABILITY = {
    SourceType.OFFICIAL: 0.95,
    SourceType.FIELD_RESPONDER: 0.85,
    SourceType.OPERATOR: 0.85,
    SourceType.PUBLIC: 0.45,
    SourceType.UNKNOWN: 0.3,
}


class ReportNotFoundError(KeyError):
    pass


class ScenarioMismatchError(ValueError):
    pass


class InMemoryIntelligenceStore:
    """Hackathon store. Swap for Postgres without changing the service API."""

    def __init__(self) -> None:
        self._reports: dict[str, IntelligenceReport] = {}

    def put(self, report: IntelligenceReport) -> None:
        self._reports[report.id] = report

    def get(self, report_id: str) -> IntelligenceReport:
        try:
            return self._reports[report_id]
        except KeyError as error:
            raise ReportNotFoundError(report_id) from error

    def list(self, scenario_id: str | None = None) -> list[IntelligenceReport]:
        reports: Iterable[IntelligenceReport] = self._reports.values()
        if scenario_id is not None:
            reports = (r for r in reports if r.scenario_id == scenario_id)
        return sorted(reports, key=lambda r: (r.reported_minute, r.id), reverse=True)

    def clear(self) -> None:
        self._reports.clear()


def _report_id(request: FieldMessageRequest, minute: int) -> str:
    material = "|".join(
        [
            request.world_state.scenario_id,
            str(minute),
            request.source.name,
            request.message,
        ]
    )
    return "intel-" + hashlib.sha256(material.encode()).hexdigest()[:12]


def _physical_plausibility(
    request: FieldMessageRequest, target_id: str | None
) -> float:
    if target_id is None:
        return 0.35
    route = next((r for r in request.world_state.routes if r.id == target_id), None)
    if route and (route.closure_minute is not None or route.hazard_reason):
        return 0.9
    if request.world_state.hazards:
        return 0.75
    return 0.55


def _verification_priority(scores: EvidenceScores) -> float:
    credibility = (
        scores.source_reliability
        * scores.extraction_confidence
        * scores.location_confidence
    ) ** (1 / 3)
    return round(min(1.0, credibility * scores.operational_impact * 1.35), 3)


def apply_report_to_world(
    world: WorldState, report: IntelligenceReport
) -> WorldState:
    """Apply one report to a copy. Call only for a branch or confirmed report."""
    updated = world.model_copy(deep=True)
    change = report.proposed_change
    if change.change_type in {ChangeType.CLOSE_ROUTE, ChangeType.RESTRICT_ROUTE}:
        route = next((r for r in updated.routes if r.id == change.target_id), None)
        if route is None:
            raise ValueError(f"Unknown route {change.target_id!r}")
        if change.change_type == ChangeType.CLOSE_ROUTE:
            route.status = RouteStatus.CLOSED
            route.closure_minute = min(
                value
                for value in (route.closure_minute, updated.current_minute)
                if value is not None
            )
        elif route.status == RouteStatus.OPEN:
            route.status = RouteStatus.RESTRICTED
        route.hazard_reason = f"Field intelligence {report.id}: {report.claim.summary}"
    elif change.change_type == ChangeType.ADD_FLOOD_HAZARD:
        node_id = change.target_id
        if node_id is None or not any(n.id == node_id for n in updated.nodes):
            raise ValueError(f"Unknown node {node_id!r}")
        hazard_id = f"hazard-{report.id}"
        if not any(h.id == hazard_id for h in updated.hazards):
            updated.hazards.append(
                Hazard(
                    id=hazard_id,
                    type=HazardType.FLOOD,
                    affected_node_ids=[node_id],
                    start_minute=report.reported_minute,
                    severity=3,
                    source=f"field-intelligence:{report.id}",
                    observed=report.status == ReportStatus.CONFIRMED,
                )
            )
    metadata = dict(updated.metadata)
    ids = list(metadata.get("intelligence_report_ids", []))
    if report.id not in ids:
        ids.append(report.id)
    metadata["intelligence_report_ids"] = ids
    metadata["revision"] = int(metadata.get("revision", 0)) + 1
    updated.metadata = metadata
    return WorldState.model_validate(updated.model_dump(mode="json"))


class FieldIntelligenceService:
    def __init__(self, store: InMemoryIntelligenceStore | None = None) -> None:
        self.store = store or InMemoryIntelligenceStore()

    def ingest(self, request: FieldMessageRequest) -> FieldMessageResponse:
        minute = (
            request.reported_minute
            if request.reported_minute is not None
            else request.world_state.current_minute
        )
        extraction = extract_field_message(request.message, request.world_state)
        match = extraction.claim.asset_match
        source_reliability = (
            request.source.reliability
            if request.source.reliability is not None
            else _DEFAULT_RELIABILITY[request.source.type]
        )
        location_confidence = match.confidence if match else 0.0
        operational_impact = (
            0.9
            if extraction.change.change_type == ChangeType.CLOSE_ROUTE
            else 0.7
            if extraction.change.change_type
            in {ChangeType.RESTRICT_ROUTE, ChangeType.ADD_FLOOD_HAZARD}
            else 0.2
        )
        scores = EvidenceScores(
            source_reliability=source_reliability,
            extraction_confidence=extraction.extraction_confidence,
            location_confidence=location_confidence,
            physical_plausibility=_physical_plausibility(
                request, extraction.change.target_id
            ),
            operational_impact=operational_impact,
        )
        if extraction.change.change_type == ChangeType.NONE or match is None:
            status = ReportStatus.UNRESOLVED
        elif (
            source_reliability >= 0.7
            and extraction.extraction_confidence >= 0.8
            and location_confidence >= 0.7
        ):
            status = ReportStatus.PROBABLE
        else:
            status = ReportStatus.POSSIBLE
        report = IntelligenceReport(
            id=_report_id(request, minute),
            scenario_id=request.world_state.scenario_id,
            original_message=request.message,
            source=request.source,
            reported_minute=minute,
            status=status,
            claim=extraction.claim,
            scores=scores,
            proposed_change=extraction.change,
            verification_priority=_verification_priority(scores),
        )
        self.store.put(report)
        tentative = (
            apply_report_to_world(request.world_state, report)
            if status == ReportStatus.PROBABLE
            else None
        )
        explanation = (
            "The baseline was not changed. Ark created a tentative branch because "
            "the report is credible and operationally relevant."
            if tentative is not None
            else "The baseline was not changed. The report is stored for review."
        )
        return FieldMessageResponse(
            report=report,
            tentative_world_state=tentative,
            explanation=explanation,
        )

    def decide(
        self,
        report_id: str,
        decision: OperatorDecision,
        world: WorldState,
        note: str | None = None,
    ) -> tuple[IntelligenceReport, WorldState, bool]:
        report = self.store.get(report_id)
        if report.scenario_id != world.scenario_id:
            raise ScenarioMismatchError(
                "Report and world state belong to different scenarios"
            )
        if decision == OperatorDecision.CONFIRM:
            report = report.model_copy(
                update={"status": ReportStatus.CONFIRMED, "decision_note": note}
            )
            updated = apply_report_to_world(world, report)
            changed = report.proposed_change.change_type != ChangeType.NONE
        elif decision == OperatorDecision.REJECT:
            report = report.model_copy(
                update={"status": ReportStatus.REJECTED, "decision_note": note}
            )
            updated = world.model_copy(deep=True)
            changed = False
        else:
            report = report.model_copy(update={"decision_note": note})
            updated = world.model_copy(deep=True)
            changed = False
        self.store.put(report)
        return report, updated, changed
