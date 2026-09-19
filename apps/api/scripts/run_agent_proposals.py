"""Offline synthetic proposals by default; live interviews require --live."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from ark_api.agents.contracts import (
    FixtureProviderConfig,
    MiroFishProviderConfig,
    make_request,
)
from ark_api.agents.providers.fixture import FixtureProposalProvider
from ark_api.agents.providers.mirofish import MiroFishHttpProposalProvider
from ark_api.agents.providers.rule_based import RuleBasedProposalProvider
from ark_api.agents.service import AgentProposalService, to_response_plan
from ark_api.simulation.engine import simulate_plan
from ark_api.simulation.models import SimulationRequest
from ark_api.simulation.scoring import score_scenario_result

ROOT = Path(__file__).resolve().parents[3]
WORLD = ROOT / "data/scenarios/kantipur-river/nepal_nakkhu_demo_v1.json"
FIXTURE = ROOT / "apps/api/tests/fixtures/mirofish/interview_success.json"


async def run(live=False):
    scenario = SimulationRequest.model_validate_json(WORLD.read_text(encoding="utf-8"))
    request = make_request(scenario.world_state, scenario.duration_minutes)
    providers = [
        FixtureProposalProvider(FixtureProviderConfig(fixture_path=FIXTURE)),
        RuleBasedProposalProvider(),
    ]
    if live:
        providers.insert(
            0,
            MiroFishHttpProposalProvider(
                MiroFishProviderConfig(
                    base_url=os.environ["ARK_MIROFISH_BASE_URL"],
                    simulation_id=os.environ["ARK_MIROFISH_SIMULATION_ID"],
                    platform=os.environ["ARK_MIROFISH_PLATFORM"],
                    responder_agent_mapping=json.loads(
                        os.environ["ARK_MIROFISH_AGENT_MAPPING"]
                    ),
                )
            ),
        )
    batch = await AgentProposalService(providers).propose_actions(request)
    output = {
        "provider": batch.provider_type,
        "provenance": batch.audit.provenance,
        "snapshot_hash": batch.snapshot_hash,
        "accepted_proposals": [a.model_dump(mode="json") for a in batch.proposals],
        "rejections": [r.model_dump(mode="json") for r in batch.rejections],
        "audit": batch.audit.model_dump(mode="json"),
    }
    if batch.proposals:
        result = score_scenario_result(
            simulate_plan(
                scenario.world_state,
                to_response_plan(batch),
                scenario.duration_minutes,
            )
        )
        output.update(
            metrics=result.metrics.model_dump(),
            viable=result.viable,
            score=result.score,
        )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if batch.proposals else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Attempt configured MiroFish"
    )
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.live))
    except (ValueError, KeyError, OSError):
        print("Agent demo failed: invalid configuration or unavailable input.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
