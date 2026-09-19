import type {
  AssignmentResult,
  PlanResult,
  PredictionSignal,
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

export type ResponseDestinationStatus =
  | "go_now"
  | "priority"
  | "planned"
  | "blocked";

export interface ResponseDestination {
  id: string;
  rank: number;
  communityId: string;
  communityName: string;
  shelterId: string;
  shelterName: string;
  people: number;
  status: ResponseDestinationStatus;
  travelMinutes: number | null;
  arrivalMinutes: number | null;
  deadlineMinutes: number | null;
  routeEdgeIds: string[];
  restrictedEdgeCount: number;
  remainingAccessHours: number | null;
  signal: PredictionSignal | null;
  instruction: string;
  rationale: string[];
}

function strongestSignal(
  worldState: WorldStateSnapshot,
  communityId: string,
): PredictionSignal | null {
  return (
    worldState.prediction_signals
      .filter((signal) => signal.exposure_asset_id === communityId)
      .sort(
        (left, right) =>
          right.priority_score - left.priority_score ||
          left.priority_rank - right.priority_rank,
      )[0] ?? null
  );
}

function destinationStatus(
  assignment: AssignmentResult,
  signal: PredictionSignal | null,
  isolated: boolean,
  remainingAccessHours: number | null,
  restrictedEdgeCount: number,
): ResponseDestinationStatus {
  if (!assignment.route || !assignment.meets_deadline) return "blocked";
  if (
    isolated ||
    (signal?.state === "active" && signal.priority_level === "critical") ||
    (remainingAccessHours !== null && remainingAccessHours <= 3)
  ) {
    return "go_now";
  }
  if (
    (signal?.state === "active" &&
      (signal.priority_level === "high" || signal.priority_level === "elevated")) ||
    (remainingAccessHours !== null && remainingAccessHours <= 9) ||
    restrictedEdgeCount > 0
  ) {
    return "priority";
  }
  return "planned";
}

/**
 * Present the selected plan's already-evaluated assignments as a destination
 * brief. Routing, feasibility, and arrival times remain backend-owned; this
 * helper only joins those results to human labels and model evidence.
 */
export function responseDestinations(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
  selectedPlan: PlanResult | undefined,
): ResponseDestination[] {
  if (!selectedPlan) return [];

  const names = assetNames(bootstrap);
  const accessByCommunity = new Map(
    worldState.community_access.map((access) => [access.community_id, access]),
  );
  const edgeStateById = new Map(
    worldState.edge_states.map((edge) => [edge.edge_id, edge]),
  );
  const deadlineMinutes =
    bootstrap.plans.find((plan) => plan.plan_id === selectedPlan.plan_id)
      ?.evaluation_deadline_minutes ?? null;

  const destinations = selectedPlan.assignment_results.map((assignment, index) => {
    const communityName = names.get(assignment.community_id) ?? assignment.community_id;
    const shelterName = names.get(assignment.shelter_id) ?? assignment.shelter_id;
    const access = accessByCommunity.get(assignment.community_id);
    const signal = strongestSignal(worldState, assignment.community_id);
    const routeEdgeIds = assignment.route?.edge_ids ?? [];
    const restrictedEdgeCount = routeEdgeIds.filter(
      (edgeId) => edgeStateById.get(edgeId)?.status === "restricted",
    ).length;
    const remainingAccessHours =
      access?.time_to_isolation_hours === null ||
      access?.time_to_isolation_hours === undefined
        ? null
        : Math.max(
            0,
            access.time_to_isolation_hours - worldState.simulation_time_hours,
          );
    const status = destinationStatus(
      assignment,
      signal,
      access?.isolated ?? false,
      remainingAccessHours,
      restrictedEdgeCount,
    );
    const rationale: string[] = [];

    if (!assignment.route) {
      rationale.push("No safe route exists in this modeled state");
    } else if (!assignment.meets_deadline) {
      rationale.push("Modeled arrival falls outside the plan deadline");
    }
    if (access?.isolated) {
      rationale.push("Community is isolated in the selected frame");
    } else if (remainingAccessHours !== null) {
      rationale.push(
        `${remainingAccessHours === 0 ? "Less than 1" : remainingAccessHours}h modeled access window remaining`,
      );
    }
    if (signal) {
      rationale.push(
        `#${signal.priority_rank} ${signal.priority_level} ${signal.state} model signal`,
      );
    }
    if (restrictedEdgeCount > 0) {
      rationale.push(
        `${restrictedEdgeCount} restricted route segment${restrictedEdgeCount === 1 ? "" : "s"}`,
      );
    }
    if (rationale.length === 0) {
      rationale.push("Scheduled by the selected counterfactual plan");
    }

    return {
      id: `${selectedPlan.plan_id}:${assignment.community_id}:${assignment.shelter_id}:${index}`,
      rank: 0,
      communityId: assignment.community_id,
      communityName,
      shelterId: assignment.shelter_id,
      shelterName,
      people: assignment.people,
      status,
      travelMinutes: assignment.route?.travel_minutes ?? null,
      arrivalMinutes: assignment.arrival_minutes,
      deadlineMinutes,
      routeEdgeIds,
      restrictedEdgeCount,
      remainingAccessHours,
      signal,
      instruction:
        status === "blocked"
          ? `Hold dispatch to ${communityName}; no feasible transfer to ${shelterName}.`
          : `Proceed to ${communityName}, then support evacuation to ${shelterName}.`,
      rationale,
    };
  });

  const statusOrder: Record<ResponseDestinationStatus, number> = {
    go_now: 0,
    priority: 1,
    planned: 2,
    blocked: 3,
  };
  const missingNumber = Number.POSITIVE_INFINITY;

  return destinations
    .sort((left, right) => {
      const byStatus = statusOrder[left.status] - statusOrder[right.status];
      if (byStatus !== 0) return byStatus;

      const byRisk =
        (left.signal?.priority_rank ?? missingNumber) -
        (right.signal?.priority_rank ?? missingNumber);
      if (byRisk !== 0) return byRisk;

      const byAccess =
        (left.remainingAccessHours ?? missingNumber) -
        (right.remainingAccessHours ?? missingNumber);
      if (byAccess !== 0) return byAccess;

      const byArrival =
        (left.arrivalMinutes ?? missingNumber) -
        (right.arrivalMinutes ?? missingNumber);
      if (byArrival !== 0) return byArrival;

      return left.communityId.localeCompare(right.communityId);
    })
    .map((destination, index) => ({ ...destination, rank: index + 1 }));
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
