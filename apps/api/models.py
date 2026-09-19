"""Strict wire models exposed by the ark API."""

from __future__ import annotations

from typing import List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict


class WireModel(BaseModel):
    """Reject undeclared response fields so contract drift fails visibly."""

    model_config = ConfigDict(extra="forbid")


class HealthResponse(WireModel):
    status: Literal["ok"]


class SourceMetadata(WireModel):
    source_type: Literal["modeled_input", "operator_injected", "derived_result"]
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    description: str


class PointGeometry(WireModel):
    type: Literal["Point"]
    coordinates: Tuple[float, float]


class LineStringGeometry(WireModel):
    type: Literal["LineString"]
    coordinates: List[Tuple[float, float]]


class PolygonGeometry(WireModel):
    type: Literal["Polygon"]
    coordinates: List[List[Tuple[float, float]]]


class ContextSource(WireModel):
    repository: str
    commit: str
    retrieved_on: str
    license: str
    note: Optional[str] = None


class ContextBoundaryProperties(WireModel):
    id: str
    name: str
    name_ne: Optional[str] = None
    feature_class: Literal["administrative_context"]
    admin_type: str
    source_feature_code: Optional[int] = None
    routing_enabled: Literal[False]
    flood_model_input: Literal[False]


class ContextBoundaryFeature(WireModel):
    type: Literal["Feature"]
    id: str
    properties: ContextBoundaryProperties
    geometry: PolygonGeometry


class ContextBoundaryCollection(WireModel):
    """Visual-only administrative reference. Never a routing or flood input."""

    type: Literal["FeatureCollection"]
    name: str
    bbox: Tuple[float, float, float, float]
    scenario_id: str
    data_classification: Literal["external_reference"]
    operational_use: Literal[False]
    source: ContextSource
    features: List[ContextBoundaryFeature]


class AssetProperties(WireModel):
    id: str
    asset_type: Literal["community", "hospital", "shelter", "bridge"]
    name: str
    node_id: Optional[str] = None
    edge_id: Optional[str] = None
    bank: Optional[Literal["north", "south"]] = None
    zone: Optional[str] = None
    elevation_band: Optional[str] = None
    population: Optional[int] = None
    vulnerable_population_proxy: Optional[int] = None
    capacity: Optional[int] = None
    open: Optional[bool] = None
    relative_exposure: Optional[Literal["medium", "high"]] = None


class AssetFeature(WireModel):
    type: Literal["Feature"]
    id: str
    properties: AssetProperties
    geometry: Union[PointGeometry, LineStringGeometry]


class AssetFeatureCollection(WireModel):
    type: Literal["FeatureCollection"]
    name: str
    scenario_id: str
    data_classification: Literal["modeled_synthetic_demo"]
    operational_use: Literal[False]
    features: List[AssetFeature]


class RoadProperties(WireModel):
    id: str
    edge_type: Literal["road", "bridge"]
    from_node_id: str
    to_node_id: str
    baseline_travel_minutes: float
    bidirectional: bool
    penalty_depth_m: float
    closure_depth_m: float
    penalty_multiplier: float
    critical: bool


class RoadFeature(WireModel):
    type: Literal["Feature"]
    id: str
    properties: RoadProperties
    geometry: LineStringGeometry


class RoadFeatureCollection(WireModel):
    type: Literal["FeatureCollection"]
    name: str
    scenario_id: str
    data_classification: Literal["modeled_synthetic_demo"]
    operational_use: Literal[False]
    features: List[RoadFeature]


class FloodFrameSummary(WireModel):
    frame_id: str
    simulation_time_hours: float
    observed_at: str
    rainfall_assumption: str
    rainfall_multiplier: float


class ImpactModelEvaluation(WireModel):
    unseen_district_roc_auc: float
    four_split_macro_roc_auc: float
    mean_rmse: float


class ImpactModelSummary(WireModel):
    event_id: str
    location: str
    model_name: str
    model_version: str
    status: Literal["research_only"]
    training_events: int
    feature_policy: str
    evaluation: ImpactModelEvaluation
    limitations: List[str]


class PredictionSignal(WireModel):
    ping_id: str
    target: Literal[
        "casualty_or_missing",
        "housing_damage",
        "transport_disruption",
        "severe_impact",
    ]
    label: str
    short_label: str
    base_probability: float
    base_percent: int
    probability: float
    percent: int
    geometry: PointGeometry
    anchor_asset_id: Optional[str]
    anchor_edge_id: str
    local_flood_depth_m: float
    activation_hours: float
    state: Literal["forecast", "active"]
    recommended_action: str
    source_type: Literal["scenario_adjusted_model_prior"]


class EvacuationAssignment(WireModel):
    community_id: str
    shelter_id: str
    people: int
    departure_offset_minutes: float
    route_preference: Literal["shortest_safe"]


class ResponsePlan(WireModel):
    plan_id: str
    name: str
    evaluation_deadline_minutes: float
    assumptions: List[str]
    assignments: List[EvacuationAssignment]


class StateChange(WireModel):
    change_type: Literal["force_close_edge"]
    edge_id: str
    reason: str


class IncidentEvent(WireModel):
    event_id: str
    event_type: Literal["bridge_failure", "increased_rainfall"]
    effective_at_hours: float
    occurred_at: str
    source_type: Literal["operator_injected"]
    reliability: Literal["confirmed", "probable", "unverified"]
    description: str
    changes: List[StateChange]


class ScenarioBootstrapResponse(WireModel):
    schema_version: Literal["1.0.0"]
    scenario_id: str
    name: str
    description: str
    data_classification: Literal["modeled_synthetic_demo"]
    operational_use: Literal[False]
    initial_world_state_version: str
    initial_frame_id: str
    evaluation_horizon_hours: float
    assets: AssetFeatureCollection
    road_network: RoadFeatureCollection
    context_boundaries: ContextBoundaryCollection
    available_frames: List[FloodFrameSummary]
    events: List[IncidentEvent]
    plans: List[ResponsePlan]
    impact_model: ImpactModelSummary


class DerivedEdgeState(WireModel):
    edge_id: str
    edge_type: Literal["road", "bridge"]
    status: Literal["open", "restricted", "closed"]
    closure_reason: Optional[str]
    flood_depth_m: float
    baseline_travel_minutes: float
    penalty_depth_m: float
    closure_depth_m: float
    penalty_multiplier: float
    effective_travel_minutes: Optional[float]
    source_frame_id: str
    originating_event_id: Optional[str]
    critical: bool


class RouteResult(WireModel):
    source_node_id: str
    destination_node_id: str
    node_ids: List[str]
    edge_ids: List[str]
    travel_minutes: float


class ShelterRoute(WireModel):
    shelter_id: str
    route: RouteResult


class CommunityAccessState(WireModel):
    community_id: str
    reachable_shelter_ids: List[str]
    shelter_routes: List[ShelterRoute]
    hospital_accessible: bool
    hospital_route: Optional[RouteResult]
    isolated: bool
    time_to_isolation_hours: Optional[float]


class Hazard(WireModel):
    hazard_id: str
    priority: Literal["critical", "high", "medium"]
    hazard_type: Literal[
        "route_closed", "route_restricted", "community_isolated"
    ]
    asset_id: str
    source_frame_id: str
    source_event_id: Optional[str]
    description: str


class PlanMetrics(WireModel):
    people_isolated: int
    people_evacuated_by_deadline: int
    evacuation_completion_minutes: Optional[float]
    critical_routes_lost: int
    hospital_accessible: bool
    hospital_accessible_communities: int
    shelter_overload: int
    plan_viable: bool


class AssignmentResult(EvacuationAssignment):
    route: Optional[RouteResult]
    arrival_minutes: Optional[float]
    meets_deadline: bool
    people_evacuated: int


class PlanResult(WireModel):
    result_id: str
    plan_id: str
    plan_name: str
    source_world_state_version: str
    status: Literal["current", "stale", "superseded"]
    calculated_at: str
    assumptions: List[str]
    invalidation_reason: Optional[str]
    metrics: PlanMetrics
    assignment_results: List[AssignmentResult]


class WorldStateSnapshot(WireModel):
    schema_version: Literal["1.0.0"]
    scenario_id: str
    world_state_version: str
    observed_at: str
    calculated_at: str
    simulation_time_hours: float
    frame_id: str
    data_classification: Literal["modeled_synthetic_demo"]
    operational_use: Literal[False]
    active_event_ids: List[str]
    rainfall_assumption: str
    rainfall_multiplier: float
    edge_states: List[DerivedEdgeState]
    community_access: List[CommunityAccessState]
    hazards: List[Hazard]
    prediction_signals: List[PredictionSignal]
    plan_results: List[PlanResult]


class EventRecomputeResponse(WireModel):
    scenario_id: str
    event: IncidentEvent
    previous_world_state_version: str
    updated_world_state: WorldStateSnapshot
    stale_plan_results: List[PlanResult]
    recomputed_plan_results: List[PlanResult]
