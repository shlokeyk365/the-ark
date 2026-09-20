"""Planning admission only; never calls execution or scoring."""

from pydantic import ValidationError

from ark_api.agents.contracts import (
    AgentProposalServiceConfig,
    ProposalBatch,
    ProposalRejection,
    ProviderErrorCode,
    snapshot_hash,
)
from ark_api.agents.providers.base import ProposalProvider, ProviderFailure, batch
from ark_api.simulation.models import ActionType, PlanStatus, ResponsePlan
from ark_api.simulation.validation import ExecutionState, validate_action


class AgentProposalService:
    def __init__(self, providers: list[ProposalProvider], config=None):
        if not providers:
            raise ValueError("At least one provider is required")
        self.providers = providers
        self.config = config or AgentProposalServiceConfig()

    def validate(self, request, result):
        if (
            result.request_id != request.request_id
            or result.audit.request_id != request.request_id
        ):
            raise ProviderFailure(
                ProviderErrorCode.IDENTITY_MISMATCH, "Request identity mismatch."
            )
        if (
            result.snapshot_hash != request.snapshot_hash
            or result.audit.snapshot_hash != request.snapshot_hash
        ):
            raise ProviderFailure(
                ProviderErrorCode.STALE_SNAPSHOT, "Snapshot mismatch."
            )
        if len(result.proposals) > request.maximum_actions:
            raise ProviderFailure(
                ProviderErrorCode.TOO_MANY_ACTIONS, "Action limit exceeded."
            )
        state = ExecutionState.from_world(request.world_state)
        accepted = []
        seen_ids = set()
        for index, action in enumerate(result.proposals):
            code = None
            reason = None
            if action.action_type not in request.allowed_action_types:
                code = ProviderErrorCode.UNSUPPORTED_ACTION
            elif (
                request.responder_ids is not None
                and action.responder_id not in request.responder_ids
            ):
                code = ProviderErrorCode.UNKNOWN_RESPONDER
            elif (
                action.start_minute
                >= request.simulation_minute + request.horizon_minutes
                or action.id in seen_ids
            ):
                code = ProviderErrorCode.UNSAFE_PROPOSAL
            else:
                validation = validate_action(state, action, action.start_minute)
                if not validation.accepted:
                    code = ProviderErrorCode.UNSAFE_PROPOSAL
                    reason = validation.reason_code.value
            seen_ids.add(action.id)
            if code is not None:
                result.rejections.append(
                    ProposalRejection(
                        source_index=index,
                        responder_id=action.responder_id,
                        error_code=code,
                        message="Proposal rejected at planning admission.",
                        metadata={"reason_code": reason} if reason else {},
                    )
                )
                continue
            accepted.append(action)
            state.responders[action.responder_id].assignment_id = action.id
            # Conservative one assignment per responder; reserve populations until
            # execution. Do not predict completions or relocate responders here.
            count = action.people_count or 0
            reservations = []
            if action.action_type == ActionType.RESCUE:
                reservations.append((state.request_reserved, action.request_id))
            elif action.action_type == ActionType.EVACUATE:
                reservations.extend(
                    (
                        (state.community_reserved, action.community_id),
                        (state.shelter_reserved, action.shelter_id),
                    )
                )
            for ledger, key in reservations:
                ledger[key] = ledger.get(key, 0) + count
        result.audit.proposal_count = len(result.proposals)
        result.proposals = accepted
        result.audit.accepted_count = len(accepted)
        result.audit.rejected_count = len(result.rejections)
        result.status = (
            ("partial" if result.rejections else "accepted") if accepted else "failed"
        )
        return result

    async def propose_actions(self, request):
        if snapshot_hash(request) != request.snapshot_hash:
            raise ProviderFailure(
                ProviderErrorCode.STALE_SNAPSHOT, "Request snapshot hash is invalid."
            )
        failures = []
        origin = self.providers[0].provider_type
        for _attempt, provider in enumerate(self.providers):
            try:
                # Each provider gets a private copy; fallback sees the same snapshot.
                candidate = await provider.propose_actions(
                    request.model_copy(deep=True)
                )
                result = ProposalBatch.model_validate(candidate.model_dump())
                if (
                    result.provider_type != provider.provider_type
                    or result.audit.provider_type != provider.provider_type
                ):
                    raise ProviderFailure(
                        ProviderErrorCode.IDENTITY_MISMATCH,
                        "Provider identity mismatch.",
                    )
                result = self.validate(request, result)
                if result.proposals or not self.config.fallback_on_zero_accepted:
                    result.audit.fallback_used = bool(failures)
                    result.audit.fallback_origin = origin if failures else None
                    result.audit.failures = failures
                    return result
                failures.extend(
                    result.rejections
                    or [
                        ProposalRejection(
                            error_code=ProviderErrorCode.UNSAFE_PROPOSAL,
                            message="Provider returned no accepted proposals.",
                        )
                    ]
                )
            except ProviderFailure as error:
                error.rejection.metadata["provider_type"] = provider.provider_type.value
                failures.append(error.rejection)
            except ValidationError:
                failures.append(
                    ProposalRejection(
                        error_code=ProviderErrorCode.INVALID_SCHEMA,
                        message="Provider returned an invalid batch.",
                    )
                )
            except Exception:
                # Provider boundary: preserve baseline availability without exposing
                # transport diagnostics, credentials, or arbitrary provider output.
                failures.append(
                    ProposalRejection(
                        error_code=ProviderErrorCode.UNAVAILABLE,
                        message="Provider failed unexpectedly.",
                        metadata={"provider_type": provider.provider_type.value},
                    )
                )
            if not self.config.fallback_enabled or not getattr(
                getattr(provider, "config", None), "fallback_enabled", True
            ):
                break
        result = batch(
            request,
            origin,
            self.config,
            "unavailable",
        )
        result.status = "failed"
        result.audit.failures = failures
        result.audit.fallback_used = _attempt > 0
        result.audit.fallback_origin = origin if result.audit.fallback_used else None
        result.rejections = [
            ProposalRejection(
                error_code=ProviderErrorCode.FALLBACK_EXHAUSTED,
                message="No configured provider produced accepted proposals.",
            )
        ]
        result.audit.rejected_count = 1
        return result


def to_response_plan(result: ProposalBatch) -> ResponsePlan:
    if not result.proposals or result.status not in {"accepted", "partial"}:
        raise ValueError("Require an admitted nonempty proposal batch")
    return ResponsePlan(
        id="agent-proposals",
        name="Validated agent proposals",
        description=f"Proposal source: {result.audit.provenance}",
        actions=[a.model_copy(deep=True) for a in result.proposals],
        status=PlanStatus.READY,
    )
