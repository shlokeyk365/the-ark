import type {
  PlanResult,
  Position,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

/**
 * GeoJSON the Mapbox layers consume. Everything here is a pure projection of
 * API payloads into map-ready features — no domain logic, no thresholds, no
 * routing. The backend remains the only place that decides what is closed,
 * reachable, or isolated.
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

const KM_PER_DEG_LAT = 110.574;

function midpoint(coordinates: Position[]): Position {
  if (coordinates.length === 0) return [0, 0];
  if (coordinates.length === 1) return coordinates[0];
  const first = coordinates[0];
  const last = coordinates[coordinates.length - 1];
  return [(first[0] + last[0]) / 2, (first[1] + last[1]) / 2];
}

/* ------------------------------------------------------------------ roads */

export function roadsCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
  routeEdgeIds: Set<string>,
): MapFeatureCollection {
  const stateById = new Map(
    worldState.edge_states.map((edge) => [edge.edge_id, edge]),
  );

  return {
    type: "FeatureCollection",
    features: bootstrap.road_network.features.map((feature) => {
      const state = stateById.get(feature.id);
      return {
        type: "Feature",
        id: feature.id,
        geometry: { type: "LineString", coordinates: feature.geometry.coordinates },
        properties: {
          id: feature.id,
          edge_type: feature.properties.edge_type,
          status: state?.status ?? "open",
          flood_depth_m: state?.flood_depth_m ?? 0,
          travel_minutes: state?.effective_travel_minutes ?? null,
          baseline_travel_minutes: feature.properties.baseline_travel_minutes,
          closure_reason: state?.closure_reason ?? null,
          originating_event_id: state?.originating_event_id ?? null,
          critical: Boolean(state?.critical ?? feature.properties.critical),
          on_route: routeEdgeIds.has(feature.id),
        },
      };
    }),
  };
}

export function routeCollection(
  bootstrap: ScenarioBootstrapResponse,
  routeEdgeIds: Set<string>,
): MapFeatureCollection {
  return {
    type: "FeatureCollection",
    features: bootstrap.road_network.features
      .filter((feature) => routeEdgeIds.has(feature.id))
      .map((feature) => ({
        type: "Feature",
        id: `route-${feature.id}`,
        geometry: { type: "LineString", coordinates: feature.geometry.coordinates },
        properties: { id: feature.id },
      })),
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

export function assetsCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
): MapFeatureCollection {
  const accessById = new Map(
    worldState.community_access.map((access) => [access.community_id, access]),
  );

  return {
    type: "FeatureCollection",
    features: bootstrap.assets.features
      .filter((feature) => feature.geometry.type === "Point")
      .map((feature) => {
        const access = accessById.get(feature.id);
        return {
          type: "Feature",
          id: feature.id,
          geometry: {
            type: "Point",
            coordinates: feature.geometry.coordinates as Position,
          },
          properties: {
            id: feature.id,
            name: feature.properties.name,
            asset_type: feature.properties.asset_type,
            population: feature.properties.population ?? null,
            capacity: feature.properties.capacity ?? null,
            isolated: Boolean(access?.isolated),
            hospital_accessible: access ? access.hospital_accessible : true,
            reachable_shelters: access?.reachable_shelter_ids.length ?? 0,
            time_to_isolation_hours: access?.time_to_isolation_hours ?? null,
          },
        };
      }),
  };
}

export function bridgesCollection(
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
            type: "Point",
            coordinates: midpoint(feature.geometry.coordinates as Position[]),
          },
          properties: {
            id: feature.id,
            name: feature.properties.name,
            status: state?.status ?? "open",
            flood_depth_m: state?.flood_depth_m ?? 0,
          },
        };
      }),
  };
}

/* ---------------------------------------------------------------- hazards */

export function hazardsCollection(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
): MapFeatureCollection {
  const assetPoints = new Map<string, Position>();
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
            hazard_id: hazard.hazard_id,
            priority: hazard.priority,
            hazard_type: hazard.hazard_type,
            asset_id: hazard.asset_id,
            description: hazard.description ?? "",
            operator_injected: hazard.source_event_id !== null,
          },
        },
      ];
    }),
  };
}

/* ------------------------------------------------------------------ flood */

/**
 * PLACEHOLDER GEOMETRY — replace with solver output.
 *
 * The scenario fixture carries flood depth per network edge, not an inundation
 * surface. Until `services/physics` publishes a flood polygon fixture, these
 * envelopes are drawn from the channel centreline widened by the frame's peak
 * modeled depth. They communicate extent and growth; they are not a
 * hydraulic result and must never be read as one.
 *
 * See docs/scenario-contract.md for the flood-polygon fixture this will
 * consume instead.
 */
const CHANNEL_CENTRELINE: Position[] = [
  [85.262, 27.6955],
  [85.29, 27.6884],
  [85.317, 27.6906],
  [85.334, 27.6872],
  [85.352, 27.6913],
  [85.378, 27.6858],
];

const CHANNEL_HALF_WIDTH_KM = 0.22;
/** Kilometres of lateral spread modeled per metre of peak depth. */
const SPREAD_KM_PER_METRE = 2.9;

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

function envelopeRing(halfWidthKm: number): Position[] {
  const offset = halfWidthKm / KM_PER_DEG_LAT;
  const north: Position[] = SMOOTHED_CENTRELINE.map(([lon, lat]) => [lon, lat + offset]);
  const south: Position[] = [...SMOOTHED_CENTRELINE]
    .reverse()
    .map(([lon, lat]) => [lon, lat - offset]);
  return [...north, ...south, north[0]];
}

export function peakDepth(worldState: WorldStateSnapshot): number {
  return worldState.edge_states.reduce(
    (highest, edge) => Math.max(highest, edge.flood_depth_m),
    0,
  );
}

function envelopeFeature(
  id: string,
  halfWidthKm: number,
  depth: number,
  label: string,
): MapFeature {
  return {
    type: "Feature",
    id,
    geometry: { type: "Polygon", coordinates: [envelopeRing(halfWidthKm)] },
    properties: {
      id,
      label,
      peak_depth_m: Number(depth.toFixed(2)),
      provenance: "modeled_envelope_placeholder",
    },
  };
}

/** Inundation implied by the frame currently on screen. */
export function floodNowCollection(worldState: WorldStateSnapshot): MapFeatureCollection {
  const depth = peakDepth(worldState);
  return {
    type: "FeatureCollection",
    features: [
      envelopeFeature(
        "flood-now",
        CHANNEL_HALF_WIDTH_KM + depth * SPREAD_KM_PER_METRE,
        depth,
        "Modeled inundation (current frame)",
      ),
    ],
  };
}

/** Inundation implied by the last frame in the horizon. */
export function floodForecastCollection(
  horizonState: WorldStateSnapshot | undefined,
): MapFeatureCollection {
  if (!horizonState) return EMPTY;
  const depth = peakDepth(horizonState);
  return {
    type: "FeatureCollection",
    features: [
      envelopeFeature(
        "flood-forecast",
        CHANNEL_HALF_WIDTH_KM + depth * SPREAD_KM_PER_METRE,
        depth,
        "Modeled inundation (horizon)",
      ),
    ],
  };
}

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

  const longitudes = positions.map(([longitude]) => longitude);
  const latitudes = positions.map(([, latitude]) => latitude);

  return [
    [Math.min(...longitudes), Math.min(...latitudes)],
    [Math.max(...longitudes), Math.max(...latitudes)],
  ];
}
