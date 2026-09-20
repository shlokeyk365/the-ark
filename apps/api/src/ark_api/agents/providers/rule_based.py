from ark_api.agents.contracts import ProviderType, RuleBasedProviderConfig
from ark_api.agents.providers.base import batch
from ark_api.simulation.plans import generate_candidate_plans


class RuleBasedProposalProvider:
    provider_type = ProviderType.RULE_BASED

    def __init__(self, config: RuleBasedProviderConfig | None = None):
        self.config = config or RuleBasedProviderConfig()

    async def propose_actions(self, request):
        plan = next(
            p
            for p in generate_candidate_plans(request.world_state)
            if p.id == self.config.strategy
        )
        result = batch(request, self.provider_type, self.config, "rule_based")
        result.proposals = [
            a
            for a in plan.actions
            if a.action_type in request.allowed_action_types
            and (
                request.responder_ids is None or a.responder_id in request.responder_ids
            )
        ][: request.maximum_actions]
        result.audit.proposal_count = len(result.proposals)
        return result
