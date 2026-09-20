# Nakkhu River demonstration, version 1

Fixture: `data/scenarios/kantipur-river/nepal_nakkhu_demo_v1.json`.
Runner: `apps/api/scripts/run_nepal_demo.py`.

This scenario is a synthetic operational reconstruction inspired by the September
2024 Nakkhu River flood near Kantipur Colony and Nakhipot, Lalitpur, Nepal. Exact
responder positions, population counts, routes, travel times, closure times, and
outcomes are demonstration assumptions rather than verified historical records.

The 60-minute fixture demonstrates resource allocation using the existing
SimulationRequest -> candidate plans -> isolated simulations -> scoring -> ranking
-> SimulationResponse pipeline. No engine, policy, or API changes were needed to
obtain the ordering below. The other empty scaffold files in this directory are
not inputs to this replay.

## Historical context and assumptions

[Khabarhub's September 28 report](https://english.khabarhub.com/2024/28/402033/)
locates a flood rescue incident near Kantipur Colony in Nakhipot, Lalitpur, on the
Nakkhu River. The next day's
[Kathmandu Post report](https://kathmandupost.com/national/2024/09/29/government-faces-criticism-over-slow-rescue-as-disasters-claim-lives-property)
describes swollen-river conditions and rescue-access difficulties, including poor
visibility. These reports establish setting and access challenges only. Early
casualty reports are not used as demand counts or predicted outcomes. Rapid river
rise is qualitative inspiration, not a measured rise rate or model calibration.

Fixture metadata separately labels `documented_context` (including source URLs)
and `synthetic_assumptions`. Every population, responder, initial position,
capacity, hazard severity, route, capability restriction, travel time, closure,
shelter characteristic, and resulting outcome is synthetic. Coordinates are
omitted to avoid suggesting surveyed map accuracy. Minute 0 is an arbitrary
decision point, not a historical timestamp.

There are six location roles, ten edges, five responders, four rescue requests,
one Nakhipot household cohort, and one operational shelter. The two boats have
capacity 4 each, the ambulance 2, the ground team 3, and the bus 10. All start at
the synthetic staging node. The three road closures occur at minutes 10 and 18;
water-only links remain available by assumption and never count as civilian
walking access. A direct staging-to-shelter road takes 7 minutes; a permanent
alternative via the secondary zone and medical-transfer point takes 13.

Population accounting is explicit: 13 rescue-demand people, 20 separate community
members, and 2 separate initial shelter occupants. The `population_accounting`
metadata assigns distinct fictional person labels to every cohort. These labels
are audit documentation, not new engine fields or historical identities. The
tests verify pairwise disjointness and agreement with domain counts. The shelter
has capacity 20, leaving 18 admissions, so shelter capacity limits preventive work.

## Replay locally

After installing backend dependencies (`uv sync --project apps/api --locked`),
run this exact PowerShell command **from the repository root**:

```powershell
& .\apps\api\.venv\Scripts\python.exe .\apps\api\scripts\run_nepal_demo.py
```

Equivalent uv command:

```powershell
uv run --project apps/api python apps/api/scripts/run_nepal_demo.py
```

No live service, network calls, MiroFish, or LLM is needed for replay. The runner
loads the versioned fixture relative to its own location, validates it, and calls
the same orchestration function as the API. `--fixture PATH` selects an alternate
fixture; `--output PATH` writes the full response JSON to a chosen file (its parent
must exist). Invalid input, execution errors, and output errors exit nonzero.
The input fixture cannot be used as the output file.

Example console output (score display rounded to two decimal places only):

```text
Rank | Plan ID | Viable | Score | Rescued | Evacuated | Isolated | Critical unanswered | Stranded
1 | balanced-response | true | 146.17 | 10 | 13 | 7 | 0 | 0
2 | preventive-evacuation | true | -79.50 | 2 | 18 | 10 | 2 | 0
3 | immediate-rescue | true | -97.00 | 13 | 0 | 20 | 0 | 0
Recommended plan ID: balanced-response
```

Immediate Rescue services both Kantipur groups, the medical group, and the lower
urgency ground-assistance group, leaving household evacuation undone. Balanced
Response assigns the two boats and ambulance to urgent rescues, while the bus and
ground team deliver 13 household members before road closure. Preventive Evacuation
uses the bus and both boats to fill the 18 free shelter places; the ambulance can
still serve the medical call, but both Kantipur calls remain unresolved. All three
plans are viable under the current policy. Viability does not mean no unmet demand.

The existing score weights reward the balanced combination here. Rankings are
calculated, never stored in the input or overridden. `test_nepal_demo.py` records
the expected order and major outcome relationships without snapshotting timelines.

## Replay through the HTTP API

For optional HTTP testing, start the existing app in one terminal from the root:

```powershell
uv run --project apps/api uvicorn ark_api.main:app --reload
```

Then submit the fixture from another PowerShell terminal at the repository root:

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/v1/simulate-response' -ContentType 'application/json' -InFile '.\data\scenarios\kantipur-river\nepal_nakkhu_demo_v1.json'
```

Tests exercise the same endpoint in process with httpx, with no listening server.

## What this does not prove

This is not an exact historical reconstruction, calibrated behavioral prediction,
government-grade flood model, claim of guaranteed lives saved, or operational
certification. It shows how the current one-primary-action-per-responder policies
trade rescue demand against preventive evacuation under explicit assumptions.
It does not simulate return trips, actual water movement, or changing live data.
Human incident command retains authority; every output is experimental decision
support. Keep this v1 fixture stable for replay; substantive future scenario
changes should receive a new fixture version and corresponding golden test.
