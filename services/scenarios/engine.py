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
        self.flood_polygons = self._load("flood-polygons.geojson")
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
            self.flood_polygons,
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
        # Field reopening makes event order significant.
        key = tuple(event["event_id"] for event in event_list)
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
        self,
        frame_id: str,
        event_ids: Iterable[str] = (),
        additional_events: Iterable[Mapping[str, Any]] = (),
    ) -> JsonObject:
        frame = self._frame(frame_id)
        events = self._events(event_ids) + list(additional_events)
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
                frame,
                edge_states_by_id,
            ),
        }
        state["hazards"] = self._hazards(state)
        state["plan_results"] = [
            evaluate_plan(plan, self.assets, self.network, state)
            for plan in self.response_plans["plans"]
        ]
        return state

    def _prediction_signals(
        self,
        frame: Mapping[str, Any],
        edge_states_by_id: Mapping[str, Mapping[str, Any]],
    ) -> List[JsonObject]:
        """Localize event priors with hazard, exposure, and vulnerability proxies.

        The CatBoost values remain immutable as ``base_probability``. Displayed
        values are prototype ranking scores informed by absolute local depth,
        the edge's closure threshold and status, route criticality, and nearby
        community population. They are not calibrated dispatch probabilities.
        """

        simulation_time_hours = frame["simulation_time_hours"]
        probabilities = self.impact_prior["impactProbabilities"]
        global_max_depth = max(
            condition["flood_depth_m"]
            for modeled_frame in self.flood_frames["frames"]
            for condition in modeled_frame["edge_conditions"]
        )
        assets_by_id = {
            feature["properties"]["id"]: feature["properties"]
            for feature in self.assets["features"]
        }
        max_population = max(
            asset.get("population", 0) for asset in assets_by_id.values()
        )
        status_scores = {"open": 0.0, "restricted": 0.55, "closed": 1.0}
        target_weights = {
            "casualty_or_missing": {
                "depth": 0.35,
                "threshold": 0.25,
                "status": 0.15,
                "critical": 0.05,
                "exposure": 0.20,
            },
            "housing_damage": {
                "depth": 0.35,
                "threshold": 0.25,
                "status": 0.10,
                "critical": 0.00,
                "exposure": 0.30,
            },
            "transport_disruption": {
                "depth": 0.30,
                "threshold": 0.30,
                "status": 0.20,
                "critical": 0.15,
                "exposure": 0.05,
            },
            "severe_impact": {
                "depth": 0.35,
                "threshold": 0.25,
                "status": 0.15,
                "critical": 0.10,
                "exposure": 0.15,
            },
        }

        signals: List[JsonObject] = []
        for ping in self.prediction_pings["pings"]:
            base_probability = probabilities[ping["target"]]
            anchor_edge_id = ping["anchor_edge_id"]
            edge_state = edge_states_by_id[anchor_edge_id]
            local_depth = edge_state["flood_depth_m"]
            exposure_asset_id = ping["exposure_asset_id"]
            exposed_people = assets_by_id[exposure_asset_id].get("population", 0)
            components = {
                "depth": min(1.0, local_depth / global_max_depth),
                "threshold": min(
                    1.0,
                    local_depth / edge_state["closure_depth_m"],
                ),
                "status": status_scores[edge_state["status"]],
                "critical": 1.0 if edge_state["critical"] else 0.0,
                "exposure": exposed_people / max_population,
            }
            weights = target_weights[ping["target"]]
            local_danger = min(
                1.0,
                sum(components[name] * weights[name] for name in weights),
            )
            adjusted_probability = base_probability * (
                0.10 + (0.90 * local_danger)
            )
            priority_score = round(
                100 * ((0.70 * local_danger) + (0.30 * base_probability))
            )
            if priority_score >= 70:
                priority_level = "critical"
            elif priority_score >= 55:
                priority_level = "high"
            elif priority_score >= 35:
                priority_level = "elevated"
            else:
                priority_level = "low"
            signals.append({
                "ping_id": ping["ping_id"],
                "target": ping["target"],
                "label": ping["label"],
                "short_label": ping["short_label"],
                "base_probability": base_probability,
                "base_percent": round(base_probability * 100),
                "probability": round(adjusted_probability, 6),
                "percent": round(adjusted_probability * 100),
                "geometry": {
                    "type": "Point",
                    "coordinates": ping["coordinates"],
                },
                "anchor_asset_id": ping.get("anchor_asset_id"),
                "anchor_edge_id": anchor_edge_id,
                "exposure_asset_id": exposure_asset_id,
                "exposed_people": exposed_people,
                "local_flood_depth_m": local_depth,
                "local_danger_score": round(local_danger, 6),
                "priority_score": priority_score,
                "priority_rank": 0,
                "priority_level": priority_level,
                "score_type": "prototype_localized_risk_score",
                "activation_hours": ping["activation_hours"],
                "state": (
                    "active"
                    if simulation_time_hours >= ping["activation_hours"]
                    else "forecast"
                ),
                "reason": ping["reason"],
                "recommended_action": ping["recommended_action"],
                "source_type": "scenario_adjusted_model_prior",
            })

        ranked = sorted(
            signals,
            key=lambda signal: (
                -signal["priority_score"],
                -signal["local_danger_score"],
                -signal["exposed_people"],
                signal["ping_id"],
            ),
        )
        for rank, signal in enumerate(ranked, start=1):
            signal["priority_rank"] = rank
        return signals

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
            "flood_polygons": self.flood_polygons,
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
