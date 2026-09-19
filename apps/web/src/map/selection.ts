import type {
  Position,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { edgeLabel, nodeLabels } from "./scenarioSources";

/**
 * Incident focus.
 *
 * Selecting something on the map — or in a side panel — puts the dashboard into
 * a contextual mode: the affected community, the damaged edge, the routes that
 * still work and the facilities that can still be reached stay at full weight,
 * and everything else recedes.
 *
 * The focus set is derived here, from the world state, so the map and the
 * panels agree on what "related" means without either re-deriving it.
 */

export type MapSelection =
  | { kind: "asset"; id: string }
  | { kind: "edge"; id: string }
  | { kind: "hazard"; id: string };

export interface FocusFact {
  label: string;
  value: string;
  tone?: "neutral" | "warn" | "bad" | "good";
}

export interface IncidentFocus {
  selection: MapSelection;
  /** Ids emphasised while the focus is held. */
  assetIds: Set<string>;
  edgeIds: Set<string>;
  hazardIds: Set<string>;
  /** Primary subject, drawn with the selection ring. */
  primaryAssetId: string | null;
  primaryEdgeId: string | null;
  kindLabel: string;
  title: string;
  summary: string;
  facts: FocusFact[];
  /** Everything the camera should frame. */
  positions: Position[];
}

function assetPosition(
  bootstrap: ScenarioBootstrapResponse,
  assetId: string,
): Position | null {
  const asset = bootstrap.assets.features.find((feature) => feature.id === assetId);
  if (!asset) return null;
  if (asset.geometry.type === "Point") return asset.geometry.coordinates;
  const line = asset.geometry.coordinates as Position[];
  return line[Math.floor(line.length / 2)] ?? null;
}

function edgePositions(
  bootstrap: ScenarioBootstrapResponse,
  edgeId: string,
): Position[] {
  const road = bootstrap.road_network.features.find((feature) => feature.id === edgeId);
  return road ? road.geometry.coordinates : [];
}

function minutesLabel(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  return `${Math.round(minutes)} min`;
}

/**
 * Communities whose current shelter or hospital route runs over an edge.
 *
 * This is what makes an edge failure legible: a closed span matters because of
 * who was relying on it, not because of its own length.
 */
function communitiesUsingEdge(
  worldState: WorldStateSnapshot,
  edgeId: string,
): string[] {
  return worldState.community_access
    .filter(
      (access) =>
        access.hospital_route?.edge_ids.includes(edgeId) ||
        access.shelter_routes.some((entry) => entry.route.edge_ids.includes(edgeId)),
    )
    .map((access) => access.community_id);
}

function communityFocus(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
  communityId: string,
  names: Map<string, string>,
): Omit<IncidentFocus, "selection" | "kindLabel"> {
  const access = worldState.community_access.find(
    (entry) => entry.community_id === communityId,
  );
  const asset = bootstrap.assets.features.find((feature) => feature.id === communityId);
  const population = asset?.properties.population ?? 0;

  const assetIds = new Set<string>([communityId]);
  const edgeIds = new Set<string>();
  const positions: Position[] = [];

  const communityPoint = assetPosition(bootstrap, communityId);
  if (communityPoint) positions.push(communityPoint);

  // The shortest surviving shelter route is the one an operator acts on first.
  const nearest = [...(access?.shelter_routes ?? [])].sort(
    (a, b) => a.route.travel_minutes - b.route.travel_minutes,
  )[0];

  access?.shelter_routes.forEach((entry) => {
    assetIds.add(entry.shelter_id);
    entry.route.edge_ids.forEach((edgeId) => edgeIds.add(edgeId));
    const shelterPoint = assetPosition(bootstrap, entry.shelter_id);
    if (shelterPoint) positions.push(shelterPoint);
  });

  if (access?.hospital_route) {
    access.hospital_route.edge_ids.forEach((edgeId) => edgeIds.add(edgeId));
    const hospital = bootstrap.assets.features.find(
      (feature) => feature.properties.asset_type === "hospital",
    );
    if (hospital) {
      assetIds.add(hospital.id);
      const point = assetPosition(bootstrap, hospital.id);
      if (point) positions.push(point);
    }
  }

  edgeIds.forEach((edgeId) => positions.push(...edgePositions(bootstrap, edgeId)));

  const hazardIds = new Set(
    worldState.hazards
      .filter(
        (hazard) => hazard.asset_id === communityId || edgeIds.has(hazard.asset_id),
      )
      .map((hazard) => hazard.hazard_id),
  );

  const facts: FocusFact[] = [
    {
      label: "Affected population",
      value: population ? population.toLocaleString() : "—",
      tone: access?.isolated ? "bad" : "neutral",
    },
    {
      label: "Nearest reachable shelter",
      value: nearest
        ? (names.get(nearest.shelter_id) ?? nearest.shelter_id)
        : "none reachable",
      tone: nearest ? "good" : "bad",
    },
    {
      label: "Route time",
      value: nearest ? minutesLabel(nearest.route.travel_minutes) : "—",
    },
    {
      label: "Hospital access",
      value: access?.hospital_accessible
        ? minutesLabel(access.hospital_route?.travel_minutes)
        : "lost",
      tone: access?.hospital_accessible ? "good" : "bad",
    },
  ];

  if (access?.time_to_isolation_hours !== null && access?.time_to_isolation_hours !== undefined) {
    facts.push({
      label: "Time to isolation",
      value: `+${access.time_to_isolation_hours}h`,
      tone: "warn",
    });
  }

  return {
    assetIds,
    edgeIds,
    hazardIds,
    primaryAssetId: communityId,
    primaryEdgeId: null,
    title: names.get(communityId) ?? communityId,
    summary: access?.isolated
      ? "Isolated — no safe route to a shelter or the hospital."
      : access?.reachable_shelter_ids.length
        ? `${access.reachable_shelter_ids.length} shelter${access.reachable_shelter_ids.length === 1 ? "" : "s"} still reachable.`
        : "No shelter route in the current world state.",
    facts,
    positions,
  };
}

function facilityFocus(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
  facilityId: string,
  names: Map<string, string>,
): Omit<IncidentFocus, "selection" | "kindLabel"> {
  const asset = bootstrap.assets.features.find((feature) => feature.id === facilityId);
  const isHospital = asset?.properties.asset_type === "hospital";

  const assetIds = new Set<string>([facilityId]);
  const edgeIds = new Set<string>();
  const positions: Position[] = [];
  const point = assetPosition(bootstrap, facilityId);
  if (point) positions.push(point);

  let served = 0;

  worldState.community_access.forEach((access) => {
    const route = isHospital
      ? access.hospital_accessible
        ? access.hospital_route
        : null
      : (access.shelter_routes.find((entry) => entry.shelter_id === facilityId)?.route ??
        null);
    if (!route) return;

    served += 1;
    assetIds.add(access.community_id);
    route.edge_ids.forEach((edgeId) => edgeIds.add(edgeId));
    const communityPoint = assetPosition(bootstrap, access.community_id);
    if (communityPoint) positions.push(communityPoint);
  });

  edgeIds.forEach((edgeId) => positions.push(...edgePositions(bootstrap, edgeId)));

  const inbound = worldState.community_access
    .filter((access) =>
      isHospital
        ? access.hospital_accessible
        : access.reachable_shelter_ids.includes(facilityId),
    )
    .reduce((total, access) => {
      const community = bootstrap.assets.features.find(
        (feature) => feature.id === access.community_id,
      );
      return total + (community?.properties.population ?? 0);
    }, 0);

  const facts: FocusFact[] = [
    {
      label: "Communities connected",
      value: `${served}/${worldState.community_access.length}`,
      tone: served === worldState.community_access.length ? "good" : "warn",
    },
    { label: "Population with access", value: inbound.toLocaleString() },
  ];

  if (asset?.properties.capacity) {
    facts.push({
      label: "Capacity",
      value: asset.properties.capacity.toLocaleString(),
      tone: inbound > asset.properties.capacity ? "bad" : "neutral",
    });
  }

  return {
    assetIds,
    edgeIds,
    hazardIds: new Set<string>(),
    primaryAssetId: facilityId,
    primaryEdgeId: null,
    title: names.get(facilityId) ?? facilityId,
    summary: served
      ? `Reachable from ${served} of ${worldState.community_access.length} communities.`
      : "Not reachable from any community in this world state.",
    facts,
    positions,
  };
}

function edgeFocus(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
  edgeId: string,
  names: Map<string, string>,
  labels: Map<string, string>,
): Omit<IncidentFocus, "selection" | "kindLabel"> {
  const state = worldState.edge_states.find((edge) => edge.edge_id === edgeId);
  const dependents = communitiesUsingEdge(worldState, edgeId);

  const assetIds = new Set<string>(dependents);
  const edgeIds = new Set<string>([edgeId]);
  const positions = [...edgePositions(bootstrap, edgeId)];

  dependents.forEach((communityId) => {
    const point = assetPosition(bootstrap, communityId);
    if (point) positions.push(point);
  });

  // The alternatives those communities still hold are part of the decision.
  worldState.community_access
    .filter((access) => dependents.includes(access.community_id))
    .forEach((access) => {
      access.shelter_routes.forEach((entry) => {
        assetIds.add(entry.shelter_id);
        entry.route.edge_ids.forEach((id) => edgeIds.add(id));
      });
    });

  const affectedPopulation = dependents.reduce((total, communityId) => {
    const community = bootstrap.assets.features.find(
      (feature) => feature.id === communityId,
    );
    return total + (community?.properties.population ?? 0);
  }, 0);

  const isolatedNames = worldState.community_access
    .filter((access) => access.isolated)
    .map((access) => names.get(access.community_id) ?? access.community_id);

  const facts: FocusFact[] = [
    {
      label: "Status",
      value:
        state?.status === "closed"
          ? "Impassable"
          : state?.status === "restricted"
            ? "Impaired"
            : "Open",
      tone:
        state?.status === "closed" ? "bad" : state?.status === "restricted" ? "warn" : "good",
    },
    { label: "Water depth", value: `${(state?.flood_depth_m ?? 0).toFixed(2)} m` },
    {
      label: "Travel time",
      value:
        state?.effective_travel_minutes === null
          ? "no through route"
          : minutesLabel(state?.effective_travel_minutes),
    },
    // Counted against the *current* world state: once an edge closes, the
    // routes that used to run over it are gone, so "0" here is the consequence
    // of the failure rather than evidence the edge never mattered.
    { label: "Routes still using it", value: `${dependents.length}` },
    { label: "Population still served", value: affectedPopulation.toLocaleString() },
  ];

  if (isolatedNames.length) {
    facts.push({
      label: "Unreachable",
      value: isolatedNames.join(", "),
      tone: "bad",
    });
  }

  if (state?.originating_event_id) {
    facts.push({
      label: "Cause",
      value: state.closure_reason ?? "operator-injected event",
      tone: "warn",
    });
  }

  return {
    assetIds,
    edgeIds,
    hazardIds: new Set(
      worldState.hazards
        .filter((hazard) => hazard.asset_id === edgeId)
        .map((hazard) => hazard.hazard_id),
    ),
    primaryAssetId: null,
    primaryEdgeId: edgeId,
    title: edgeLabel(bootstrap, labels, edgeId),
    summary:
      state?.closure_reason ??
      (state?.status === "open"
        ? "Open under the current modeled depth."
        : "Degraded under the current modeled depth."),
    facts,
    positions,
  };
}

/** Resolve a selection into everything the map and the focus panel need. */
export function buildFocus(
  bootstrap: ScenarioBootstrapResponse,
  worldState: WorldStateSnapshot,
  selection: MapSelection | null,
): IncidentFocus | null {
  if (!selection) return null;

  const names = new Map(
    bootstrap.assets.features.map((feature) => [feature.id, feature.properties.name]),
  );
  const labels = nodeLabels(bootstrap);

  if (selection.kind === "hazard") {
    const hazard = worldState.hazards.find(
      (entry) => entry.hazard_id === selection.id,
    );
    if (!hazard) return null;

    const isCommunity = hazard.hazard_type === "community_isolated";
    const base = isCommunity
      ? communityFocus(bootstrap, worldState, hazard.asset_id, names)
      : edgeFocus(bootstrap, worldState, hazard.asset_id, names, labels);

    return {
      ...base,
      selection,
      kindLabel: hazard.priority === "critical" ? "Critical hazard" : "Hazard",
      summary: hazard.description || base.summary,
      hazardIds: new Set([...base.hazardIds, hazard.hazard_id]),
    };
  }

  if (selection.kind === "edge") {
    const base = edgeFocus(bootstrap, worldState, selection.id, names, labels);
    const isBridge = bootstrap.assets.features.some(
      (feature) =>
        feature.properties.asset_type === "bridge" &&
        (feature.properties.edge_id ?? feature.id) === selection.id,
    );
    return { ...base, selection, kindLabel: isBridge ? "Bridge" : "Road segment" };
  }

  const asset = bootstrap.assets.features.find((feature) => feature.id === selection.id);
  if (!asset) return null;

  if (asset.properties.asset_type === "community") {
    return {
      ...communityFocus(bootstrap, worldState, selection.id, names),
      selection,
      kindLabel: "Community",
    };
  }

  if (asset.properties.asset_type === "bridge") {
    const edgeId = asset.properties.edge_id ?? asset.id;
    return {
      ...edgeFocus(bootstrap, worldState, edgeId, names, labels),
      selection,
      kindLabel: "Bridge",
    };
  }

  return {
    ...facilityFocus(bootstrap, worldState, selection.id, names),
    selection,
    kindLabel: asset.properties.asset_type === "hospital" ? "Hospital" : "Shelter",
  };
}
