import type {
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

export interface FrameSeriesEntry {
  frameId: string;
  hours: number;
  state: WorldStateSnapshot;
}

export interface MetricSeries {
  hours: number[];
  closedRoutes: number[];
  restrictedRoutes: number[];
  peopleIsolated: number[];
  hospitalAccess: number[];
  maxDepthCm: number[];
}

function countStatus(state: WorldStateSnapshot, status: string) {
  return state.edge_states.filter((edge) => edge.status === status).length;
}

export function peopleIsolated(state: WorldStateSnapshot): number {
  return state.plan_results[0]?.metrics.people_isolated ?? 0;
}

export function hospitalAccessCount(state: WorldStateSnapshot): number {
  return state.community_access.filter((access) => access.hospital_accessible).length;
}

export function maxFloodDepth(state: WorldStateSnapshot): number {
  return state.edge_states.reduce(
    (highest, edge) => Math.max(highest, edge.flood_depth_m),
    0,
  );
}

/**
 * Collapse the fetched frames into one series per headline metric. Every point
 * is a value the backend already derived; nothing here is interpolated.
 */
export function deriveSeries(series: FrameSeriesEntry[]): MetricSeries {
  return {
    hours: series.map((entry) => entry.hours),
    closedRoutes: series.map((entry) => countStatus(entry.state, "closed")),
    restrictedRoutes: series.map((entry) => countStatus(entry.state, "restricted")),
    peopleIsolated: series.map((entry) => peopleIsolated(entry.state)),
    hospitalAccess: series.map((entry) => hospitalAccessCount(entry.state)),
    maxDepthCm: series.map((entry) => Math.round(maxFloodDepth(entry.state) * 100)),
  };
}

/** Event IDs that have actually taken effect by the given simulation hour. */
export function eventsActiveAt(
  bootstrap: ScenarioBootstrapResponse,
  eventIds: string[],
  hours: number,
): string[] {
  const byId = new Map(bootstrap.events.map((event) => [event.event_id, event]));
  return eventIds.filter((eventId) => {
    const event = byId.get(eventId);
    return event !== undefined && event.effective_at_hours <= hours;
  });
}

export function assetNames(
  bootstrap: ScenarioBootstrapResponse,
): Map<string, string> {
  return new Map(
    bootstrap.assets.features.map((feature) => [feature.id, feature.properties.name]),
  );
}

/** Human label for any domain ID the UI might surface, falling back to the ID. */
export function describeAsset(
  names: Map<string, string>,
  bootstrap: ScenarioBootstrapResponse,
  id: string,
): string {
  const assetName = names.get(id);
  if (assetName) return assetName;
  const edge = bootstrap.road_network.features.find((feature) => feature.id === id);
  if (edge) {
    return edge.properties.edge_type === "bridge"
      ? `Bridge ${id.replace("ktp-bridge-", "")}`
      : `Road ${id.replace("ktp-road-", "")}`;
  }
  return id;
}

export function formatHours(hours: number): string {
  return hours === 0 ? "Now" : `+${hours}h`;
}
