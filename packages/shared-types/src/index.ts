export type DataClassification =
  | "modeled_synthetic_demo"
  | "external_reference";

export type EdgeStatus = "open" | "restricted" | "closed";
export type PlanResultStatus = "current" | "stale" | "superseded";

export interface HealthResponse {
  status: "ok";
}

export type Position = [number, number];

export interface PointGeometry {
  type: "Point";
  coordinates: Position;
}

export interface LineStringGeometry {
  type: "LineString";
  coordinates: Position[];
}

export interface PolygonGeometry {
  type: "Polygon";
  coordinates: Position[][];
}

export interface ContextSource {
  repository: string;
  commit: string;
  retrieved_on: string;
  license: string;
  note?: string | null;
}

export interface ContextBoundaryProperties {
  id: string;
  name: string;
  name_ne?: string | null;
  feature_class: "administrative_context";
  admin_type: string;
  source_feature_code?: number | null;
  routing_enabled: false;
  flood_model_input: false;
}

export interface ContextBoundaryFeature {
  type: "Feature";
  id: string;
  properties: ContextBoundaryProperties;
  geometry: PolygonGeometry;
}

/** Visual-only administrative reference. Never a routing or flood input. */
export interface ContextBoundaryCollection {
  type: "FeatureCollection";
  name: string;
  bbox: [number, number, number, number];
  scenario_id: string;
  data_classification: "external_reference";
  operational_use: false;
  source: ContextSource;
  features: ContextBoundaryFeature[];
}

export interface AssetProperties {
  id: string;
  asset_type: "community" | "hospital" | "shelter" | "bridge";
  name: string;
  node_id?: string;
  edge_id?: string;
  bank?: "north" | "south";
  zone?: string;
  elevation_band?: string;
  population?: number;
  vulnerable_population_proxy?: number;
  capacity?: number;
  open?: boolean;
  relative_exposure?: "medium" | "high";
}

export interface AssetFeature {
  type: "Feature";
  id: string;
  properties: AssetProperties;
  geometry: PointGeometry | LineStringGeometry;
}

export interface AssetFeatureCollection {
  type: "FeatureCollection";
  name: string;
  scenario_id: string;
  data_classification: "modeled_synthetic_demo";
  operational_use: false;
  features: AssetFeature[];
}

export interface RoadProperties {
  id: string;
  edge_type: "road" | "bridge";
  from_node_id: string;
  to_node_id: string;
  baseline_travel_minutes: number;
  bidirectional: boolean;
  penalty_depth_m: number;
  closure_depth_m: number;
  penalty_multiplier: number;
  critical: boolean;
}

export interface RoadFeature {
  type: "Feature";
  id: string;
  properties: RoadProperties;
  geometry: LineStringGeometry;
}

export interface RoadFeatureCollection {
  type: "FeatureCollection";
  name: string;
  scenario_id: string;
  data_classification: "modeled_synthetic_demo";
  operational_use: false;
  features: RoadFeature[];
}

export interface SourceMetadata {
  source_type: "modeled_input" | "operator_injected" | "derived_result";
  model_name?: string;
  model_version?: string;
  description: string;
}

export interface FloodEdgeCondition {
  edge_id: string;
  flood_depth_m: number;
}

export interface FloodFrame {
  frame_id: string;
  simulation_time_hours: number;
  observed_at: string;
  rainfall_assumption: string;
  rainfall_multiplier: number;
  source: SourceMetadata;
  edge_conditions: FloodEdgeCondition[];
}

export interface FloodFrameSummary {
  frame_id: string;
  simulation_time_hours: number;
  observed_at: string;
  rainfall_assumption: string;
  rainfall_multiplier: number;
}

export interface DerivedEdgeState {
  edge_id: string;
  edge_type: "road" | "bridge";
  status: EdgeStatus;
  closure_reason: string | null;
  flood_depth_m: number;
  baseline_travel_minutes: number;
  penalty_depth_m: number;
  closure_depth_m: number;
  penalty_multiplier: number;
  effective_travel_minutes: number | null;
  source_frame_id: string;
  originating_event_id: string | null;
  critical: boolean;
}

export interface RouteResult {
  source_node_id: string;
  destination_node_id: string;
  node_ids: string[];
  edge_ids: string[];
  travel_minutes: number;
}

export interface CommunityAccessState {
  community_id: string;
  isolated: boolean;
  reachable_shelter_ids: string[];
  shelter_routes: Array<{ shelter_id: string; route: RouteResult }>;
  hospital_accessible: boolean;
  hospital_route: RouteResult | null;
  time_to_isolation_hours: number | null;
}

export interface Hazard {
  hazard_id: string;
  priority: "critical" | "high" | "medium";
  hazard_type: "route_closed" | "route_restricted" | "community_isolated";
  asset_id: string;
  source_frame_id: string;
  source_event_id: string | null;
  description: string;
}

export interface WorldStateSnapshot {
  schema_version: "1.0.0";
  scenario_id: string;
  world_state_version: string;
  observed_at: string;
  calculated_at: string;
  simulation_time_hours: number;
  frame_id: string;
  data_classification: "modeled_synthetic_demo";
  operational_use: false;
  active_event_ids: string[];
  rainfall_assumption: string;
  rainfall_multiplier: number;
  edge_states: DerivedEdgeState[];
  community_access: CommunityAccessState[];
  hazards: Hazard[];
  plan_results: PlanResult[];
}

export interface EvacuationAssignment {
  community_id: string;
  shelter_id: string;
  people: number;
  departure_offset_minutes: number;
  route_preference: "shortest_safe";
}

export interface ResponsePlan {
  plan_id: string;
  name: string;
  evaluation_deadline_minutes: number;
  assumptions: string[];
  assignments: EvacuationAssignment[];
}

export interface PlanMetrics {
  people_isolated: number;
  people_evacuated_by_deadline: number;
  evacuation_completion_minutes: number | null;
  critical_routes_lost: number;
  hospital_accessible: boolean;
  hospital_accessible_communities: number;
  shelter_overload: number;
  plan_viable: boolean;
}

export interface AssignmentResult extends EvacuationAssignment {
  route: RouteResult | null;
  arrival_minutes: number | null;
  meets_deadline: boolean;
  people_evacuated: number;
}

export interface PlanResult {
  result_id: string;
  plan_id: string;
  plan_name: string;
  source_world_state_version: string;
  status: PlanResultStatus;
  calculated_at: string;
  assumptions: string[];
  invalidation_reason: string | null;
  metrics: PlanMetrics;
  assignment_results: AssignmentResult[];
}

export interface StateChange {
  change_type: "force_close_edge";
  edge_id: string;
  reason: string;
}

export interface IncidentEvent {
  event_id: string;
  event_type: "bridge_failure" | "increased_rainfall";
  effective_at_hours: number;
  occurred_at: string;
  source_type: "operator_injected";
  reliability: "confirmed" | "probable" | "unverified";
  description: string;
  changes: StateChange[];
}

export interface ScenarioBootstrapResponse {
  schema_version: "1.0.0";
  scenario_id: string;
  name: string;
  description: string;
  data_classification: "modeled_synthetic_demo";
  operational_use: false;
  initial_world_state_version: string;
  initial_frame_id: string;
  evaluation_horizon_hours: number;
  assets: AssetFeatureCollection;
  road_network: RoadFeatureCollection;
  context_boundaries: ContextBoundaryCollection;
  available_frames: FloodFrameSummary[];
  events: IncidentEvent[];
  plans: ResponsePlan[];
}

export interface EventRecomputeResponse {
  scenario_id: string;
  event: IncidentEvent;
  previous_world_state_version: string;
  updated_world_state: WorldStateSnapshot;
  stale_plan_results: PlanResult[];
  recomputed_plan_results: PlanResult[];
}
