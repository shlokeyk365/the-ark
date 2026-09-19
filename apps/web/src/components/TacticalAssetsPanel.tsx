import type {
  PlanResult,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { describeAsset, formatHours } from "../derive";
import { ShellIcon } from "./ShellIcon";

interface TacticalAssetsPanelProps {
  bootstrap: ScenarioBootstrapResponse;
  selectedAssetId: string | null;
  selectedPlan: PlanResult | undefined;
  worldState: WorldStateSnapshot;
  onSelectAsset: (assetId: string) => void;
}

function AssetRow({
  id,
  label,
  state,
  selected,
  tone = "normal",
  onSelect,
}: {
  id: string;
  label: string;
  state: string;
  selected: boolean;
  tone?: "normal" | "warning" | "critical" | "safe" | "unavailable";
  onSelect: (assetId: string) => void;
}) {
  return (
    <button
      aria-pressed={selected}
      className={`tactical-row ${tone} ${selected ? "selected" : ""}`}
      onClick={() => onSelect(id)}
      type="button"
    >
      <i aria-hidden="true" />
      <strong title={label}>{label}</strong>
      <em>{state}</em>
    </button>
  );
}

function PanelSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="tactical-section">
      <h2>{title}</h2>
      <div className="tactical-section-body">{children}</div>
    </section>
  );
}

/** A selectable inventory of API-backed assets. No live dispatch data is implied. */
export function TacticalAssetsPanel({
  bootstrap,
  selectedAssetId,
  selectedPlan,
  worldState,
  onSelectAsset,
}: TacticalAssetsPanelProps) {
  const accessById = new Map(
    worldState.community_access.map((access) => [access.community_id, access]),
  );
  const edgeById = new Map(worldState.edge_states.map((edge) => [edge.edge_id, edge]));
  const assets = bootstrap.assets.features;
  const communities = assets.filter((asset) => asset.properties.asset_type === "community");
  const facilities = assets.filter((asset) =>
    ["hospital", "shelter"].includes(asset.properties.asset_type),
  );
  const bridges = assets.filter((asset) => asset.properties.asset_type === "bridge");
  const criticalRoads = bootstrap.road_network.features.filter(
    (road) => road.properties.critical && road.properties.edge_type === "road",
  );

  const edgeTone = (status: string) =>
    status === "closed" ? "critical" : status === "restricted" ? "warning" : "safe";

  return (
    <aside className="tactical-assets-panel panel-shell" aria-label="Tactical assets and live feed">
      <header className="tactical-panel-title">
        <div>
          <span>Tactical assets</span>
          <small>Scenario inventory</small>
        </div>
        <span className="tactical-source">MODELED</span>
      </header>

      <div className="tactical-scroll">
        <PanelSection title="Communities">
          {communities.map((asset) => {
            const access = accessById.get(asset.id);
            const state = access?.isolated
              ? "ISOLATED"
              : access?.time_to_isolation_hours !== null && access?.time_to_isolation_hours !== undefined
                ? formatHours(access.time_to_isolation_hours)
                : "CONNECTED";
            return (
              <AssetRow
                id={asset.id}
                key={asset.id}
                label={asset.properties.name}
                onSelect={onSelectAsset}
                selected={selectedAssetId === asset.id}
                state={state}
                tone={access?.isolated ? "critical" : "safe"}
              />
            );
          })}
        </PanelSection>

        <PanelSection title="Critical infrastructure">
          {[...bridges, ...criticalRoads].map((item) => {
            const edgeId = "properties" in item && "edge_id" in item.properties
              ? item.properties.edge_id ?? item.id
              : item.id;
            const edge = edgeById.get(edgeId);
            return (
              <AssetRow
                id={edgeId}
                key={edgeId}
                label={
                  "properties" in item && "name" in item.properties
                    ? item.properties.name
                    : describeAsset(new Map(), bootstrap, edgeId)
                }
                onSelect={onSelectAsset}
                selected={selectedAssetId === edgeId}
                state={edge?.status.toUpperCase() ?? "UNAVAILABLE"}
                tone={edge ? edgeTone(edge.status) : "unavailable"}
              />
            );
          })}
        </PanelSection>

        <PanelSection title="Selected-plan routes">
          {selectedPlan?.assignment_results.map((assignment) => (
            <AssetRow
              id={assignment.community_id}
              key={`${assignment.community_id}-${assignment.shelter_id}`}
              label={`${describeAsset(new Map(), bootstrap, assignment.community_id)} → ${describeAsset(new Map(), bootstrap, assignment.shelter_id)}`}
              onSelect={onSelectAsset}
              selected={selectedAssetId === assignment.community_id}
              state={assignment.route ? `${Math.round(assignment.route.travel_minutes)} MIN` : "BLOCKED"}
              tone={assignment.route ? "safe" : "critical"}
            />
          )) ?? <span className="tactical-unavailable">UNAVAILABLE</span>}
        </PanelSection>

        <PanelSection title="Hospitals & shelters">
          {facilities.map((asset) => (
            <AssetRow
              id={asset.id}
              key={asset.id}
              label={asset.properties.name}
              onSelect={onSelectAsset}
              selected={selectedAssetId === asset.id}
              state={
                asset.properties.asset_type === "shelter"
                  ? `${asset.properties.capacity ?? "UNAVAILABLE"} CAP.`
                  : asset.properties.open === true
                    ? "OPEN"
                    : "UNAVAILABLE"
              }
              tone={asset.properties.open === false ? "critical" : "safe"}
            />
          ))}
        </PanelSection>

        <PanelSection title="Rescue teams">
          <span className="tactical-unavailable">
            <ShellIcon name="alert" size={12} /> UNAVAILABLE — no team data in this scenario
          </span>
        </PanelSection>

        <PanelSection title="Live intelligence">
          <span className="tactical-unavailable">
            <ShellIcon name="activity" size={12} /> UNAVAILABLE — no live feed or WebSocket
          </span>
        </PanelSection>
      </div>
    </aside>
  );
}
