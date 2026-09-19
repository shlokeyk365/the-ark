"""Run a no-network field-intelligence demonstration against the Nepal fixture."""

import json
from pathlib import Path

from ark_api.intelligence.models import (
    FieldMessageRequest,
    MessageSource,
    OperatorDecision,
    SourceType,
)
from ark_api.intelligence.service import FieldIntelligenceService
from ark_api.simulation.models import SimulationRequest

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = (
    ROOT / "data/scenarios/kantipur-river/nepal_nakkhu_demo_v1.json"
)


def main() -> None:
    simulation_request = SimulationRequest.model_validate_json(
        FIXTURE.read_text(encoding="utf-8")
    )
    world = simulation_request.world_state
    service = FieldIntelligenceService()
    intake = service.ingest(
        FieldMessageRequest(
            message=(
                "Rescue 4 reports road-staging-nakhipot is under two feet of "
                "water. Vehicles cannot pass and the water is rising."
            ),
            source=MessageSource(
                type=SourceType.FIELD_RESPONDER,
                name="Rescue 4",
                channel="radio",
            ),
            world_state=world,
        )
    )
    report = intake.report
    tentative_route = next(
        route
        for route in intake.tentative_world_state.routes
        if route.id == report.proposed_change.target_id
    )
    confirmed, confirmed_world, changed = service.decide(
        report.id,
        OperatorDecision.CONFIRM,
        world,
        "Confirmed by incident command.",
    )
    confirmed_route = next(
        route
        for route in confirmed_world.routes
        if route.id == confirmed.proposed_change.target_id
    )
    print(
        json.dumps(
            {
                "report": report.model_dump(mode="json"),
                "baseline_changed_on_ingest": intake.baseline_changed,
                "tentative_route_status": tentative_route.status,
                "operator_confirmed": changed,
                "confirmed_route_status": confirmed_route.status,
                "confirmed_world_revision": confirmed_world.metadata["revision"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
