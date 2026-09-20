"""FastAPI surface for the deterministic Kantipur scenario."""

import hashlib
import os
from pathlib import Path
from typing import Annotated, List, Literal, Optional

from apps.api.models import (
    CopilotChatRequest,
    CopilotChatResponse,
    EventRecomputeResponse,
    HealthResponse,
    IntelligenceDecisionRequest,
    IntelligenceDecisionResponse,
    IntelligenceMessageRequest,
    IntelligenceMessageResponse,
    IntelligenceReport,
    MapSummaryRequest,
    MapSummaryResponse,
    ScenarioBootstrapResponse,
    SimulationReport,
    SimulationRun,
    SimulationRunRequest,
    SimulationRunSummary,
    WorldStateSnapshot,
)
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from services.intelligence import FieldIntelligenceService, ReportNotFoundError
from services.intelligence.context import CopilotContextBuilder
from services.intelligence.claude import (
    ClaudeGroundedClient,
    ClaudeNotConfiguredError,
    ClaudeProviderError,
)
from services.reports import ReportRepository, SimulationReportService
from services.scenarios import ScenarioService

app = FastAPI(
    title="the ark API",
    version="0.1.0",
    description="Deterministic flood-response world state and scenario evaluation.",
)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "THE_ARK_CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["DELETE", "GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
scenario_service = ScenarioService()
default_report_database = (
    Path(__file__).resolve().parents[2] / "data" / "runtime" / "the-ark.sqlite3"
)
report_repository = ReportRepository(
    os.getenv("THE_ARK_REPORT_DB_PATH", str(default_report_database))
)
simulation_report_service = SimulationReportService(
    scenario_service, report_repository
)
intelligence_service = FieldIntelligenceService(scenario_service)
copilot_context_builder = CopilotContextBuilder(
    scenario_service, simulation_report_service
)
claude_client = ClaudeGroundedClient()


@app.get("/intelligence/status", tags=["field-intelligence"])
def copilot_status() -> dict:
    return {"assistant_configured": claude_client.configured}


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/scenarios/kantipur-river/bootstrap",
    response_model=ScenarioBootstrapResponse,
    response_model_exclude_none=True,
    tags=["kantipur-river"],
)
def get_bootstrap() -> dict:
    return scenario_service.bootstrap()


@app.get(
    "/scenarios/kantipur-river/baseline",
    response_model=WorldStateSnapshot,
    tags=["kantipur-river"],
)
def get_baseline() -> dict:
    return scenario_service.baseline()


@app.get(
    "/scenarios/kantipur-river/frames/{frame_id}",
    response_model=WorldStateSnapshot,
    tags=["kantipur-river"],
)
def get_frame(
    frame_id: str,
    events: Annotated[
        Optional[List[str]],
        Query(description="Event IDs to hold active while viewing this frame."),
    ] = None,
    intelligence_reports: Annotated[
        Optional[List[str]],
        Query(description="Confirmed field-intelligence report IDs to apply."),
    ] = None,
) -> dict:
    try:
        intelligence_events = intelligence_service.events_for(
            intelligence_reports or []
        )
        return scenario_service.build_world_state(
            frame_id, events or [], intelligence_events
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ReportNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown intelligence report: {error.args[0]}",
        ) from error


@app.post(
    "/intelligence/messages",
    response_model=IntelligenceMessageResponse,
    tags=["field-intelligence"],
)
def ingest_intelligence_message(request: IntelligenceMessageRequest) -> dict:
    try:
        report = intelligence_service.ingest(
            request.message,
            request.source.type,
            request.source.name,
            request.frame_id,
        )
        existing_events = intelligence_service.events_for(
            request.intelligence_report_ids
        )
        tentative_events = intelligence_service.events_for(
            [report.report_id],
            include_probable=True,
        )
        tentative = None
        if tentative_events:
            tentative = scenario_service.build_world_state(
                request.frame_id,
                request.event_ids,
                existing_events + tentative_events,
            )
        return {
            "report": report.as_dict(),
            "baseline_changed": False,
            "tentative_world_state": tentative,
        }
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ReportNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown intelligence report: {error.args[0]}",
        ) from error


def _copilot_answer(
    question: str,
    state: dict,
    provider: str,
    model: Optional[str],
    result: dict,
) -> dict:
    material = "|".join(
        [state["world_state_version"], provider, question, result["answer"]]
    )
    return {
        "answer_id": "answer-" + hashlib.sha256(material.encode()).hexdigest()[:12],
        "provider": provider,
        "model": model,
        "question": question,
        "message": result["answer"],
        "evidence_ids": result["evidence_ids"],
        "source_world_state_version": state["world_state_version"],
        "limitations": result["limitations"],
    }


def _build_tentative_update(
    message: str,
    frame_id: str,
    event_ids: List[str],
    report_ids: List[str],
) -> dict:
    report = intelligence_service.ingest(
        message,
        "operator",
        "Incident Command",
        frame_id,
    )
    existing_events = intelligence_service.events_for(report_ids)
    tentative_events = intelligence_service.events_for(
        [report.report_id],
        include_probable=True,
    )
    tentative = None
    if tentative_events:
        tentative = scenario_service.build_world_state(
            frame_id,
            event_ids,
            existing_events + tentative_events,
        )
    return {
        "mode": "deterministic_update",
        "report": report.as_dict(),
        "baseline_changed": False,
        "tentative_world_state": tentative,
    }


@app.post(
    "/intelligence/chat",
    response_model=CopilotChatResponse,
    tags=["field-intelligence"],
)
def chat_with_incident_copilot(request: CopilotChatRequest) -> dict:
    try:
        intelligence_events = intelligence_service.events_for(
            request.intelligence_report_ids
        )
        state = scenario_service.build_world_state(
            request.frame_id,
            request.event_ids,
            intelligence_events,
        )
        if intelligence_service.is_supported_change(request.message):
            return _build_tentative_update(
                request.message,
                request.frame_id,
                request.event_ids,
                request.intelligence_report_ids,
            )
        deterministic = intelligence_service.answer_map_query(
            request.message, state
        )
        if deterministic:
            return {
                "mode": "deterministic_answer",
                "answer": _copilot_answer(
                    request.message,
                    state,
                    "deterministic",
                    None,
                    deterministic,
                ),
            }
        context, evidence_ids = copilot_context_builder.build(
            state, intelligence_service.list()
        )
        generated = claude_client.answer(
            request.message,
            context,
            evidence_ids,
        )
        return {
            "mode": "claude_answer",
            "answer": _copilot_answer(
                request.message,
                state,
                "claude",
                claude_client.model,
                generated,
            ),
        }
    except ClaudeNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ClaudeProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ReportNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown intelligence report: {error.args[0]}",
        ) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get(
    "/intelligence/reports",
    response_model=List[IntelligenceReport],
    tags=["field-intelligence"],
)
def list_intelligence_reports() -> list[dict]:
    return intelligence_service.list()


@app.post(
    "/intelligence/map-summary",
    response_model=MapSummaryResponse,
    tags=["field-intelligence"],
)
def summarize_current_map(request: MapSummaryRequest) -> dict:
    try:
        intelligence_events = intelligence_service.events_for(
            request.intelligence_report_ids
        )
        state = scenario_service.build_world_state(
            request.frame_id,
            request.event_ids,
            intelligence_events,
        )
        deterministic = intelligence_service.summarize_map(state)
        context, evidence_ids = copilot_context_builder.build(
            state, intelligence_service.list()
        )
        generated = claude_client.briefing(
            context,
            deterministic,
            evidence_ids,
        )
        return {
            **deterministic,
            "headline": generated["headline"],
            "overview": generated["overview"],
            "priorities": generated["priorities"],
            "recommended_plan": generated["recommended_plan"],
            "provider": "claude",
            "model": claude_client.model,
            "evidence_ids": generated["evidence_ids"],
        }
    except ClaudeNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ClaudeProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ReportNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown intelligence report: {error.args[0]}",
        ) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.delete(
    "/intelligence/reports/{report_id}",
    response_model=IntelligenceReport,
    tags=["field-intelligence"],
)
def delete_intelligence_report(report_id: str) -> dict:
    try:
        return intelligence_service.delete(report_id).as_dict()
    except ReportNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown intelligence report: {error.args[0]}",
        ) from error


@app.post(
    "/intelligence/reports/{report_id}/decision",
    response_model=IntelligenceDecisionResponse,
    tags=["field-intelligence"],
)
def decide_intelligence_report(
    report_id: str, request: IntelligenceDecisionRequest
) -> dict:
    try:
        report = intelligence_service.decide(
            report_id, request.decision, request.note
        )
        report_ids = list(request.intelligence_report_ids)
        if request.decision == "confirm" and report_id not in report_ids:
            report_ids.append(report_id)
        confirmed_events = intelligence_service.events_for(report_ids)
        updated = scenario_service.build_world_state(
            request.frame_id,
            request.event_ids,
            confirmed_events,
        )
        return {
            "report": report.as_dict(),
            "baseline_changed": request.decision == "confirm",
            "updated_world_state": updated,
        }
    except ReportNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown intelligence report: {error.args[0]}",
        ) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post(
    "/scenarios/kantipur-river/events/{event_id}",
    response_model=EventRecomputeResponse,
    tags=["kantipur-river"],
)
def apply_event(event_id: str) -> dict:
    try:
        return scenario_service.apply_event(event_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post(
    "/scenarios/kantipur-river/runs",
    response_model=SimulationRun,
    tags=["reports"],
)
def create_simulation_run(request: SimulationRunRequest) -> dict:
    """Evaluate the full frozen horizon and persist exactly one report."""

    try:
        return simulation_report_service.create_run(request.event_ids)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get(
    "/scenarios/kantipur-river/runs",
    response_model=List[SimulationRunSummary],
    tags=["reports"],
)
def list_simulation_runs(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict]:
    return simulation_report_service.list_runs(limit)


@app.get(
    "/scenarios/kantipur-river/runs/{run_id}",
    response_model=SimulationRun,
    tags=["reports"],
)
def get_simulation_run(run_id: str) -> dict:
    run = simulation_report_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id}")
    return run


@app.get(
    "/reports/{report_id}",
    response_model=SimulationReport,
    tags=["reports"],
)
def get_simulation_report(report_id: str) -> dict:
    report = simulation_report_service.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Unknown report_id: {report_id}")
    return report


@app.get("/reports/{report_id}/export", tags=["reports"])
def export_simulation_report(
    report_id: str,
    format: Annotated[Literal["json", "csv", "html"], Query()] = "json",
) -> Response:
    exported = simulation_report_service.export(report_id, format)
    if exported is None:
        raise HTTPException(status_code=404, detail=f"Unknown report_id: {report_id}")
    content, media_type, filename = exported
    disposition = "inline" if format == "html" else "attachment"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )
