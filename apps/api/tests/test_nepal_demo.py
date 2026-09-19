import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from ark_api.main import app
from ark_api.routes.simulations import run_response_simulation
from ark_api.simulation.models import Capability, SimulationRequest, SimulationResponse
from ark_api.simulation.plans import generate_candidate_plans
from ark_api.simulation.routing import (
    CIVILIAN_CAPABILITIES,
    NoRouteError,
    shortest_path,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "data/scenarios/kantipur-river/nepal_nakkhu_demo_v1.json"
RUNNER = ROOT / "apps/api/scripts/run_nepal_demo.py"
DISCLAIMER = (
    "This scenario is a synthetic operational reconstruction inspired by the September "
    "2024 Nakkhu River flood near Kantipur Colony and Nakhipot, Lalitpur, Nepal. Exact "
    "responder positions, population counts, routes, travel times, closure times, and "
    "outcomes are demonstration assumptions rather than verified historical records."
)


@pytest.fixture
def demo_request():
    return SimulationRequest.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists_parses_and_validates():
    assert FIXTURE.is_file()
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    parsed = SimulationRequest.model_validate(data)
    assert parsed.world_state.scenario_id == "nepal-nakkhu-demo-v1"
    assert parsed.duration_minutes == 60
    assert parsed.world_state.current_minute == 0
    assert parsed.plans is None


def test_metadata_context_and_assumptions_are_separate(demo_request):
    metadata = demo_request.world_state.metadata
    assert metadata["fixture_version"] == "1.0.0"
    assert metadata["disclaimer"] == DISCLAIMER
    context = metadata["documented_context"]
    assert context["period"] == "September 2024"
    assert context["river"] == "Nakkhu River"
    assert {"Kantipur Colony", "Nakhipot", "Lalitpur, Nepal"} <= set(context["places"])
    assert "Rapid river rise" in context["summary"]
    assert len(context["sources"]) >= 2
    assert all(
        s["url"].startswith("https://") and s["supports"] for s in context["sources"]
    )
    assert {
        "population_counts",
        "responders",
        "routes",
        "closure_times",
        "shelter_capacity",
        "hazards",
        "outcomes",
        "time_origin",
    } <= metadata["synthetic_assumptions"].keys()


def test_unique_ids_and_resolved_references(demo_request):
    world = demo_request.world_state
    for collection in (
        world.nodes,
        world.routes,
        world.hazards,
        world.responders,
        world.rescue_requests,
        world.communities,
        world.shelters,
    ):
        assert len({item.id for item in collection}) == len(collection)
    # WorldState's own cross-field validators check every domain node reference.
    assert type(world).model_validate_json(world.model_dump_json()) == world
    assert set(world.metadata["location_roles"].values()) <= {n.id for n in world.nodes}


def test_population_cohorts_are_disjoint_and_counts_match(demo_request):
    world = demo_request.world_state
    accounting = world.metadata["population_accounting"]
    assert "disjoint" in accounting["rule"]
    expected = {(r.id, "rescue_request"): r.people_count for r in world.rescue_requests}
    expected.update({(c.id, "community"): c.population for c in world.communities})
    expected.update(
        {(s.id, "initial_shelter_occupants"): s.occupancy for s in world.shelters}
    )
    cohorts = accounting["cohorts"]
    assert {(c["record_id"], c["kind"]) for c in cohorts} == expected.keys()
    assert len(cohorts) == len(expected)
    all_people = []
    for cohort in cohorts:
        assert (
            len(cohort["person_ids"]) == expected[cohort["record_id"], cohort["kind"]]
        )
        all_people.extend(cohort["person_ids"])
    assert (
        len(all_people) == len(set(all_people)) == 35
    )  # 33 demand + 2 initial occupants.


def test_required_assets_locations_and_demands(demo_request):
    world = demo_request.world_state
    assert len(world.nodes) == 6
    assert len(world.responders) == 5
    assert sum(r.type == "boat" for r in world.responders) == 2
    assert {"rescue_team", "ambulance", "bus"} <= {r.type for r in world.responders}
    assert any(n.is_safe_zone for n in world.nodes)
    assert all(
        r.current_node_id == world.metadata["location_roles"]["primary_staging"]
        for r in world.responders
    )
    assert all("Synthetic" in r.name for r in world.responders)
    assert len({r.urgency for r in world.rescue_requests}) > 1
    assert any(
        r.urgency >= 4 and r.node_id == "kantipur" for r in world.rescue_requests
    )
    community = world.communities[0]
    assert community.node_id == "nakhipot"
    assert community.population > max(r.capacity for r in world.responders)
    assert community.isolation_minute == 18
    assert any(s.status == "open" and s.capacity > s.occupancy for s in world.shelters)
    assert all(n.latitude is None and n.longitude is None for n in world.nodes)
    assert all(not hazard.observed for hazard in world.hazards)


def test_closures_and_water_only_routes(demo_request):
    world = demo_request.world_state
    assert 6 <= len(world.routes) <= 12
    assert any(
        r.closure_minute is not None and 0 < r.closure_minute < 60 for r in world.routes
    )
    assert any(
        r.allowed_capabilities == {Capability.WATER_TRAVEL} for r in world.routes
    )
    for node in ("nakhipot", "kantipur"):
        assert shortest_path(world, node, "staging", 0, CIVILIAN_CAPABILITIES)
        with pytest.raises(NoRouteError):
            shortest_path(world, node, "staging", 60, CIVILIAN_CAPABILITIES)
        assert shortest_path(world, node, "staging", 60, {Capability.WATER_TRAVEL})


def test_longer_alternative_route_exists(demo_request):
    world = demo_request.world_state
    direct = shortest_path(
        world, "staging", "shelter-ground", 60, CIVILIAN_CAPABILITIES
    )
    alternative_world = world.model_copy(deep=True)
    alternative_world.routes = [
        r for r in alternative_world.routes if r.id != "road-staging-shelter"
    ]
    alternative = shortest_path(
        alternative_world, "staging", "shelter-ground", 60, CIVILIAN_CAPABILITIES
    )
    assert direct.total_travel_minutes == 7
    assert alternative.total_travel_minutes == 13


def test_three_distinct_baseline_plans(demo_request):
    plans = generate_candidate_plans(demo_request.world_state)
    assert [p.id for p in plans] == [
        "immediate-rescue",
        "balanced-response",
        "preventive-evacuation",
    ]
    signatures = {
        tuple(
            (
                a.responder_id,
                a.action_type,
                a.request_id,
                a.community_id,
                a.people_count,
            )
            for a in p.actions
        )
        for p in plans
    }
    assert len(signatures) == 3


def test_replay_determinism_and_input_preservation(demo_request):
    before = demo_request.model_dump_json()
    first = run_response_simulation(demo_request)
    second = run_response_simulation(demo_request)
    assert first.model_dump_json() == second.model_dump_json()
    assert demo_request.model_dump_json() == before
    assert len(first.results) == 3
    assert all(
        r.status == "completed" and r.score is not None and len(r.score_breakdown) == 9
        for r in first.results
    )
    assert all(r.metrics.rejected_actions == 0 for r in first.results)
    assert any(
        r.plan_id == first.recommended_plan_id and r.viable for r in first.results
    )


def test_golden_strategy_order_and_tradeoffs(demo_request):
    response = run_response_simulation(demo_request)
    assert [r.plan_id for r in response.results] == [
        "balanced-response",
        "preventive-evacuation",
        "immediate-rescue",
    ]
    by_id = {r.plan_id: r for r in response.results}
    immediate = by_id["immediate-rescue"].metrics
    balanced = by_id["balanced-response"].metrics
    preventive = by_id["preventive-evacuation"].metrics
    assert (
        immediate.people_rescued > balanced.people_rescued > preventive.people_rescued
    )
    assert (
        preventive.people_evacuated
        > balanced.people_evacuated
        > immediate.people_evacuated
    )
    assert (
        balanced.people_isolated
        < preventive.people_isolated
        < immediate.people_isolated
    )
    assert balanced.critical_calls_completed >= 1
    assert preventive.critical_calls_unanswered > balanced.critical_calls_unanswered
    assert (
        immediate.critical_calls_unanswered == balanced.critical_calls_unanswered == 0
    )
    assert all(
        r.viable and r.metrics.responders_stranded == 0 for r in response.results
    )
    assert len({r.metrics.model_dump_json() for r in response.results}) == 3
    assert response.recommended_plan_id == "balanced-response"
    shelter = demo_request.world_state.shelters[0]
    assert preventive.people_evacuated == shelter.capacity - shelter.occupancy


def test_demo_api_is_deterministic_and_successful():
    raw = FIXTURE.read_bytes()

    async def post_twice():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return [
                await client.post(
                    "/api/v1/simulate-response",
                    content=raw,
                    headers={"content-type": "application/json"},
                )
                for _ in range(2)
            ]

    first, second = asyncio.run(post_twice())
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    parsed = SimulationResponse.model_validate(first.json())
    assert parsed.recommended_plan_id == "balanced-response"
    assert all(r.timeline and r.score_breakdown for r in parsed.results)


def test_runner_success_and_optional_json(tmp_path):
    output = tmp_path / "response.json"
    process = subprocess.run(
        [sys.executable, str(RUNNER), "--output", str(output)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    for field in (
        "Rank",
        "Plan ID",
        "Viable",
        "Score",
        "Rescued",
        "Evacuated",
        "Isolated",
        "Critical unanswered",
        "Stranded",
        "Recommended plan ID: balanced-response",
    ):
        assert field in process.stdout
    assert "Synthetic operational reconstruction" in process.stdout
    parsed = SimulationResponse.model_validate_json(output.read_text(encoding="utf-8"))
    assert len(parsed.results) == 3


@pytest.mark.parametrize("content", ["{", "{}"])
def test_runner_invalid_fixture_exits_nonzero(tmp_path, content):
    invalid = tmp_path / "invalid.json"
    invalid.write_text(content, encoding="utf-8")
    process = subprocess.run(
        [sys.executable, str(RUNNER), "--fixture", str(invalid)],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert process.returncode != 0
    assert "Demo failed" in process.stderr
    assert "Recommended plan ID" not in process.stdout


def test_runner_execution_failure_exits_nonzero(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("nepal_demo_runner_test", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def fail(_request):
        raise RuntimeError("Injected execution failure")

    monkeypatch.setattr(module, "run_response_simulation", fail)
    assert module.main([]) == 1
    assert "Demo failed" in capsys.readouterr().err


def test_runner_cannot_overwrite_fixture(tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_bytes(FIXTURE.read_bytes())
    before = fixture.read_bytes()
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--fixture",
            str(fixture),
            "--output",
            str(fixture),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert process.returncode == 1
    assert fixture.read_bytes() == before
