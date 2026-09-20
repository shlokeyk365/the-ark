# Field intelligence contract

## Hybrid Copilot and private Claude setup

Put `ANTHROPIC_API_KEY=your-key` and optionally
`ANTHROPIC_MODEL=claude-sonnet-4-6` in the **repository-root `.env.local`**.
This file is ignored by Git, read only by the Python server, and never included
in a response or browser bundle. Do not use a `VITE_` variable for credentials.
Environment variables override the file. The API rereads the file on each chat
request, so saving a key does not require a frontend rebuild or server restart.
For keys that require a workspace, also set `ANTHROPIC_WORKSPACE_ID=wrkspc_...`.
The server sends it in the `anthropic-workspace-id` header.

On Windows run `npm run dev:local`, then open
`http://127.0.0.1:5173/command-center`. The launcher starts separate background
API/Vite processes and writes logs to `work/local-servers`. It only restarts a
port-8000 process identified as this checkout's `apps.api.main` server. It will
refuse to stop an unidentified process. A key-present indicator is configuration
status, not a successful authentication check; API failures are shown in chat.

`GET /intelligence/status` returns `{assistant_configured: boolean}`, never a
key or provider/model name. `POST /intelligence/chat` accepts `message`, `frame_id`, `event_ids`,
and `intelligence_report_ids`. The backend rebuilds the world from these IDs;
the browser cannot submit fabricated world-state facts or model scores.

Responses carry `answer`, the original `message`, `world_state_version`,
`frame_id`, `context_digest`, nullable `report` and `tentative_world_state`, and
`baseline_changed: false`. Provider mode and grounding records stay server-side;
the browser receives no citations, evidence records, or provider label. Old replies retain their
snapshot labels after a frame or event change. `context_digest` hashes the
world for deterministic replies and the submitted question/evidence for Claude.

The source dropdown and name field are removed. Chat reports have explicit
`operator` provenance and source name `Operator`; mentioning police or a field
team in a message does not upgrade its source to verified official evidence.

Road/bridge IDs or exact names plus clear closed/blocked/flooded/open status
use deterministic rules. Questions, ambiguous matches, negation and conflicting
statuses do not create changes. Simple edge-status questions are answered from
the selected map frame without a model. Other map entities are available for
questions but do not yet support mutation commands.

The additive `open_edge` report produces a `clear_field_restriction` event.
It clears only preceding field-intelligence restrictions on that edge. It
cannot override flood thresholds or fixture bridge failures. Event order is
preserved, including in isolation-cache keys. Confirmation is still required.

For other questions, Claude receives current derived map state, asset/network
metadata, flood inputs, plans, prediction metadata, active reports, the latest
five saved simulation reports, and the first-responder demo's validated
proposals and simulated results. Rendering coordinate arrays are omitted;
Claude does not see basemap pixels or infer terrain. No historical report is
silently relabeled as the current map state.

The MiroFish fixture path is executed through the existing proposal validator
and deterministic simulator, then cached until API restart. It is labeled
**separate synthetic first-responder demo**, with its original scenario ID and
snapshot hash. It is not live MiroFish output and uses a different snapshot
from the map. Missing integration dependencies are reported as unavailable.

Claude uses the official [Messages API structured-output format](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
to return three briefing fields plus internal `evidence_ids`. The server renders
exactly `STATUS`, `THREAT`, and `ACTION` lines, optionally followed by one
`Ask for detail on:` line, with a hard cap of 120 words. It validates the output
shape, word count, and every internal evidence ID. Unknown IDs, invalid responses,
truncation, timeouts and API failures produce an explicit unavailable response.
Answers without evidence are replaced by an abstention. Claude cannot
invoke tools, submit events, confirm reports or change plan scores. Valid IDs do
not prove that generated prose is entailed by the selected records. Grounding is
prompt-constrained synthesis, not a guarantee against hallucinations. Simple status
lookups remain deterministic; explanatory questions go to Claude.

Requests have a 750 KB context limit, 45-second HTTP timeout and 4,096 output
token limit. Oversize context fails visibly rather than being silently truncated.
No prior chat transcript is treated as factual context: each question uses a
fresh server snapshot. Never represent unanswered questions as verified facts.

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
