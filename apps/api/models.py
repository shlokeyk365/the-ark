"""Strict wire models exposed by the ark API."""

from __future__ import annotations

from typing import List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field


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


class FloodPolygonProperties(WireModel):
    id: str
    frame_id: str
    simulation_time_hours: float
    depth_min_m: float
    depth_max_m: float
    band_label: str
    surface_kind: Literal["curated_synthetic_surface"]
    source_type: Literal["modeled_input"]


class FloodPolygonFeature(WireModel):
    type: Literal["Feature"]
    id: str
    properties: FloodPolygonProperties
    geometry: PolygonGeometry


class FloodPolygonCollection(WireModel):
    """Synthetic situational-awareness surface; never a routing input."""

    type: Literal["FeatureCollection"]
    name: str
    scenario_id: str
    data_classification: Literal["modeled_synthetic_demo"]
    operational_use: Literal[False]
    source: SourceMetadata
    features: List[FloodPolygonFeature]


class FloodFrameSummary(WireModel):
    frame_id: str
    simulation_time_hours: float
    observed_at: str
    rainfall_assumption: str
    rainfall_multiplier: float


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
    flood_polygons: FloodPolygonCollection
    context_boundaries: ContextBoundaryCollection
    available_frames: List[FloodFrameSummary]
    events: List[IncidentEvent]
    plans: List[ResponsePlan]


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
    plan_results: List[PlanResult]


class EventRecomputeResponse(WireModel):
    scenario_id: str
    event: IncidentEvent
    previous_world_state_version: str
    updated_world_state: WorldStateSnapshot
    stale_plan_results: List[PlanResult]
    recomputed_plan_results: List[PlanResult]


class SimulationRunRequest(WireModel):
    event_ids: List[str] = Field(default_factory=list)


class SimulationRunInput(WireModel):
    scenario_id: str
    event_ids: List[str]
    evaluation_horizon_hours: float
    fixture_sha256: str
    impact_prior_sha256: Optional[str]
    impact_prior_used: Literal[False]


class ReportSummaryMetrics(WireModel):
    peak_flood_depth_m: float
    peak_isolated_people: int
    peak_isolated_communities: int
    peak_critical_routes_lost: int
    first_isolation_hours: Optional[float]
    viable_plans_at_horizon: int


class ReportChange(WireModel):
    change_id: str
    at_hours: float
    category: Literal["infrastructure", "community", "plan", "event"]
    subject_id: str
    subject_name: str
    description: str
    before_value: str
    after_value: str
    comparison: Literal["timeline", "baseline_counterfactual"]
    source_event_id: Optional[str]


class CommunityImpactReport(WireModel):
    community_id: str
    community_name: str
    population: int
    first_isolated_at_hours: Optional[float]
    hospital_access_lost_at_hours: Optional[float]
    horizon_isolated: bool
    horizon_hospital_accessible: bool
    horizon_reachable_shelter_ids: List[str]
    analysis: str


class PlanAnalysisReport(WireModel):
    plan_id: str
    plan_name: str
    baseline_metrics: PlanMetrics
    horizon_metrics: PlanMetrics
    people_evacuated_change: int
    people_isolated_change: int
    critical_routes_lost_change: int
    shelter_overload_change: int
    viability_changed: bool
    analysis: str


class ReportProvenance(WireModel):
    input_fingerprint: str
    fixture_sha256: str
    impact_prior_sha256: Optional[str]
    impact_prior_used: Literal[False]
    world_state_versions: List[str]
    engine_version: Literal["reports-1.0.0"]
    data_classification: Literal["modeled_synthetic_demo"]
    operational_use: Literal[False]


class SimulationReport(WireModel):
    schema_version: Literal["1.0.0"]
    report_id: str
    run_id: str
    scenario_id: str
    status: Literal["completed"]
    generated_at: str
    title: str
    event_ids: List[str]
    summary: ReportSummaryMetrics
    narrative: List[str]
    changes: List[ReportChange]
    community_impacts: List[CommunityImpactReport]
    plan_analysis: List[PlanAnalysisReport]
    assumptions: List[str]
    limitations: List[str]
    provenance: ReportProvenance


class SimulationRun(WireModel):
    schema_version: Literal["1.0.0"]
    run_id: str
    report_id: str
    scenario_id: str
    status: Literal["completed"]
    started_at: str
    completed_at: str
    input: SimulationRunInput
    input_fingerprint: str
    snapshots: List[WorldStateSnapshot]
    report: SimulationReport


class SimulationRunSummary(WireModel):
    run_id: str
    report_id: str
    scenario_id: str
    status: Literal["completed"]
    completed_at: str
    title: str
    event_ids: List[str]
    input_fingerprint: str
    summary: ReportSummaryMetrics
