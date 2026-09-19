# Field intelligence contract

The field-intelligence API converts an operator or responder message into a
stored, auditable report. Ingestion never changes the canonical world state.

The dashboard's Incident Copilot calls `POST /intelligence/messages`, which
returns:

- the original message and source;
- an extracted claim and matched asset;
- separate evidence dimensions rather than a generic AI confidence score;
- a proposed deterministic state change;
- an optional tentative world-state branch for probable reports.

An operator promotes or rejects the report through
`POST /intelligence/reports/{report_id}/decision`.
Only a confirm decision applies the proposed change to the supplied canonical
world state. keep_tentative and reject preserve the baseline.

Confirmed reports are replayed through the normal scenario endpoint using
repeated `intelligence_reports` query parameters. The scenario engine folds
their deterministic synthetic events into the same edge, community, hazard,
and plan derivation used by fixture events. Probable reports can return a
tentative world state for an amber map preview without mutating the baseline.

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

## Run and try it

From the repository root:

```bash
npm install
python3 -m venv apps/api/.venv
apps/api/.venv/bin/pip install -r apps/api/requirements.txt
```

Then start the API and web app in separate terminals:

```bash
apps/api/.venv/bin/python -m uvicorn apps.api.main:app --reload --port 8000
npm run dev:web
```

Open the Vite URL printed in the terminal (normally
`http://localhost:5173`). In **Incident Copilot**, try a message such as:

```text
Police radio reports ktp-bridge-02 is blocked by debris.
```

The proposed closure appears as a tentative map preview. Choose **Confirm** to
recompute the canonical frame and dependent routing outputs, **Keep tentative**
to retain the report without applying it, or **Reject** to discard its effect.

The current report store is process-local, so restarting the API clears chat
reports and decisions.
