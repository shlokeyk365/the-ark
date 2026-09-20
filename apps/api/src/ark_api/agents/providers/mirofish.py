"""Experimental interview client. No lifecycle operations or model retries."""

import asyncio
import hashlib
import json

import httpx

from ark_api.agents.contracts import (
    MiroFishProviderConfig,
    ProposalDocument,
    ProviderErrorCode,
    ProviderType,
    canonical,
    fingerprint,
)
from ark_api.agents.providers.base import (
    ProviderFailure,
    actions_from_document,
    batch,
    load_json,
    parse_document,
)


class MiroFishHttpProposalProvider:
    provider_type = ProviderType.MIROFISH_HTTP

    def __init__(self, config: MiroFishProviderConfig, *, transport=None):
        self.config = config
        self.transport = transport

    def prompt(self, request, responder_id):
        payload = {
            "snapshot_hash": request.snapshot_hash,
            "simulation_minute": request.simulation_minute,
            "horizon_minutes": request.horizon_minutes,
            "world": request.world_state.model_dump(exclude={"metadata"}),
            "responder_id": responder_id,
            "allowed_action_types": request.allowed_action_types,
            "maximum_actions": 1,
            "objectives": request.objectives,
            "assumptions": "Rescue requests and community populations are disjoint. "
            "Ark alone controls physics, routes, capacities and time.",
            "instruction": "Propose at most one action for the specified responder. "
            "Return only JSON matching the schema; no prose or markdown.",
            "response_schema": ProposalDocument.model_json_schema(),
        }
        prompt = json.dumps(canonical(payload), sort_keys=True, separators=(",", ":"))
        if len(prompt.encode()) > self.config.maximum_prompt_bytes:
            raise ProviderFailure(
                ProviderErrorCode.INVALID_SCHEMA, "Prompt exceeds byte limit."
            )
        return prompt

    async def propose_actions(self, request):
        config = self.config
        mapping = config.responder_agent_mapping
        world_ids = {r.id for r in request.world_state.responders}
        if not set(mapping) <= world_ids:
            raise ProviderFailure(
                ProviderErrorCode.UNKNOWN_RESPONDER, "Configured responder is unknown."
            )
        selected = sorted(
            r
            for r in mapping
            if request.responder_ids is None or r in request.responder_ids
        )
        result = batch(
            request,
            self.provider_type,
            config,
            "live",
            upstream_commit=config.expected_upstream_commit,
            simulation_id=config.simulation_id,
            platform=config.platform,
            raw_output_retained=config.retain_raw_output,
        )
        raw_outputs = []
        try:
            async with asyncio.timeout(config.total_timeout):
                async with httpx.AsyncClient(
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                    timeout=httpx.Timeout(
                        config.total_timeout, connect=config.connect_timeout
                    ),
                ) as client:
                    for responder_id in selected:
                        if len(result.proposals) >= min(
                            request.maximum_actions, config.maximum_actions
                        ):
                            break
                        prompt = self.prompt(request, responder_id)
                        result.audit.prompt_hashes.append(fingerprint(prompt))
                        agent_id = mapping[responder_id]
                        result.audit.agent_ids.append(agent_id)
                        async with client.stream(
                            "POST",
                            config.base_url + "/api/simulation/interview",
                            json={
                                "simulation_id": config.simulation_id,
                                "agent_id": agent_id,
                                "platform": config.platform,
                                "prompt": prompt,
                                "timeout": config.total_timeout,
                            },
                        ) as response:
                            if response.status_code != 200:
                                raise ProviderFailure(
                                    ProviderErrorCode.UNAVAILABLE,
                                    "Interview HTTP request failed.",
                                )
                            raw = bytearray()
                            async for chunk in response.aiter_bytes(chunk_size=4096):
                                raw.extend(chunk)
                                if len(raw) > config.maximum_response_bytes:
                                    raise ProviderFailure(
                                        ProviderErrorCode.INVALID_ENVELOPE,
                                        "Response exceeds byte limit.",
                                    )
                        try:
                            text = raw.decode("utf-8")
                            result.audit.raw_response_hashes.append(
                                hashlib.sha256(raw).hexdigest()
                            )
                            envelope = load_json(text)
                            if (
                                envelope["success"] is not True
                                or envelope["data"]["success"] is not True
                            ):
                                raise ValueError()
                            data = envelope["data"]
                            if (
                                type(data["agent_id"]) is not int
                                or data["agent_id"] != agent_id
                                or data["result"]["agent_id"] != agent_id
                                or data["result"]["platform"] != config.platform
                            ):
                                raise ProviderFailure(
                                    ProviderErrorCode.IDENTITY_MISMATCH,
                                    "Interview identity mismatch.",
                                )
                            content = data["result"]["response"]
                            if not isinstance(content, str):
                                raise ValueError()
                        except (KeyError, TypeError, ValueError, UnicodeError) as error:
                            raise ProviderFailure(
                                ProviderErrorCode.INVALID_ENVELOPE,
                                "Invalid interview success envelope.",
                            ) from error
                        doc = parse_document(load_json(content), request)
                        if len(doc.actions) > 1:
                            raise ProviderFailure(
                                ProviderErrorCode.TOO_MANY_ACTIONS,
                                "Only one action per queried responder is allowed.",
                            )
                        if any(a.responder_id != responder_id for a in doc.actions):
                            raise ProviderFailure(
                                ProviderErrorCode.IDENTITY_MISMATCH,
                                "Agent proposed for another responder.",
                            )
                        result.proposals.extend(
                            actions_from_document(doc, request, responder_id)
                        )
                        if config.retain_raw_output:
                            raw_outputs.append(text)
        except (TimeoutError, httpx.TimeoutException) as error:
            raise ProviderFailure(
                ProviderErrorCode.TIMEOUT, "Interview batch timed out."
            ) from error
        except httpx.HTTPError as error:
            raise ProviderFailure(
                ProviderErrorCode.UNAVAILABLE, "Interview service unavailable."
            ) from error
        except ProviderFailure as error:
            error.rejection.metadata.update(
                upstream_commit=config.expected_upstream_commit,
                configuration_hash=result.audit.configuration_hash,
                prompt_hashes=result.audit.prompt_hashes,
                raw_response_hashes=result.audit.raw_response_hashes,
                agent_ids=result.audit.agent_ids,
            )
            raise
        result.audit.proposal_count = len(result.proposals)
        result.raw_output = (
            json.dumps(raw_outputs) if config.retain_raw_output else None
        )
        return result
