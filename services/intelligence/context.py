"""Assemble the bounded, read-only context exposed to Incident Copilot."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Tuple

JsonObject = Dict[str, Any]


class CopilotContextBuilder:
    """Join canonical map data with available responder-simulation output."""

    def __init__(self, scenario_service, report_service=None) -> None:
        self.scenario_service = scenario_service
        self.report_service = report_service
        self.repository_root = Path(__file__).resolve().parents[2]
        self.responder_fixture_path = (
            self.repository_root
            / "data"
            / "scenarios"
            / "kantipur-river"
            / "nepal_nakkhu_demo_v1.json"
        )

    @staticmethod
    def _load_json(path: Path, maximum_bytes: int) -> Optional[JsonObject]:
        if not path.exists() or path.stat().st_size > maximum_bytes:
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _mirofish_context(self) -> JsonObject:
        configured = os.getenv("ARK_MIROFISH_CONTEXT_PATH")
        path = (
            Path(configured).expanduser()
            if configured
            else self.repository_root
            / "data"
            / "runtime"
            / "mirofish-latest.json"
        )
        output = self._load_json(path, 512_000)
        if output is None:
            return {
                "status": "unavailable",
                "reason": "No persisted, validated MiroFish proposal result is available.",
            }
        return {
            "status": "available",
            "source": "persisted_validated_output",
            "result": output,
        }

    def _latest_simulation(self) -> JsonObject:
        if self.report_service is None:
            return {"status": "unavailable"}
        runs = self.report_service.list_runs(1)
        if not runs:
            return {"status": "unavailable", "reason": "No saved run exists."}
        summary = runs[0]
        report = self.report_service.get_report(summary["report_id"])
        return {
            "status": "available",
            "run": summary,
            "report": report,
        }

    @staticmethod
    def _collect_context_ids(value: Any) -> Set[str]:
        ids: Set[str] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    (key == "id" or key.endswith("_id"))
                    and isinstance(item, str)
                    and item
                ):
                    ids.add(item)
                ids.update(CopilotContextBuilder._collect_context_ids(item))
        elif isinstance(value, list):
            for item in value:
                ids.update(CopilotContextBuilder._collect_context_ids(item))
        return ids

    @staticmethod
    def _evidence_ids(
        state: JsonObject,
        responder_fixture: Optional[JsonObject],
        latest_simulation: JsonObject,
        mirofish: JsonObject,
        reports: Iterable[JsonObject],
    ) -> Set[str]:
        values: Set[str] = {
            state["scenario_id"],
            state["frame_id"],
            state["world_state_version"],
        }
        for key in ("active_event_ids",):
            values.update(str(item) for item in state.get(key, []))
        for collection, key in (
            (state.get("edge_states", []), "edge_id"),
            (state.get("community_access", []), "community_id"),
            (state.get("hazards", []), "hazard_id"),
            (state.get("prediction_signals", []), "ping_id"),
            (state.get("plan_results", []), "plan_id"),
        ):
            values.update(str(item[key]) for item in collection if item.get(key))
        for report in reports:
            if report.get("report_id"):
                values.add(str(report["report_id"]))
        if responder_fixture:
            world = responder_fixture.get("world_state", {})
            for collection_name in (
                "responders",
                "rescue_requests",
                "communities",
                "shelters",
                "nodes",
                "routes",
            ):
                values.update(
                    str(item["id"])
                    for item in world.get(collection_name, [])
                    if isinstance(item, dict) and item.get("id")
                )
        run = latest_simulation.get("run") or {}
        values.update(
            str(run[key]) for key in ("run_id", "report_id") if run.get(key)
        )
        result = mirofish.get("result") or {}
        if result.get("snapshot_hash"):
            values.add(str(result["snapshot_hash"]))
        return values

    def build(
        self,
        state: JsonObject,
        intelligence_reports: Iterable[JsonObject],
    ) -> Tuple[JsonObject, Set[str]]:
        reports = list(intelligence_reports)
        responder_fixture = self._load_json(self.responder_fixture_path, 256_000)
        latest_simulation = self._latest_simulation()
        mirofish = self._mirofish_context()
        context = {
            "context_version": "ark-copilot-grounding/1.0.0",
            "data_classification": state["data_classification"],
            "operational_use": state["operational_use"],
            "canonical_world_state": state,
            "scenario": self.scenario_service.manifest,
            "map_assets": self.scenario_service.assets,
            "road_network": self.scenario_service.network,
            "timeline_frames": [
                {
                    "frame_id": frame["frame_id"],
                    "simulation_time_hours": frame["simulation_time_hours"],
                    "rainfall_assumption": frame["rainfall_assumption"],
                    "rainfall_multiplier": frame["rainfall_multiplier"],
                }
                for frame in self.scenario_service.flood_frames["frames"]
            ],
            "available_events": self.scenario_service.event_stream["events"],
            "response_plan_definitions": self.scenario_service.response_plans[
                "plans"
            ],
            "field_intelligence": reports,
            "responder_simulation_fixture": responder_fixture
            or {
                "status": "unavailable",
                "reason": "Responder simulation fixture could not be loaded.",
            },
            "latest_saved_map_simulation": latest_simulation,
            "mirofish": mirofish,
            "excluded_visual_data": [
                (
                    "Basemap imagery and raw flood-polygon coordinates are "
                    "visual-only and are not sent."
                ),
                (
                    "All routed-edge flood depths and derived consequences are "
                    "present in canonical_world_state."
                ),
            ],
        }
        evidence_ids = self._evidence_ids(
            state,
            responder_fixture,
            latest_simulation,
            mirofish,
            reports,
        )
        evidence_ids.update(self._collect_context_ids(context))
        return context, evidence_ids
