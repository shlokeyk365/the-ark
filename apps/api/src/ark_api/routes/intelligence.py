"""HTTP API for field-message triage and explicit operator decisions."""

from fastapi import APIRouter, HTTPException, Query

from ark_api.intelligence.models import (
    FieldMessageRequest,
    FieldMessageResponse,
    IntelligenceDecisionRequest,
    IntelligenceDecisionResponse,
    IntelligenceReport,
)
from ark_api.intelligence.service import (
    FieldIntelligenceService,
    ReportNotFoundError,
    ScenarioMismatchError,
)

router = APIRouter(prefix="/api/v1/intelligence", tags=["field-intelligence"])
service = FieldIntelligenceService()


@router.post("/messages", response_model=FieldMessageResponse)
def ingest_message(request: FieldMessageRequest) -> FieldMessageResponse:
    return service.ingest(request)


@router.get("/reports", response_model=list[IntelligenceReport])
def list_reports(
    scenario_id: str | None = Query(default=None),
) -> list[IntelligenceReport]:
    return service.store.list(scenario_id)


@router.get("/reports/{report_id}", response_model=IntelligenceReport)
def get_report(report_id: str) -> IntelligenceReport:
    try:
        return service.store.get(report_id)
    except ReportNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="Intelligence report not found"
        ) from error


@router.post(
    "/reports/{report_id}/decision", response_model=IntelligenceDecisionResponse
)
def decide_report(
    report_id: str, request: IntelligenceDecisionRequest
) -> IntelligenceDecisionResponse:
    try:
        report, world, changed = service.decide(
            report_id, request.decision, request.world_state, request.note
        )
    except ReportNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="Intelligence report not found"
        ) from error
    except ScenarioMismatchError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return IntelligenceDecisionResponse(
        report=report, world_state=world, baseline_changed=changed
    )
