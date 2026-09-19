# Field intelligence contract

The field-intelligence API converts an operator or responder message into a
stored, auditable report. Ingestion never changes the canonical world state.

POST /api/v1/intelligence/messages returns:

- the original message and source;
- an extracted claim and matched asset;
- separate evidence dimensions rather than a generic AI confidence score;
- a proposed deterministic state change;
- an optional tentative world-state branch for probable reports.

An operator promotes or rejects the report through
POST /api/v1/intelligence/reports/{report_id}/decision.
Only a confirm decision applies the proposed change to the supplied canonical
world state. keep_tentative and reject preserve the baseline.

The included store is process-local for the hackathon. Its interface is
deliberately small so it can be replaced by Postgres without changing route or
service contracts.

## Safety properties

- Raw messages and provenance are retained.
- Tentative reports are not represented as observed truth.
- Asset changes use IDs after extraction; display names are not execution keys.
- LLM extraction can later replace the deterministic extractor, but cannot
  bypass operator confirmation or deterministic application rules.
- Every applied report ID is added to world-state metadata for replay.
