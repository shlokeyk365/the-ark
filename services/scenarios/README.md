# Scenario service

`ScenarioService` loads and validates the Kantipur fixtures, freezes a derived
world state, evaluates Plan A/B/C against that same state, and applies the named
bridge-failure event. Event application retains stale prior results and returns
new results linked to the updated world-state version.

The implementation is intentionally deterministic: fixture timestamps are used
as calculation timestamps, and the same inputs produce the same payload.
