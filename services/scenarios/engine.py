"""Load, derive, and recompute the deterministic Kantipur scenario."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from services.routing.engine import (
    calculate_time_to_isolation,
    compute_community_access,
    derive_edge_states,
)
from services.scenarios.evaluator import evaluate_plan
from services.scenarios.validation import validate_scenario_fixtures

JsonObject = Dict[str, Any]


class ScenarioService:
    """Deterministic orchestration for one fixture-backed scenario."""

    def __init__(self, fixture_directory: Optional[Path] = None) -> None:
        self.fixture_directory = fixture_directory or (
            Path(__file__).resolve().parents[2]
            / "data"
            / "scenarios"
            / "kantipur-river"
        )
        self.manifest = self._load("scenario.json")
        self.assets = self._load("assets.geojson")
        self.network = self._load("road-network.geojson")
        self.flood_frames = self._load("flood-frames.json")
        self.response_plans = self._load("response-plans.json")
        self.event_stream = self._load("event-stream.json")
        self.impact_prior = self._load("model-impact-prior.json")
        self.prediction_pings = self._load("prediction-pings.json")
        # Visual reference only: never passed to routing or flood derivation.
        self.context_boundaries = self._load("context-boundaries.geojson")
        validate_scenario_fixtures(
            self.manifest,
            self.assets,
            self.network,
            self.flood_frames,
            self.response_plans,
            self.event_stream,
            self.context_boundaries,
            self.impact_prior,
            self.prediction_pings,
        )
        self._isolation_cache: Dict[Tuple[str, ...], Dict[str, Optional[float]]] = {}

    def _time_to_isolation(
        self, events: Iterable[Mapping[str, Any]] = ()
    ) -> Dict[str, Optional[float]]:
        """Time-to-isolation for the supplied event set, memoized per event set."""

        event_list = list(events)
        key = tuple(sorted(event["event_id"] for event in event_list))
        if key not in self._isolation_cache:
            self._isolation_cache[key] = calculate_time_to_isolation(
                self.assets,
                self.network,
                self.flood_frames["frames"],
                event_list,
            )
        return self._isolation_cache[key]

    def _load(self, filename: str) -> JsonObject:
        with (self.fixture_directory / filename).open(encoding="utf-8") as source:
            return json.load(source)

    def _frame(self, frame_id: str) -> Mapping[str, Any]:
        for frame in self.flood_frames["frames"]:
            if frame["frame_id"] == frame_id:
                return frame
        raise KeyError(f"Unknown frame_id: {frame_id}")

    def _events(self, event_ids: Iterable[str]) -> List[Mapping[str, Any]]:
        requested = set(event_ids)
        events = [
            event
            for event in self.event_stream["events"]
            if event["event_id"] in requested
        ]
        found = {event["event_id"] for event in events}
        missing = requested - found
        if missing:
            raise KeyError(f"Unknown event_id: {sorted(missing)[0]}")
        return events

    def build_world_state(
        self, frame_id: str, event_ids: Iterable[str] = ()
    ) -> JsonObject:
        frame = self._frame(frame_id)
        events = self._events(event_ids)
        inactive = [
            event["event_id"]
            for event in events
            if event["effective_at_hours"] > frame["simulation_time_hours"]
        ]
        if inactive:
            raise ValueError(
                f"Event {inactive[0]} is not effective at frame {frame['frame_id']}"
            )
        frame_index = self.flood_frames["frames"].index(frame) + 1
        event_suffix = "" if not events else "-" + "-".join(
            event["event_id"].removeprefix("ktp-event-") for event in events
        )
        version = f"ktp-world-{frame_index:04d}{event_suffix}"
        edge_states_by_id = derive_edge_states(self.network, frame, events)
        community_access = compute_community_access(
            self.assets, self.network, edge_states_by_id
        )
        isolation_times = self._time_to_isolation(events)
        for access in community_access:
            access["time_to_isolation_hours"] = isolation_times[
                access["community_id"]
            ]

        state: JsonObject = {
            "schema_version": "1.0.0",
            "scenario_id": self.manifest["scenario_id"],
            "world_state_version": version,
            "observed_at": frame["observed_at"],
            "calculated_at": frame["observed_at"],
            "simulation_time_hours": frame["simulation_time_hours"],
            "frame_id": frame["frame_id"],
            "data_classification": self.manifest["data_classification"],
            "operational_use": self.manifest["operational_use"],
            "active_event_ids": [event["event_id"] for event in events],
            "rainfall_assumption": frame["rainfall_assumption"],
            "rainfall_multiplier": frame["rainfall_multiplier"],
            "edge_states": list(edge_states_by_id.values()),
            "community_access": community_access,
            "prediction_signals": self._prediction_signals(
                frame["simulation_time_hours"]
            ),
        }
        state["hazards"] = self._hazards(state)
        state["plan_results"] = [
            evaluate_plan(plan, self.assets, self.network, state)
            for plan in self.response_plans["plans"]
        ]
        return state

    def _prediction_signals(self, simulation_time_hours: float) -> List[JsonObject]:
        """Project the frozen event-level model output onto map annotations.

        The probabilities remain fixed because the trained model predicts a
        whole-event impact prior, not an hourly physical state. The scenario
        timeline only changes whether a signal is still forecast or has become
        active according to the deterministic flood frame.
        """

        probabilities = self.impact_prior["impactProbabilities"]
        return [
            {
                "ping_id": ping["ping_id"],
                "target": ping["target"],
                "label": ping["label"],
                "short_label": ping["short_label"],
                "probability": probabilities[ping["target"]],
                "percent": round(probabilities[ping["target"]] * 100),
                "geometry": {
                    "type": "Point",
                    "coordinates": ping["coordinates"],
                },
                "anchor_asset_id": ping.get("anchor_asset_id"),
                "activation_hours": ping["activation_hours"],
                "state": (
                    "active"
                    if simulation_time_hours >= ping["activation_hours"]
                    else "forecast"
                ),
                "recommended_action": ping["recommended_action"],
                "source_type": "model_prediction",
            }
            for ping in self.prediction_pings["pings"]
        ]

    def _impact_model_summary(self) -> JsonObject:
        model = self.prediction_pings["model"]
        return {
            "event_id": self.prediction_pings["event_id"],
            "location": self.prediction_pings["location"],
            "model_name": model["model_name"],
            "model_version": model["model_version"],
            "status": model["status"],
            "training_events": model["training_events"],
            "feature_policy": model["feature_policy"],
            "evaluation": model["evaluation"],
            "limitations": self.impact_prior["limitations"],
        }

    def _hazards(self, state: Mapping[str, Any]) -> List[JsonObject]:
        hazards: List[JsonObject] = []
        for edge in state["edge_states"]:
            if edge["status"] == "closed":
                hazards.append(
                    {
                        "hazard_id": f"hazard:{state['world_state_version']}:{edge['edge_id']}",
                        "priority": "critical" if edge["critical"] else "high",
                        "hazard_type": "route_closed",
                        "asset_id": edge["edge_id"],
                        "source_frame_id": edge["source_frame_id"],
                        "source_event_id": edge["originating_event_id"],
                        "description": edge["closure_reason"],
                    }
                )
            elif edge["status"] == "restricted":
                hazards.append(
                    {
                        "hazard_id": f"hazard:{state['world_state_version']}:{edge['edge_id']}",
                        "priority": "medium",
                        "hazard_type": "route_restricted",
                        "asset_id": edge["edge_id"],
                        "source_frame_id": edge["source_frame_id"],
                        "source_event_id": edge["originating_event_id"],
                        "description": (
                            f"Flood depth {edge['flood_depth_m']:.2f} m increases travel time"
                        ),
                    }
                )
        for access in state["community_access"]:
            if access["isolated"]:
                hazards.append(
                    {
                        "hazard_id": f"hazard:{state['world_state_version']}:{access['community_id']}",
                        "priority": "critical",
                        "hazard_type": "community_isolated",
                        "asset_id": access["community_id"],
                        "source_frame_id": state["frame_id"],
                        "source_event_id": (
                            state["active_event_ids"][0]
                            if state["active_event_ids"]
                            else None
                        ),
                        "description": "No traversable route to an open shelter or hospital",
                    }
                )
        priority_order = {"critical": 0, "high": 1, "medium": 2}
        return sorted(
            hazards,
            key=lambda hazard: (
                priority_order[hazard["priority"]],
                hazard["hazard_id"],
            ),
        )

    def baseline(self) -> JsonObject:
        return self.build_world_state(self.manifest["initial_frame_id"])

    def bootstrap(self) -> JsonObject:
        """Return static metadata and geometry needed to initialize the frontend."""

        return {
            "schema_version": self.manifest["schema_version"],
            "scenario_id": self.manifest["scenario_id"],
            "name": self.manifest["name"],
            "description": self.manifest["description"],
            "data_classification": self.manifest["data_classification"],
            "operational_use": self.manifest["operational_use"],
            "initial_world_state_version": self.manifest[
                "initial_world_state_version"
            ],
            "initial_frame_id": self.manifest["initial_frame_id"],
            "evaluation_horizon_hours": self.manifest[
                "evaluation_horizon_hours"
            ],
            "assets": self.assets,
            "road_network": self.network,
            "context_boundaries": self.context_boundaries,
            "available_frames": [
                {
                    "frame_id": frame["frame_id"],
                    "simulation_time_hours": frame["simulation_time_hours"],
                    "observed_at": frame["observed_at"],
                    "rainfall_assumption": frame["rainfall_assumption"],
                    "rainfall_multiplier": frame["rainfall_multiplier"],
                }
                for frame in self.flood_frames["frames"]
            ],
            "events": self.event_stream["events"],
            "plans": self.response_plans["plans"],
            "impact_model": self._impact_model_summary(),
        }

    def apply_event(self, event_id: str) -> JsonObject:
        event = self._events([event_id])[0]
        applicable_frames = [
            frame
            for frame in self.flood_frames["frames"]
            if frame["simulation_time_hours"] >= event["effective_at_hours"]
        ]
        frame = applicable_frames[0]
        previous_state = self.build_world_state(frame["frame_id"])
        updated_state = self.build_world_state(frame["frame_id"], [event_id])

        stale_results = copy.deepcopy(previous_state["plan_results"])
        for result in stale_results:
            result["status"] = "stale"
            result["invalidation_reason"] = (
                f"Event {event_id} created world state "
                f"{updated_state['world_state_version']}"
            )

        return {
            "scenario_id": self.manifest["scenario_id"],
            "event": event,
            "previous_world_state_version": previous_state["world_state_version"],
            "updated_world_state": updated_state,
            "stale_plan_results": stale_results,
            "recomputed_plan_results": updated_state["plan_results"],
        }
