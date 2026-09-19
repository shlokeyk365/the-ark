"""Synchronous HTTP boundary for the deterministic response-simulation pipeline."""

import logging
from enum import StrEnum

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError

from ark_api.simulation.engine import simulate_plan
from ark_api.simulation.models import (
    ContractModel,
    PlanStatus,
    SimulationRequest,
    SimulationResponse,
)
from ark_api.simulation.plans import generate_candidate_plans
from ark_api.simulation.scoring import rank_scenario_results, recommend_plan_id

MODEL_VERSION = "ark-response-simulator/0.1.0"
DISCLAIMER = (
    "Ark provides experimental decision support. Results depend on supplied data, "
    "assumptions, and simplified simulation rules. Human incident command retains "
    "operational authority."
)
MAX_DURATION_MINUTES = 1440
MAX_SUBMITTED_PLANS = 20
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["simulations"])


class ErrorCode(StrEnum):
    EMPTY_PLANS = "EMPTY_PLANS"
    DUPLICATE_PLAN_ID = "DUPLICATE_PLAN_ID"
    TOO_MANY_PLANS = "TOO_MANY_PLANS"
    PLAN_NOT_READY = "PLAN_NOT_READY"
    DURATION_LIMIT_EXCEEDED = "DURATION_LIMIT_EXCEEDED"
    DOMAIN_VALIDATION_FAILED = "DOMAIN_VALIDATION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(ContractModel):
    code: ErrorCode
    message: str
    details: dict[str, int] = Field(default_factory=dict)


class ErrorResponse(ContractModel):
    error: ErrorDetail


class SimulationClientError(ValueError):
    def __init__(self, code: ErrorCode, message: str, **details: int):
        super().__init__(message)
        self.body = ErrorResponse(
            error=ErrorDetail(code=code, message=message, details=details)
        )


def run_response_simulation(request: SimulationRequest) -> SimulationResponse:
    """Orchestrate existing domain functions; random_seed is reserved, unused."""
    if request.duration_minutes > MAX_DURATION_MINUTES:
        raise SimulationClientError(
            ErrorCode.DURATION_LIMIT_EXCEEDED,
            "Duration exceeds the synchronous limit.",
            max_duration_minutes=MAX_DURATION_MINUTES,
        )
    plans = request.plans
    if plans is not None:
        if not plans:
            raise SimulationClientError(
                ErrorCode.EMPTY_PLANS, "Submitted plans must not be empty."
            )
        if len(plans) > MAX_SUBMITTED_PLANS:
            raise SimulationClientError(
                ErrorCode.TOO_MANY_PLANS,
                "Too many submitted plans.",
                max_plans=MAX_SUBMITTED_PLANS,
            )
        if len({plan.id for plan in plans}) != len(plans):
            raise SimulationClientError(
                ErrorCode.DUPLICATE_PLAN_ID, "Plan IDs must be unique."
            )
        if any(plan.status != PlanStatus.READY for plan in plans):
            raise SimulationClientError(
                ErrorCode.PLAN_NOT_READY, "Submitted plans must have ready status."
            )
    else:
        try:
            plans = generate_candidate_plans(request.world_state)
        except ValidationError:
            # Invalid internally generated contracts are programming errors.
            raise
        except ValueError as error:
            raise SimulationClientError(
                ErrorCode.DOMAIN_VALIDATION_FAILED,
                "The supplied scenario could not be planned.",
            ) from error
    # simulate_plan owns deep isolation of each world and plan; no duplicate logic.
    results = [
        simulate_plan(request.world_state, plan, request.duration_minutes)
        for plan in plans
    ]
    try:
        # Ranking scores each result with the default policy before sorting.
        ranked = rank_scenario_results(results)
        recommended = recommend_plan_id(ranked)
    except ValidationError:
        raise
    except ValueError as error:
        raise SimulationClientError(
            ErrorCode.DOMAIN_VALIDATION_FAILED,
            "The scenario results could not be ranked.",
        ) from error
    return SimulationResponse(
        recommended_plan_id=recommended,
        results=ranked,
        disclaimer=DISCLAIMER,
        model_version=MODEL_VERSION,
    )


@router.post(
    "/simulate-response",
    response_model=SimulationResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def simulate_response(request: SimulationRequest):
    try:
        return run_response_simulation(request)
    except SimulationClientError as error:
        return JSONResponse(status_code=400, content=error.body.model_dump(mode="json"))
    except Exception:
        # Broad handling is confined to the HTTP boundary, never the domain layer.
        logger.exception("Unexpected response-simulation failure")
        error = ErrorResponse(
            error=ErrorDetail(
                code=ErrorCode.INTERNAL_ERROR,
                message="The simulation could not be completed.",
            )
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))
