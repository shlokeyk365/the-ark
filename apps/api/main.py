"""FastAPI surface for the deterministic Kantipur scenario."""

import os
from pathlib import Path
from typing import Annotated, List, Literal, Optional

from apps.api.models import (
    CopilotRequest,
    CopilotResponse,
    EventRecomputeResponse,
    HealthResponse,
    IntelligenceDecisionRequest,
    IntelligenceDecisionResponse,
    IntelligenceMessageRequest,
    IntelligenceMessageResponse,
    IntelligenceReport,
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
from services.intelligence.copilot import CopilotService
from services.intelligence.config import claude_settings
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
    allow_methods=["GET", "POST", "OPTIONS"],
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
copilot_service = CopilotService(scenario_service, intelligence_service, report_repository)


@app.get("/intelligence/status", tags=["field-intelligence"])
def copilot_status() -> dict:
    key, _ = claude_settings()
    return {"assistant_configured": bool(key)}


@app.post("/intelligence/chat", response_model=CopilotResponse, tags=["field-intelligence"])
def chat(request: CopilotRequest) -> dict:
    try:
        return copilot_service.ask(request)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


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


@app.get(
    "/intelligence/reports",
    response_model=List[IntelligenceReport],
    tags=["field-intelligence"],
)
def list_intelligence_reports() -> list[dict]:
    return intelligence_service.list()


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
