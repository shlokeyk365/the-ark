"""FastAPI surface for the deterministic Kantipur scenario."""

import os
from typing import Annotated, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from apps.api.models import (
    EventRecomputeResponse,
    HealthResponse,
    ScenarioBootstrapResponse,
    WorldStateSnapshot,
)
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
) -> dict:
    try:
        return scenario_service.build_world_state(frame_id, events or [])
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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
