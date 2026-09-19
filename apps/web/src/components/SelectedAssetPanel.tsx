import type {
  IncidentEvent,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { describeAsset, formatHours } from "../derive";
import { ShellIcon } from "./ShellIcon";

interface SelectedAssetPanelProps {
  activeEventIds: string[];
  bootstrap: ScenarioBootstrapResponse;
  busy: boolean;
  selectedAssetId: string | null;
  worldState: WorldStateSnapshot;
  onApplyEvent: (eventId: string) => void;
}

function DetailRow({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="asset-detail-row">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  );
}

function eventForAsset(
  events: IncidentEvent[],
  assetId: string | null,
  edgeId: string | undefined,
) {
  if (!assetId) return undefined;
  return events.find((event) =>
    event.changes.some((change) => change.edge_id === assetId || change.edge_id === edgeId),
  );
}

/**
 * Shows only the technical values that already exist in the canonical payload.
 * Figma's structural and flow telemetry remains visibly unavailable.
 */
export function SelectedAssetPanel({
  activeEventIds,
  bootstrap,
  busy,
  selectedAssetId,
  worldState,
  onApplyEvent,
}: SelectedAssetPanelProps) {
  const asset = bootstrap.assets.features.find((feature) => feature.id === selectedAssetId);
  const edgeId = asset?.properties.edge_id ?? selectedAssetId ?? undefined;
  const edge = worldState.edge_states.find((state) => state.edge_id === edgeId);
  const access = worldState.community_access.find((item) => item.community_id === selectedAssetId);
  const hazard = worldState.hazards.find(
    (item) => item.asset_id === selectedAssetId || item.asset_id === edgeId,
  );
  const event = eventForAsset(bootstrap.events, selectedAssetId, edgeId);
  const canSimulate = Boolean(event && !activeEventIds.includes(event.event_id));
  const name = selectedAssetId
    ? asset?.properties.name ?? describeAsset(new Map(), bootstrap, selectedAssetId)
    : "No asset selected";

  return (
    <aside className="selected-asset-panel panel-shell" aria-label="Selected asset details">
      <header className="selected-asset-heading">
        <span>Selected asset</span>
        <strong>{name}</strong>
      </header>

      {!selectedAssetId ? (
        <div className="selected-empty-state">
          <ShellIcon name="crosshair" size={18} />
          <span>Select an asset from the tactical panel.</span>
        </div>
      ) : (
        <div className="selected-asset-content">
          <div className={`selected-alert ${hazard ? "has-alert" : ""}`}>
            <ShellIcon name={hazard ? "alert" : "shield"} size={14} />
            <div>
              <strong>{hazard ? `${hazard.priority.toUpperCase()} ALERT` : "NO ACTIVE ALERT"}</strong>
              <span>{hazard?.description ?? "No current backend-derived alert for this asset."}</span>
            </div>
          </div>

          <section className="asset-detail-section">
            <h2>Technical data</h2>
            {edge ? (
              <>
                <DetailRow label="Current status" tone={edge.status} value={edge.status.toUpperCase()} />
                <DetailRow label="Flood depth" value={`${edge.flood_depth_m.toFixed(2)} m`} />
                <DetailRow
                  label="Travel time"
                  value={edge.effective_travel_minutes === null ? "IMPASSABLE" : `${edge.effective_travel_minutes} min`}
                />
                <DetailRow label="Closure reason" value={edge.closure_reason ?? "NONE"} />
              </>
            ) : access ? (
              <>
                <DetailRow label="Population" value={(asset?.properties.population ?? "UNAVAILABLE").toLocaleString()} />
                <DetailRow label="Access status" tone={access.isolated ? "closed" : "open"} value={access.isolated ? "ISOLATED" : "CONNECTED"} />
                <DetailRow
                  label="Time to isolation"
                  value={access.time_to_isolation_hours === null ? "UNAVAILABLE" : formatHours(access.time_to_isolation_hours)}
                />
                <DetailRow label="Hospital access" value={access.hospital_accessible ? "REACHABLE" : "LOST"} />
              </>
            ) : (
              <>
                <DetailRow label="Operational status" value={asset?.properties.open === true ? "OPEN" : "UNAVAILABLE"} />
                <DetailRow label="Capacity" value={asset?.properties.capacity?.toLocaleString() ?? "UNAVAILABLE"} />
              </>
            )}
            <DetailRow label="Structural rating" value="UNAVAILABLE" />
            <DetailRow label="Failure window" value="UNAVAILABLE" />
            <DetailRow label="Flow velocity" value="UNAVAILABLE" />
          </section>

          <section className="asset-detail-section">
            <h2>Risk analysis</h2>
            <DetailRow label="Dependent communities" value="UNAVAILABLE" />
            <DetailRow label="Alternate route delta" value="UNAVAILABLE" />
          </section>
        </div>
      )}

      <footer className="selected-asset-actions">
        <button
          disabled={!canSimulate || busy}
          onClick={() => event && onApplyEvent(event.event_id)}
          type="button"
        >
          <ShellIcon name="alert" size={13} />
          {canSimulate ? "Simulate failure" : "Simulate failure unavailable"}
        </button>
        <span>Plan comparison remains in the response-plan panel.</span>
        <button disabled type="button">
          Assign response unavailable
        </button>
      </footer>
    </aside>
  );
}
