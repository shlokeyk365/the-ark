import type {
  AssetFeature,
  CommunityAccessState,
  DerivedEdgeState,
  PlanResult,
  Position,
  RoadFeature,
  RouteResult,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

/**
 * GeoJSON the MapLibre layers consume. Everything here is a pure projection of
 * API payloads into map-ready features — no domain logic, no thresholds, no
 * routing. The backend remains the only place that decides what is closed,
 * reachable, or isolated.
 *
 * Properties are named for what the map draws with them (`risk`, `route_role`,
 * `label`), so the layer expressions never have to re-derive a judgement the
 * world state already made.
 */

type Json = string | number | boolean | null;

export interface MapFeature {
  type: "Feature";
  id?: string | number;
  properties: Record<string, Json>;
  geometry:
    | { type: "Point"; coordinates: Position }
    | { type: "LineString"; coordinates: Position[] }
    | { type: "Polygon"; coordinates: Position[][] };
}

export interface MapFeatureCollection {
  type: "FeatureCollection";
  features: MapFeature[];
}

export const EMPTY: MapFeatureCollection = { type: "FeatureCollection", features: [] };

function midpoint(coordinates: Position[]): Position {
  if (coordinates.length === 0) return [0, 0];
  if (coordinates.length === 1) return coordinates[0];
  const first = coordinates[0];
  const last = coordinates[coordinates.length - 1];
  return [(first[0] + last[0]) / 2, (first[1] + last[1]) / 2];
}

function sameCoordinate(a: Position | undefined, b: Position | undefined): boolean {
  return Boolean(a && b && a[0] === b[0] && a[1] === b[1]);
}

/* ------------------------------------------------------------------ naming */

/**
 * Human-readable name for every routing node.
 *
 * Communities, shelters and the hospital supply their own. Junctions have no
 * asset behind them, so they fall back to a readable rendering of the node id
 * rather than being shown as `ktp-node-junction-nw`.
 */
export function nodeLabels(bootstrap: ScenarioBootstrapResponse): Map<string, string> {
  const labels = new Map<string, string>();

  bootstrap.assets.features.forEach((feature) => {
    const nodeId = feature.properties.node_id;
    if (nodeId) labels.set(nodeId, feature.properties.name);
  });

  bootstrap.road_network.features.forEach((feature) => {
    [feature.properties.from_node_id, feature.properties.to_node_id].forEach((nodeId) => {
      if (labels.has(nodeId)) return;
      const tail = nodeId.split("-").slice(2).join(" ");
      labels.set(nodeId, tail ? `${tail} junction` : nodeId);
    });
  });

  return labels;
}

/**
 * Corridor description for a road edge, e.g. "North Market → nw junction".
 *
 * Used in the inspector and incident panel. The fixture carries no street
 * names, so nothing here invents one — the endpoints are stated as they are.
 */
export function edgeLabel(
  bootstrap: ScenarioBootstrapResponse,
  labels: Map<string, string>,
  edgeId: string,
): string {
  const bridge = bootstrap.assets.features.find(
    (feature) => feature.properties.edge_id === edgeId,
  );
  if (bridge) return bridge.properties.name;

  const road = bootstrap.road_network.features.find((feature) => feature.id === edgeId);
  if (!road) return edgeId;
  const from = labels.get(road.properties.from_node_id) ?? road.properties.from_node_id;
  const to = labels.get(road.properties.to_node_id) ?? road.properties.to_node_id;
  return `${from} → ${to}`;
}

/* ------------------------------------------------------------------ roads */

/** How a road segment should read on the map: clear, impaired, or blocked. */
function edgeRisk(state: DerivedEdgeState | undefined): "clear" | "impaired" | "blocked" {
  if (state?.status === "closed") return "blocked";
  if (state?.status === "restricted") return "impaired";
  return "clear";
}

export function roadsCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
  routeEdgeIds: Set<string>,
): MapFeatureCollection {
  const stateById = new Map(
    worldState.edge_states.map((edge) => [edge.edge_id, edge]),
  );
  const bridgeNames = new Map(
    bootstrap.assets.features
      .filter((feature) => feature.properties.edge_id)
      .map((feature) => [feature.properties.edge_id as string, feature.properties.name]),
  );

  return {
    type: "FeatureCollection",
    features: bootstrap.road_network.features.map((feature) => {
      const state = stateById.get(feature.id);
      const risk = edgeRisk(state);
      const depth = state?.flood_depth_m ?? 0;

      return {
        type: "Feature",
        id: feature.id,
        geometry: { type: "LineString", coordinates: feature.geometry.coordinates },
        properties: {
          id: feature.id,
          name: bridgeNames.get(feature.id) ?? null,
          edge_type: feature.properties.edge_type,
          is_bridge: feature.properties.edge_type === "bridge",
          status: state?.status ?? "open",
          risk,
          flood_depth_m: depth,
          // Drives the wet-road underlay; below this the water is not worth ink.
          submerged: depth >= 0.05,
          travel_minutes: state?.effective_travel_minutes ?? null,
          baseline_travel_minutes: feature.properties.baseline_travel_minutes,
          closure_reason: state?.closure_reason ?? null,
          originating_event_id: state?.originating_event_id ?? null,
          operator_injected: state?.originating_event_id !== null,
          critical: Boolean(state?.critical ?? feature.properties.critical),
          on_route: routeEdgeIds.has(feature.id),
          status_label:
            risk === "blocked"
              ? "IMPASSABLE"
              : risk === "impaired"
                ? "IMPAIRED"
                : "",
          depth_label: depth > 0 ? `${depth.toFixed(2)} m water` : "",
        },
      };
    }),
  };
}

/**
 * Closure and restriction symbols, placed on the affected segment itself.
 *
 * A road hazard belongs on the road, not on a marker floating beside it, so
 * each point sits at the midpoint of the edge it describes.
 */
export function roadHazardsCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
): MapFeatureCollection {
  const geometryById = new Map(
    bootstrap.road_network.features.map((feature) => [
      feature.id,
      feature.geometry.coordinates,
    ]),
  );
  const bridgeEdgeIds = new Set(
    bootstrap.assets.features
      .filter((feature) => feature.properties.asset_type === "bridge")
      .map((feature) => feature.properties.edge_id ?? feature.id),
  );

  return {
    type: "FeatureCollection",
    features: worldState.edge_states.flatMap((state) => {
      if (state.status === "open") return [];
      // Bridges carry their own symbol and label, so they are not doubled here.
      if (bridgeEdgeIds.has(state.edge_id)) return [];
      const coordinates = geometryById.get(state.edge_id);
      if (!coordinates) return [];

      return [
        {
          type: "Feature" as const,
          id: `closure-${state.edge_id}`,
          geometry: { type: "Point" as const, coordinates: midpoint(coordinates) },
          properties: {
            id: state.edge_id,
            status: state.status,
            risk: edgeRisk(state),
            flood_depth_m: state.flood_depth_m,
            operator_injected: state.originating_event_id !== null,
          },
        },
      ];
    }),
  };
}

/* ----------------------------------------------------------------- routes */

export type RouteRole = "active" | "alternate" | "blocked";

interface OrientedRoute {
  coordinates: Position[];
  blocked: boolean;
}

/**
 * Stitch a route's edges into one line running in travel order.
 *
 * Edge geometry is stored in its own direction, which is not necessarily the
 * direction the route traverses it. Without this the chevrons would point
 * backwards on roughly half the segments.
 */
function orientedRoute(
  roadById: Map<string, RoadFeature>,
  statusById: Map<string, DerivedEdgeState>,
  route: RouteResult,
): OrientedRoute | null {
  const coordinates: Position[] = [];
  let blocked = false;

  route.edge_ids.forEach((edgeId, index) => {
    const road = roadById.get(edgeId);
    if (!road) return;
    if (statusById.get(edgeId)?.status === "closed") blocked = true;

    const entryNode = route.node_ids[index];
    const forward = road.properties.from_node_id === entryNode;
    const line = forward
      ? road.geometry.coordinates
      : [...road.geometry.coordinates].reverse();

    const segment = sameCoordinate(coordinates[coordinates.length - 1], line[0])
      ? line.slice(1)
      : line;
    coordinates.push(...segment);
  });

  return coordinates.length > 1 ? { coordinates, blocked } : null;
}

function planRoutes(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
  plan: PlanResult | undefined,
  role: Exclude<RouteRole, "blocked">,
): MapFeature[] {
  if (!plan) return [];

  const roadById = new Map(
    bootstrap.road_network.features.map((feature) => [feature.id, feature]),
  );
  const statusById = new Map(
    worldState.edge_states.map((edge) => [edge.edge_id, edge]),
  );
  const assetNames = new Map(
    bootstrap.assets.features.map((feature) => [feature.id, feature.properties.name]),
  );

  return plan.assignment_results.flatMap((assignment) => {
    if (!assignment.route) return [];
    const oriented = orientedRoute(roadById, statusById, assignment.route);
    if (!oriented) return [];

    return [
      {
        type: "Feature" as const,
        id: `${plan.plan_id}-${assignment.community_id}-${assignment.shelter_id}`,
        geometry: { type: "LineString" as const, coordinates: oriented.coordinates },
        properties: {
          id: `${plan.plan_id}-${assignment.community_id}-${assignment.shelter_id}`,
          plan_id: plan.plan_id,
          plan_name: plan.plan_name,
          community_id: assignment.community_id,
          shelter_id: assignment.shelter_id,
          role: oriented.blocked ? ("blocked" as RouteRole) : role,
          people: assignment.people,
          travel_minutes: assignment.route.travel_minutes,
          arrival_minutes: assignment.arrival_minutes,
          meets_deadline: assignment.meets_deadline,
          label: `${assetNames.get(assignment.shelter_id) ?? assignment.shelter_id} · ${Math.round(
            assignment.route.travel_minutes,
          )} min`,
        },
      },
    ];
  });
}

/** Routes the selected plan would actually run. */
export function routeCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
  selectedPlan: PlanResult | undefined,
): MapFeatureCollection {
  return {
    type: "FeatureCollection",
    features: planRoutes(bootstrap, worldState, selectedPlan, "active"),
  };
}

/**
 * Routes the plans the operator did not select would run.
 *
 * Drawn dashed and dimmed, and hidden by default, so the comparison is
 * available without turning the map into a route tangle.
 */
export function alternateRouteCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
  selectedPlan: PlanResult | undefined,
): MapFeatureCollection {
  const active = new Set(
    planRoutes(bootstrap, worldState, selectedPlan, "active").map((feature) =>
      String(feature.properties.community_id),
    ),
  );

  return {
    type: "FeatureCollection",
    features: worldState.plan_results
      .filter((plan) => plan.plan_id !== selectedPlan?.plan_id)
      .flatMap((plan) => planRoutes(bootstrap, worldState, plan, "alternate"))
      // An alternate that duplicates the active assignment adds nothing.
      .filter((feature) => !active.has(String(feature.properties.community_id))),
  };
}

export function routeEdgeIdsFor(plan: PlanResult | undefined): Set<string> {
  const edgeIds = new Set<string>();
  plan?.assignment_results.forEach((assignment) => {
    assignment.route?.edge_ids.forEach((edgeId) => edgeIds.add(edgeId));
  });
  return edgeIds;
}

/* ----------------------------------------------------------------- assets */

/**
 * Risk band for a community marker.
 *
 * `isolated` is the world state's own verdict; `at_risk` covers a community
 * that still has a way out but has already lost the hospital or is inside the
 * modeled isolation window.
 */
function communityRisk(access: CommunityAccessState | undefined): string {
  if (!access) return "clear";
  if (access.isolated) return "isolated";
  if (!access.hospital_accessible || access.reachable_shelter_ids.length === 0) {
    return "at_risk";
  }
  return access.time_to_isolation_hours !== null ? "at_risk" : "clear";
}

export function assetsCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
): MapFeatureCollection {
  const accessById = new Map(
    worldState.community_access.map((access) => [access.community_id, access]),
  );
  const reachableShelters = new Set(
    worldState.community_access.flatMap((access) => access.reachable_shelter_ids),
  );
  const hospitalReachable = worldState.community_access.some(
    (access) => access.hospital_accessible,
  );

  return {
    type: "FeatureCollection",
    features: bootstrap.assets.features
      .filter((feature): feature is AssetFeature & { geometry: { type: "Point"; coordinates: Position } } =>
        feature.geometry.type === "Point",
      )
      .map((feature) => {
        const access = accessById.get(feature.id);
        const assetType = feature.properties.asset_type;
        const reachable =
          assetType === "shelter"
            ? reachableShelters.has(feature.id)
            : assetType === "hospital"
              ? hospitalReachable
              : true;

        return {
          type: "Feature",
          id: feature.id,
          geometry: {
            type: "Point",
            coordinates: feature.geometry.coordinates,
          },
          properties: {
            id: feature.id,
            name: feature.properties.name,
            asset_type: assetType,
            population: feature.properties.population ?? null,
            capacity: feature.properties.capacity ?? null,
            reachable,
            isolated: Boolean(access?.isolated),
            risk: assetType === "community" ? communityRisk(access) : "clear",
            hospital_accessible: access ? access.hospital_accessible : true,
            reachable_shelters: access?.reachable_shelter_ids.length ?? 0,
            time_to_isolation_hours: access?.time_to_isolation_hours ?? null,
            /* Secondary label lines, revealed as the operator zooms in. */
            detail_label:
              assetType === "community" && feature.properties.population
                ? `${feature.properties.population.toLocaleString()} residents`
                : assetType === "shelter" && feature.properties.capacity
                  ? `capacity ${feature.properties.capacity.toLocaleString()}`
                  : "",
            status_label: access?.isolated
              ? "ISOLATED"
              : assetType === "shelter" && !reachable
                ? "UNREACHABLE"
                : "",
          },
        };
      }),
  };
}

/**
 * Bridge decks, drawn from the bridge's own geometry.
 *
 * A bridge failure is a failure of a specific span, so the warning is placed on
 * that span rather than on a circle nearby.
 */
export function bridgeLinesCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
): MapFeatureCollection {
  const stateById = new Map(
    worldState.edge_states.map((edge) => [edge.edge_id, edge]),
  );

  return {
    type: "FeatureCollection",
    features: bootstrap.assets.features
      .filter(
        (feature) =>
          feature.properties.asset_type === "bridge" &&
          feature.geometry.type === "LineString",
      )
      .map((feature) => {
        const edgeId = feature.properties.edge_id ?? feature.id;
        const state = stateById.get(edgeId);
        return {
          type: "Feature",
          id: feature.id,
          geometry: {
            type: "LineString",
            coordinates: feature.geometry.coordinates as Position[],
          },
          properties: {
            id: feature.id,
            edge_id: edgeId,
            name: feature.properties.name,
            status: state?.status ?? "open",
            risk: edgeRisk(state),
            flood_depth_m: state?.flood_depth_m ?? 0,
            operator_injected: state?.originating_event_id !== null,
          },
        };
      }),
  };
}

/** Bridge symbol and label anchor: the midpoint of the deck. */
export function bridgesCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
): MapFeatureCollection {
  return {
    type: "FeatureCollection",
    features: bridgeLinesCollection(bootstrap, worldState).features.map((feature) => {
      const depth = Number(feature.properties.flood_depth_m ?? 0);
      const risk = String(feature.properties.risk);
      return {
        ...feature,
        geometry: {
          type: "Point" as const,
          coordinates: midpoint(
            (feature.geometry as { coordinates: Position[] }).coordinates,
          ),
        },
        properties: {
          ...feature.properties,
          status_label:
            risk === "blocked" ? "BLOCKED" : risk === "impaired" ? "IMPAIRED" : "OPEN",
          depth_label: depth > 0 ? `${depth.toFixed(2)} m water` : "",
        },
      };
    }),
  };
}

/* ---------------------------------------------------------------- hazards */

const HAZARD_TITLES: Record<string, string> = {
  route_closed: "Route impassable",
  route_restricted: "Route impaired",
  community_isolated: "Community isolated",
};

export function hazardsCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
): MapFeatureCollection {
  const assetPoints = new Map<string, Position>();
  const labels = nodeLabels(bootstrap);

  bootstrap.assets.features.forEach((feature) => {
    assetPoints.set(
      feature.id,
      feature.geometry.type === "Point"
        ? (feature.geometry.coordinates as Position)
        : midpoint(feature.geometry.coordinates as Position[]),
    );
  });
  bootstrap.road_network.features.forEach((feature) => {
    if (!assetPoints.has(feature.id)) {
      assetPoints.set(feature.id, midpoint(feature.geometry.coordinates));
    }
  });

  return {
    type: "FeatureCollection",
    features: worldState.hazards.flatMap((hazard) => {
      const coordinates = assetPoints.get(hazard.asset_id);
      if (!coordinates) return [];

      return [
        {
          type: "Feature" as const,
          id: hazard.hazard_id,
          geometry: { type: "Point" as const, coordinates },
          properties: {
            id: hazard.hazard_id,
            hazard_id: hazard.hazard_id,
            priority: hazard.priority,
            hazard_type: hazard.hazard_type,
            asset_id: hazard.asset_id,
            // Operational wording, never "#3 ROAD 12%".
            title: HAZARD_TITLES[hazard.hazard_type] ?? "Hazard",
            subject: edgeLabel(bootstrap, labels, hazard.asset_id),
            description: hazard.description ?? "",
            operator_injected: hazard.source_event_id !== null,
          },
        },
      ];
    }),
  };
}

/* ------------------------------------------------------------------ flood */

const CHANNEL_CENTRELINE: Position[] = [
  [85.289, 27.688],
  [85.301, 27.685],
  [85.311, 27.686],
  [85.321, 27.689],
  [85.332, 27.687],
  [85.343, 27.688],
  [85.354, 27.682],
  [85.368, 27.684],
];

/** Catmull-Rom resampling so the rendered bank reads as a river, not a polyline. */
function smoothCentreline(points: Position[], samplesPerSegment = 14): Position[] {
  const padded = [points[0], ...points, points[points.length - 1]];
  const output: Position[] = [];

  for (let index = 1; index < padded.length - 2; index += 1) {
    const p0 = padded[index - 1];
    const p1 = padded[index];
    const p2 = padded[index + 1];
    const p3 = padded[index + 2];

    for (let step = 0; step < samplesPerSegment; step += 1) {
      const t = step / samplesPerSegment;
      const t2 = t * t;
      const t3 = t2 * t;
      const axis = (a: number, b: number, c: number, d: number) =>
        0.5 *
        (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
      output.push([axis(p0[0], p1[0], p2[0], p3[0]), axis(p0[1], p1[1], p2[1], p3[1])]);
    }
  }

  output.push(points[points.length - 1]);
  return output;
}

const SMOOTHED_CENTRELINE = smoothCentreline(CHANNEL_CENTRELINE);

function floodCollectionForFrame(
  bootstrap: ScenarioBootstrapResponse,
  frameId: string,
  displayState: "current" | "forecast",
): MapFeatureCollection {
  return {
    type: "FeatureCollection",
    features: bootstrap.flood_polygons.features
      .filter((feature) => feature.properties.frame_id === frameId)
      .map((feature) => ({
        type: "Feature",
        id: `${displayState}-${feature.id}`,
        geometry: feature.geometry,
        properties: {
          ...feature.properties,
          display_state: displayState,
          provenance: feature.properties.surface_kind,
          source_description: bootstrap.flood_polygons.source.description,
        },
      })),
  };
}

/** Curated depth bands for the frame currently on screen. */
export function floodNowCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
): MapFeatureCollection {
  return floodCollectionForFrame(bootstrap, worldState.frame_id, "current");
}

/** Curated depth bands for the last frame in the horizon. */
export function floodForecastCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
  horizonState: WorldStateSnapshot | undefined,
): MapFeatureCollection {
  if (!horizonState || horizonState.frame_id === worldState.frame_id) return EMPTY;
  return floodCollectionForFrame(bootstrap, horizonState.frame_id, "forecast");
}

/**
 * River centreline, doubling as the anchor for flow arrows.
 *
 * The chevrons run in the digitised order of the centreline, which is the
 * downstream direction for the Kantipur fixture.
 */
export function channelCollection(): MapFeatureCollection {
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        id: "channel",
        geometry: { type: "LineString", coordinates: SMOOTHED_CENTRELINE },
        properties: { id: "channel" },
      },
    ],
  };
}

/* ---------------------------------------------------------------- context */

export function contextCollection(
  bootstrap: ScenarioBootstrapResponse,
): MapFeatureCollection {
  return {
    type: "FeatureCollection",
    features: bootstrap.context_boundaries.features.map((feature) => ({
      type: "Feature",
      id: feature.id,
      geometry: { type: "Polygon", coordinates: feature.geometry.coordinates },
      properties: {
        id: feature.properties.id,
        name: feature.properties.name,
      },
    })),
  };
}

/* ----------------------------------------------------------------- bounds */

export function scenarioBounds(
  bootstrap: ScenarioBootstrapResponse,
): [[number, number], [number, number]] {
  const positions: Position[] = [];
  bootstrap.road_network.features.forEach((feature) => {
    positions.push(...feature.geometry.coordinates);
  });
  bootstrap.assets.features.forEach((feature) => {
    if (feature.geometry.type === "Point") {
      positions.push(feature.geometry.coordinates);
    } else {
      positions.push(...(feature.geometry.coordinates as Position[]));
    }
  });
  bootstrap.flood_polygons.features.forEach((feature) => {
    feature.geometry.coordinates.forEach((ring) => positions.push(...ring));
  });

  const longitudes = positions.map(([longitude]) => longitude);
  const latitudes = positions.map(([, latitude]) => latitude);

  return [
    [Math.min(...longitudes), Math.min(...latitudes)],
    [Math.max(...longitudes), Math.max(...latitudes)],
  ];
}

/** Bounding box around an explicit set of positions, for incident focus. */
export function boundsFor(
  positions: Position[],
): [[number, number], [number, number]] | null {
  if (positions.length === 0) return null;
  const longitudes = positions.map(([longitude]) => longitude);
  const latitudes = positions.map(([, latitude]) => latitude);
  return [
    [Math.min(...longitudes), Math.min(...latitudes)],
    [Math.max(...longitudes), Math.max(...latitudes)],
  ];
}

/* ------------------------------------------------------------ route paths */

/**
 * A response route prepared for animation.
 *
 * Distances are accumulated once, in metres, so the per-frame work is a binary
 * search rather than a re-measure of the whole line. Longitude is scaled by the
 * latitude of the route so a diagonal segment is not treated as longer than it
 * is — at basin scale that flat-earth approximation is well inside the error of
 * the fixture geometry itself.
 */
export interface RoutePath {
  id: string;
  coordinates: Position[];
  /** Cumulative distance to each vertex, same length as `coordinates`. */
  distances: number[];
  length: number;
  /** Destination and travel time, for the focused-route label. */
  label: string;
  communityId: string;
  shelterId: string;
}

const METRES_PER_DEGREE = 111_320;

function metres(from: Position, to: Position, latitudeScale: number): number {
  const dx = (to[0] - from[0]) * METRES_PER_DEGREE * latitudeScale;
  const dy = (to[1] - from[1]) * METRES_PER_DEGREE;
  return Math.hypot(dx, dy);
}

/**
 * Prepare the active routes for a moving team marker.
 *
 * Blocked routes are excluded: a route that crosses a failed edge is not one a
 * team is driving, and showing a unit gliding over a collapsed bridge would
 * claim something the world state explicitly denies.
 */
export function routePaths(routes: MapFeatureCollection): RoutePath[] {
  return routes.features.flatMap((feature) => {
    if (feature.geometry.type !== "LineString") return [];
    if (feature.properties.role === "blocked") return [];

    const coordinates = feature.geometry.coordinates;
    if (coordinates.length < 2) return [];

    const latitudeScale = Math.cos((coordinates[0][1] * Math.PI) / 180);
    const distances: number[] = [0];
    for (let index = 1; index < coordinates.length; index += 1) {
      distances.push(
        distances[index - 1] +
          metres(coordinates[index - 1], coordinates[index], latitudeScale),
      );
    }

    const length = distances[distances.length - 1];
    if (length <= 0) return [];

    return [
      {
        id: String(feature.properties.id ?? feature.id ?? ""),
        coordinates,
        distances,
        length,
        label: String(feature.properties.label ?? ""),
        communityId: String(feature.properties.community_id ?? ""),
        shelterId: String(feature.properties.shelter_id ?? ""),
      },
    ];
  });
}

export interface PointOnPath {
  position: Position;
  /** Compass bearing in degrees, for `icon-rotate`. */
  bearing: number;
}

/** Position and heading at a fraction `t` (0–1) along a prepared route. */
export function pointAlong(path: RoutePath, t: number): PointOnPath {
  const target = Math.min(Math.max(t, 0), 1) * path.length;

  let index = 1;
  while (index < path.distances.length - 1 && path.distances[index] < target) {
    index += 1;
  }

  const from = path.coordinates[index - 1];
  const to = path.coordinates[index];
  const segment = path.distances[index] - path.distances[index - 1];
  const along = segment > 0 ? (target - path.distances[index - 1]) / segment : 0;

  const latitudeScale = Math.cos((from[1] * Math.PI) / 180);
  const bearing =
    (Math.atan2(
      (to[0] - from[0]) * latitudeScale,
      to[1] - from[1],
    ) *
      180) /
    Math.PI;

  return {
    position: [
      from[0] + (to[0] - from[0]) * along,
      from[1] + (to[1] - from[1]) * along,
    ],
    bearing,
  };
}
