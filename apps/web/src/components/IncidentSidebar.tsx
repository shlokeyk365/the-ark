import type {
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import {
  assetNames,
  describeAsset,
  deriveSeries,
  formatHours,
  hospitalAccessCount,
  maxFloodDepth,
  peopleIsolated,
  type FrameSeriesEntry,
} from "../derive";
import { ShellIcon } from "./ShellIcon";
import { Delta, Sparkline, type Tone } from "./Trend";

interface IncidentSidebarProps {
  bootstrap: ScenarioBootstrapResponse;
  worldState: WorldStateSnapshot;
  series: FrameSeriesEntry[];
}

interface MetricRowProps {
  icon: Parameters<typeof ShellIcon>[0]["name"];
  tone: Tone;
  value: string;
  label: string;
  note: string;
  points: number[];
  activeIndex: number;
  previous: number | undefined;
  current: number;
  riseIsBad?: boolean;
}

function MetricRow({
  icon,
  tone,
  value,
  label,
  note,
  points,
  activeIndex,
  previous,
  current,
  riseIsBad = true,
}: MetricRowProps) {
  return (
    <div className="metric-row">
      <span className={`metric-icon ${tone}`}>
        <ShellIcon name={icon} size={17} />
      </span>
      <div className="metric-value">
        <strong>{value}</strong>
        <span>{label}</span>
      </div>
      <div className="metric-trend">
        <Delta current={current} previous={previous} riseIsBad={riseIsBad} />
        <Sparkline
          activeIndex={activeIndex}
          label={`${label} across all modeled frames`}
          tone={tone}
          values={points}
        />
        <em>{note}</em>
      </div>
    </div>
  );
}

export function IncidentSidebar({
  bootstrap,
  worldState,
  series,
}: IncidentSidebarProps) {
  const names = assetNames(bootstrap);
  const metrics = deriveSeries(series);
  const activeIndex = Math.max(
    0,
    series.findIndex((entry) => entry.frameId === worldState.frame_id),
  );
  const previousIndex = activeIndex - 1;
  const at = (points: number[], index: number) =>
    index >= 0 && index < points.length ? points[index] : undefined;

  const closed = worldState.edge_states.filter((edge) => edge.status === "closed").length;
  const restricted = worldState.edge_states.filter(
    (edge) => edge.status === "restricted",
  ).length;
  const isolatedCommunities = worldState.community_access.filter(
    (access) => access.isolated,
  );
  const hospitalAccess = hospitalAccessCount(worldState);
  const totalCommunities = worldState.community_access.length;
  const depthCm = Math.round(maxFloodDepth(worldState) * 100);

  const nextIsolation = worldState.community_access
    .filter((access) => access.time_to_isolation_hours !== null && !access.isolated)
    .sort(
      (a, b) =>
        (a.time_to_isolation_hours ?? Infinity) - (b.time_to_isolation_hours ?? Infinity),
    )[0];

  return (
    <aside className="left-rail panel-shell" aria-label="Incident overview">
      <section className="incident-summary">
        <div className="section-eyebrow">
          <span>Incident overview</span>
          <span className={`status-badge ${worldState.active_event_ids.length ? "disrupted" : ""}`}>
            {worldState.active_event_ids.length ? "DISRUPTED" : "MODELED"}
          </span>
        </div>
        <h1>Kantipur River Flood Exercise</h1>
        <p>{bootstrap.description}</p>
        <div className="incident-meta">
          <span>
            <ShellIcon name="clock" size={13} />
            {formatHours(worldState.simulation_time_hours)}
          </span>
          <span className="meta-version">{worldState.world_state_version}</span>
        </div>
        <div className="weather-callout">
          <span className="weather-icon">
            <ShellIcon name="rain" size={24} />
          </span>
          <div>
            <strong>{worldState.rainfall_assumption}</strong>
            <span>{worldState.rainfall_multiplier.toFixed(1)}× modeled rainfall</span>
          </div>
          <span className="weather-depth">
            <strong>{depthCm}</strong>
            <em>cm peak</em>
          </span>
        </div>
      </section>

      <section className="rail-section">
        <h2>Current status</h2>
        <div className="metric-stack">
          <MetricRow
            activeIndex={activeIndex}
            current={depthCm}
            icon="drop"
            label="Peak modeled depth"
            note="across 12 edges"
            points={metrics.maxDepthCm}
            previous={at(metrics.maxDepthCm, previousIndex)}
            tone="cyan"
            value={`${depthCm} cm`}
          />
          <MetricRow
            activeIndex={activeIndex}
            current={closed}
            icon="road"
            label="Routes impassable"
            note={`${restricted} restricted`}
            points={metrics.closedRoutes}
            previous={at(metrics.closedRoutes, previousIndex)}
            tone="amber"
            value={`${closed}`}
          />
          <MetricRow
            activeIndex={activeIndex}
            current={peopleIsolated(worldState)}
            icon="people"
            label="People isolated"
            note={`${isolatedCommunities.length} ${isolatedCommunities.length === 1 ? "community" : "communities"}`}
            points={metrics.peopleIsolated}
            previous={at(metrics.peopleIsolated, previousIndex)}
            tone="red"
            value={peopleIsolated(worldState).toLocaleString()}
          />
          <MetricRow
            activeIndex={activeIndex}
            current={hospitalAccess}
            icon="hospital"
            label="Hospital access"
            note={hospitalAccess === totalCommunities ? "all connected" : "access lost"}
            points={metrics.hospitalAccess}
            previous={at(metrics.hospitalAccess, previousIndex)}
            riseIsBad={false}
            tone="green"
            value={`${hospitalAccess}/${totalCommunities}`}
          />
        </div>
      </section>

      {nextIsolation ? (
        <section className="rail-section forecast-callout">
          <h2>Next to isolate</h2>
          <div className="forecast-body">
            <span className="forecast-clock">
              <ShellIcon name="clock" size={15} />
            </span>
            <div>
              <strong>{names.get(nextIsolation.community_id)}</strong>
              <span>
                Loses every safe destination at{" "}
                {formatHours(nextIsolation.time_to_isolation_hours ?? 0)} under the
                current assumptions.
              </span>
            </div>
          </div>
        </section>
      ) : null}

      <section className="rail-section hazards-section">
        <div className="section-title-row">
          <h2>Top hazards</h2>
          <span>{worldState.hazards.length} active</span>
        </div>
        {worldState.hazards.length > 0 ? (
          <div className="hazard-list">
            {worldState.hazards.slice(0, 6).map((hazard) => (
              <article className={`hazard-item ${hazard.priority}`} key={hazard.hazard_id}>
                <span className="hazard-symbol">
                  <ShellIcon name={hazard.hazard_type === "community_isolated" ? "people" : "alert"} size={15} />
                </span>
                <div>
                  <strong>{describeAsset(names, bootstrap, hazard.asset_id)}</strong>
                  <span>{hazard.description ?? hazard.hazard_type.replaceAll("_", " ")}</span>
                </div>
                <em>{hazard.priority}</em>
              </article>
            ))}
          </div>
        ) : (
          <div className="quiet-state">
            <ShellIcon name="shield" size={22} />
            <strong>No active route hazards</strong>
            <span>Advance the timeline to inspect modeled degradation.</span>
          </div>
        )}
      </section>

      <footer className="model-disclaimer">
        Synthetic demonstration data · not for operational decisions
      </footer>
    </aside>
  );
}
