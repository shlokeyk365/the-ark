import type { WorldStateSnapshot } from "@the-ark/shared-types";

import {
  hospitalAccessCount,
  maxFloodDepth,
  peopleIsolated,
} from "../derive";
import { ShellIcon } from "./ShellIcon";

interface TopStatusMetricsProps {
  worldState: WorldStateSnapshot;
}

interface Metric {
  label: string;
  value: string;
  detail: string;
  tone: "cyan" | "amber" | "red" | "green" | "muted";
  icon: Parameters<typeof ShellIcon>[0]["name"];
}

/**
 * The compact operational readout that sits above the map canvas. Values are
 * deliberately projections of the current immutable world state: this
 * component does not infer a river gauge, weather rate, or risk score.
 */
export function TopStatusMetrics({ worldState }: TopStatusMetricsProps) {
  const closed = worldState.edge_states.filter((edge) => edge.status === "closed").length;
  const restricted = worldState.edge_states.filter(
    (edge) => edge.status === "restricted",
  ).length;
  const hospitalAccess = hospitalAccessCount(worldState);
  const communityCount = worldState.community_access.length;

  const metrics: Metric[] = [
    {
      label: "Peak modeled depth",
      value: `${Math.round(maxFloodDepth(worldState) * 100)} cm`,
      detail: "Network-edge reading",
      tone: "cyan",
      icon: "drop",
    },
    {
      label: "Routes impassable",
      value: `${closed}`,
      detail: `${restricted} restricted`,
      tone: "amber",
      icon: "road",
    },
    {
      label: "People isolated",
      value: peopleIsolated(worldState).toLocaleString(),
      detail: "Graph-derived population",
      tone: "red",
      icon: "people",
    },
    {
      label: "Hospital access",
      value: `${hospitalAccess}/${communityCount}`,
      detail: "Communities connected",
      tone: "green",
      icon: "hospital",
    },
    {
      label: "Rainfall assumption",
      value: `${worldState.rainfall_multiplier.toFixed(1)}×`,
      detail: worldState.rainfall_assumption,
      tone: "muted",
      icon: "rain",
    },
  ];

  return (
    <section className="top-status-metrics" aria-label="Current operations status">
      <div className="top-status-title">
        <span>Operations status</span>
        <small>Current world state</small>
      </div>
      <div className="top-status-grid">
        {metrics.map((metric) => (
          <article className={`top-status-card ${metric.tone}`} key={metric.label}>
            <span className="top-status-icon"><ShellIcon name={metric.icon} size={15} /></span>
            <div>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
              <small>{metric.detail}</small>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
