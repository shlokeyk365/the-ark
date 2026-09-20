"""Provider protocol and shared strict ingestion boundary."""

import json
from typing import Protocol

from pydantic import ValidationError

from ark_api.agents.contracts import (
    ProposalBatch,
    ProposalDocument,
    ProposalRejection,
    ProposalRequest,
    ProviderAudit,
    ProviderErrorCode,
    ProviderType,
    fingerprint,
)
from ark_api.simulation.models import PlanAction


class ProviderFailure(Exception):
    def __init__(self, code: ProviderErrorCode, message: str):
        super().__init__(message)
        self.rejection = ProposalRejection(error_code=code, message=message)


class ProposalProvider(Protocol):
    provider_type: ProviderType

    async def propose_actions(self, request: ProposalRequest) -> ProposalBatch: ...


def batch(request, provider_type, config, provenance, **audit_fields):
    return ProposalBatch(
        request_id=request.request_id,
        provider_type=provider_type,
        snapshot_hash=request.snapshot_hash,
        audit=ProviderAudit(
            provider_type=provider_type,
            request_id=request.request_id,
            snapshot_hash=request.snapshot_hash,
            configuration_hash=fingerprint(config),
            provenance=provenance,
            **audit_fields,
        ),
    )


def load_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, TypeError, RecursionError) as error:
        raise ProviderFailure(
            ProviderErrorCode.INVALID_JSON, "Expected strict JSON."
        ) from error


def parse_document(data, request, model=ProposalDocument):
    # Classify unsupported values before enum validation, without coercing output.
    if isinstance(data, dict) and isinstance(data.get("actions"), list):
        if len(data["actions"]) > request.maximum_actions:
            raise ProviderFailure(
                ProviderErrorCode.TOO_MANY_ACTIONS, "Action limit exceeded."
            )
        for action in data["actions"]:
            if isinstance(action, dict) and isinstance(action.get("action_type"), str):
                if action["action_type"] not in request.allowed_action_types:
                    raise ProviderFailure(
                        ProviderErrorCode.UNSUPPORTED_ACTION, "Action is not allowed."
                    )
    try:
        document = model.model_validate(data)
    except ValidationError as error:
        raise ProviderFailure(
            ProviderErrorCode.INVALID_SCHEMA, "Invalid proposal schema."
        ) from error
    if document.snapshot_hash != request.snapshot_hash:
        raise ProviderFailure(
            ProviderErrorCode.STALE_SNAPSHOT, "Snapshot does not match."
        )
    return document


def actions_from_document(document, request, namespace="proposal"):
    world = request.world_state
    responders = {r.id for r in world.responders}
    if request.responder_ids is not None:
        responders &= set(request.responder_ids)
    collections = {
        "target_node_id": {n.id for n in world.nodes},
        "request_id": {r.id for r in world.rescue_requests},
        "community_id": {c.id for c in world.communities},
        "shelter_id": {s.id for s in world.shelters},
    }
    actions = []
    for index, proposal in enumerate(document.actions):
        if proposal.responder_id not in responders:
            raise ProviderFailure(
                ProviderErrorCode.UNKNOWN_RESPONDER, "Unknown or excluded responder."
            )
        for field, ids in collections.items():
            value = getattr(proposal, field)
            if value is not None and value not in ids:
                raise ProviderFailure(
                    ProviderErrorCode.UNKNOWN_TARGET, "Unknown target reference."
                )
        action_id = fingerprint(
            {
                "snapshot": request.snapshot_hash,
                "source": namespace,
                "index": index,
                "action": proposal,
            }
        )[:24]
        actions.append(PlanAction(id=f"agent:{action_id}", **proposal.model_dump()))
    return actions
