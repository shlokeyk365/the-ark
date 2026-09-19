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
import type { MapSelection } from "../map/selection";
import { ShellIcon } from "./ShellIcon";
import { Delta, Sparkline, type Tone } from "./Trend";

interface IncidentSidebarProps {
  bootstrap: ScenarioBootstrapResponse;
  worldState: WorldStateSnapshot;
  series: FrameSeriesEntry[];
  selection: MapSelection | null;
  onSelect: (selection: MapSelection | null) => void;
}

interface MetricCardProps {
  icon: Parameters<typeof ShellIcon>[0]["name"];
  tone: Tone;
  value: string;
  unit?: string;
  label: string;
  note: string;
  points: number[];
  activeIndex: number;
  previous: number | undefined;
  current: number;
  riseIsBad?: boolean;
}

function MetricCard({
  icon,
  tone,
  value,
  unit,
  label,
  note,
  points,
  activeIndex,
  previous,
  current,
  riseIsBad = true,
}: MetricCardProps) {
  return (
    <article className={`metric-card tone-${tone}`}>
      <span className="metric-icon">
        <ShellIcon name={icon} size={17} />
      </span>
      <div className="metric-value">
        <strong>
          {value}
          {unit ? <i>{unit}</i> : null}
        </strong>
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
    </article>
  );
}

export function IncidentSidebar({
  bootstrap,
  worldState,
  series,
  selection,
  onSelect,
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
  const disrupted = worldState.active_event_ids.length > 0;

  const nextIsolation = worldState.community_access
    .filter((access) => access.time_to_isolation_hours !== null && !access.isolated)
    .sort(
      (a, b) =>
        (a.time_to_isolation_hours ?? Infinity) - (b.time_to_isolation_hours ?? Infinity),
    )[0];

  const leadHours = nextIsolation
    ? (nextIsolation.time_to_isolation_hours ?? 0) - worldState.simulation_time_hours
    : 0;

  return (
    <aside className="left-rail panel-shell" aria-label="Incident overview">
      <section className="incident-summary">
        <div className="section-eyebrow">
          <span>Incident overview</span>
          <span className={`status-badge ${disrupted ? "disrupted" : ""}`}>
            <i aria-hidden="true" />
            {disrupted ? "Disrupted" : "Modeled"}
          </span>
        </div>
        <h1>Kantipur River Flood Exercise</h1>
        <p>{bootstrap.description}</p>
        <div className="incident-meta">
          <span className="meta-chip">
            <ShellIcon name="clock" size={11} />
            {formatHours(worldState.simulation_time_hours)}
          </span>
          <span className="meta-chip mono">{worldState.world_state_version}</span>
        </div>
        <div className="weather-callout">
          <span className="weather-icon">
            <ShellIcon name="rain" size={22} />
          </span>
          <div>
            <strong>{worldState.rainfall_assumption}</strong>
            <span>{worldState.rainfall_multiplier.toFixed(1)}× modeled rainfall</span>
          </div>
          <span className="weather-depth">
            <strong>
              {depthCm}
              <i>cm</i>
            </strong>
            <em>peak depth</em>
          </span>
        </div>
      </section>

      <section className="rail-section">
        <div className="section-title-row">
          <h2>Current conditions</h2>
          <span className="live-tag">
            <i aria-hidden="true" />
            {formatHours(worldState.simulation_time_hours)} frame
          </span>
        </div>
        <div className="metric-stack">
          <MetricCard
            activeIndex={activeIndex}
            current={depthCm}
            icon="drop"
            label="Peak modeled depth"
            note={`across ${worldState.edge_states.length} edges`}
            points={metrics.maxDepthCm}
            previous={at(metrics.maxDepthCm, previousIndex)}
            tone="cyan"
            unit="cm"
            value={`${depthCm}`}
          />
          <MetricCard
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
          <MetricCard
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
          <MetricCard
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
          <div className="section-title-row">
            <h2>Next key event</h2>
            <span>{leadHours > 0 ? `in ${leadHours}h` : "now"}</span>
          </div>
          <button
            className="forecast-body"
            onClick={() =>
              onSelect({ kind: "asset", id: nextIsolation.community_id })
            }
            type="button">
            <span className="forecast-clock">
              <ShellIcon name="alert" size={15} />
            </span>
            <div>
              <strong>{names.get(nextIsolation.community_id)}</strong>
              <span>
                Loses every safe destination at{" "}
                {formatHours(nextIsolation.time_to_isolation_hours ?? 0)} under the
                current assumptions.
              </span>
            </div>
            <span className="forecast-mark" aria-hidden="true">
              <ShellIcon name="chevron" size={12} />
            </span>
          </button>
        </section>
      ) : null}

      <section className="rail-section hazards-section">
        <div className="section-title-row">
          <h2>Key hazards</h2>
          <span>{worldState.hazards.length} active</span>
        </div>
        {worldState.hazards.length > 0 ? (
          <div className="hazard-list">
            {worldState.hazards.slice(0, 6).map((hazard) => {
              const focused =
                selection?.kind === "hazard" && selection.id === hazard.hazard_id;
              return (
                <button
                  aria-pressed={focused}
                  className={`hazard-item ${hazard.priority} ${focused ? "focused" : ""}`}
                  key={hazard.hazard_id}
                  onClick={() =>
                    onSelect(
                      focused ? null : { kind: "hazard", id: hazard.hazard_id },
                    )
                  }
                  type="button"
                >
                  <span className="hazard-symbol">
                    <ShellIcon
                      name={hazard.hazard_type === "community_isolated" ? "people" : "alert"}
                      size={14}
                    />
                  </span>
                  <div>
                    <strong>{describeAsset(names, bootstrap, hazard.asset_id)}</strong>
                    <span>{hazard.description ?? hazard.hazard_type.replaceAll("_", " ")}</span>
                  </div>
                  <em>{hazard.priority}</em>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="quiet-state">
            <span className="quiet-mark">
              <ShellIcon name="shield" size={20} />
            </span>
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
