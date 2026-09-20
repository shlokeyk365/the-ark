"""Read-only adapter for the existing synthetic first-responder execution path."""

import asyncio
from functools import lru_cache

from .config import ROOT


@lru_cache(maxsize=1)
def responder_demo() -> dict:
    # These models describe a DIFFERENT frozen snapshot from the map. Never
    # blend its identities, people, clocks, or scores into the map state.
    from ark_api.agents.contracts import FixtureProviderConfig, make_request
    from ark_api.agents.providers.fixture import FixtureProposalProvider
    from ark_api.agents.service import AgentProposalService, to_response_plan
    from ark_api.simulation.engine import simulate_plan
    from ark_api.simulation.models import SimulationRequest
    from ark_api.simulation.scoring import score_scenario_result

    scenario = SimulationRequest.model_validate_json(
        (ROOT / "data/scenarios/kantipur-river/nepal_nakkhu_demo_v1.json").read_text(encoding="utf-8")
    )
    provider = FixtureProposalProvider(FixtureProviderConfig(
        fixture_path=ROOT / "apps/api/tests/fixtures/mirofish/interview_success.json",
    ))
    batch = asyncio.run(AgentProposalService([provider]).propose_actions(
        make_request(scenario.world_state, scenario.duration_minutes)
    ))
    result = None
    if batch.proposals:
        result = score_scenario_result(simulate_plan(
            scenario.world_state, to_response_plan(batch), scenario.duration_minutes
        )).model_dump(mode="json")
    return {
        "scope": "Separate synthetic first-responder demo; NOT current map state or live MiroFish output.",
        "scenario_id": scenario.world_state.scenario_id,
        "snapshot_hash": batch.snapshot_hash,
        "provider": batch.provider_type.value,
        "provenance": batch.audit.provenance,
        "input_world": scenario.world_state.model_dump(mode="json"),
        "accepted_proposals": [p.model_dump(mode="json") for p in batch.proposals],
        "rejections": [r.model_dump(mode="json") for r in batch.rejections],
        "result": result,
    }
