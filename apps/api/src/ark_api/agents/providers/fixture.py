import hashlib

from ark_api.agents.contracts import (
    FixtureDocument,
    FixtureProviderConfig,
    ProviderErrorCode,
    ProviderType,
)
from ark_api.agents.providers.base import (
    ProviderFailure,
    actions_from_document,
    batch,
    load_json,
    parse_document,
)


class FixtureProposalProvider:
    provider_type = ProviderType.FIXTURE

    def __init__(self, config: FixtureProviderConfig):
        self.config = config

    async def propose_actions(self, request):
        try:
            with self.config.fixture_path.open("rb") as stream:
                content = stream.read(65537)
            if len(content) > 65536:
                raise ProviderFailure(
                    ProviderErrorCode.INVALID_SCHEMA, "Fixture exceeds byte limit."
                )
            raw = content.decode("utf-8")
        except OSError as error:
            raise ProviderFailure(
                ProviderErrorCode.FIXTURE_MISSING, "Fixture unavailable."
            ) from error
        except UnicodeError as error:
            raise ProviderFailure(
                ProviderErrorCode.INVALID_JSON, "Fixture encoding is invalid."
            ) from error
        try:
            doc = parse_document(load_json(raw), request, FixtureDocument)
        except ProviderFailure as error:
            if error.rejection.error_code == ProviderErrorCode.STALE_SNAPSHOT:
                raise ProviderFailure(
                    ProviderErrorCode.FIXTURE_MISMATCH, "Fixture snapshot mismatch."
                ) from error
            raise
        if (
            doc.scenario_id != request.world_state.scenario_id
            or (doc.request_id is not None and doc.request_id != request.request_id)
            or (
                self.config.expected_request_id is not None
                and self.config.expected_request_id != request.request_id
            )
            or (
                self.config.expected_scenario_id is not None
                and self.config.expected_scenario_id != doc.scenario_id
            )
        ):
            raise ProviderFailure(
                ProviderErrorCode.FIXTURE_MISMATCH, "Fixture identity mismatch."
            )
        result = batch(
            request,
            self.provider_type,
            self.config.model_dump(exclude={"fixture_path"}),
            doc.provenance,
            raw_response_hashes=[hashlib.sha256(content).hexdigest()],
            raw_output_retained=self.config.retain_raw_output,
        )
        result.proposals = actions_from_document(doc, request)
        result.audit.proposal_count = len(result.proposals)
        result.raw_output = raw if self.config.retain_raw_output else None
        return result
