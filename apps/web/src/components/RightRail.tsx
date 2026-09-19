import { useEffect, useState } from "react";

import type {
  PlanMetrics,
  PlanResult,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { assetNames, describeAsset, formatHours } from "../derive";
import type { MapSelection } from "../map/selection";
import { relativeTime, type LogEntry } from "../session";
import { ShellIcon } from "./ShellIcon";

interface RightRailProps {
  bootstrap: ScenarioBootstrapResponse;
  worldState: WorldStateSnapshot;
  selectedPlanId: string;
  onSelectPlan: (planId: string) => void;
  /** Pre-event metrics, present only while viewing the recomputed state. */
  comparison: Map<string, PlanMetrics> | undefined;
  log: LogEntry[];
  selection: MapSelection | null;
  onSelect: (selection: MapSelection | null) => void;
}

const PLAN_LETTERS = ["A", "B", "C"];

/**
 * The plan a commander would take on the numbers alone: viable, evacuating the
 * most people, then finishing soonest. Returns nothing when no single plan wins,
 * so the rail never implies a recommendation the metrics do not support.
 */
function recommendedPlanId(results: PlanResult[]): string | undefined {
  const viable = results.filter(
    (result) => result.status === "current" && result.metrics.plan_viable,
  );
  if (viable.length < 2) return undefined;

  const ranked = [...viable].sort((a, b) => {
    const byPeople =
      b.metrics.people_evacuated_by_deadline - a.metrics.people_evacuated_by_deadline;
    if (byPeople !== 0) return byPeople;
    return (
      (a.metrics.evacuation_completion_minutes ?? Infinity) -
      (b.metrics.evacuation_completion_minutes ?? Infinity)
    );
  });

  const [best, runnerUp] = ranked;
  const tied =
    best.metrics.people_evacuated_by_deadline ===
      runnerUp.metrics.people_evacuated_by_deadline &&
    best.metrics.evacuation_completion_minutes ===
      runnerUp.metrics.evacuation_completion_minutes;

  return tied ? undefined : best.plan_id;
}

/**
 * "2,620 people · 3 communities → 2 shelters" for a plan's assignment set. The
 * headline number leads so it survives truncation in a narrow rail.
 */
function describePlanShape(result: PlanResult): string {
  const communities = new Set(result.assignment_results.map((a) => a.community_id));
  const shelters = new Set(result.assignment_results.map((a) => a.shelter_id));
  const people = result.assignment_results.reduce((total, a) => total + a.people, 0);
  return `${people.toLocaleString()} people · ${communities.size} communities → ${shelters.size} shelters`;
}

function MetricCell({
  icon,
  value,
  label,
  before,
  tone,
  riseIsBad = true,
  neutral = false,
  neutralReason,
}: {
  icon: Parameters<typeof ShellIcon>[0]["name"];
  value: string;
  label: string;
  before?: number;
  tone?: "viable" | "not-viable";
  riseIsBad?: boolean;
  /** Suppress the better/worse reading when the metric is not comparable. */
  neutral?: boolean;
  neutralReason?: string;
}) {
  // "—" and other non-numeric readings must not be compared as zero.
  const digits = value.replace(/[^\d.-]/g, "");
  const numeric = digits === "" ? Number.NaN : Number(digits);
  const changed = before !== undefined && Number.isFinite(numeric) && before !== numeric;
  const rising = changed && numeric > before;
  const worse = changed && (riseIsBad ? rising : !rising);

  return (
    <span className={`plan-metric ${tone ?? ""}`}>
      <ShellIcon name={icon} size={12} />
      <strong>
        {value}
        {changed ? (
          <i
            className={`metric-shift ${neutral ? "neutral" : worse ? "worse" : "better"}`}
            title={
              neutral
                ? `${rising ? "Up" : "Down"} from ${before.toLocaleString()}. ${neutralReason ?? ""}`
                : `${rising ? "Up" : "Down"} from ${before.toLocaleString()} before the event`
            }
          >
            {rising ? "▲" : "▼"}
          </i>
        ) : null}
      </strong>
      <small>{label}</small>
    </span>
  );
}

function PlanCard({
  result,
  index,
  selected,
  recommended,
  before,
  onSelect,
}: {
  result: PlanResult;
  index: number;
  selected: boolean;
  recommended: boolean;
  before: PlanMetrics | undefined;
  onSelect: () => void;
}) {
  const metrics = result.metrics;
  const shelterPressure = metrics.shelter_overload > 0;
  // Completion time is only comparable when the same people actually finish,
  // so a drop caused by failed assignments must not read as an improvement.
  const evacuationChanged =
    before !== undefined &&
    before.people_evacuated_by_deadline !== metrics.people_evacuated_by_deadline;

  return (
    <article className={`plan-card plan-${index + 1} ${selected ? "selected" : ""}`}>
      <button
        className="plan-heading"
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
      >
        <span className="plan-letter">{PLAN_LETTERS[index] ?? index + 1}</span>
        <span className="plan-identity">
          <span className="plan-name-row">
            <strong>{result.plan_name.replace(/^Plan [A-C] — /, "")}</strong>
            {recommended ? (
              <span className="plan-flag">
                <ShellIcon name="check" size={9} />
                Recommended
              </span>
            ) : null}
          </span>
          <span className="plan-shape">{describePlanShape(result)}</span>
          <span className={`plan-status ${result.status === "stale" ? "stale" : ""}`}>
            {result.status === "stale" ? "Stale — awaiting recompute" : "Current result"}
          </span>
        </span>
        <span className="plan-open">
          {selected ? "Viewing" : "Inspect"}
          <ShellIcon name="chevron" size={11} />
        </span>
      </button>
      <div className="plan-metrics">
        <MetricCell
          before={before?.evacuation_completion_minutes ?? undefined}
          icon="clock"
          label="Minutes"
          neutral={evacuationChanged}
          neutralReason="Not comparable: a different number of people completed."
          value={`${metrics.evacuation_completion_minutes ?? "—"}`}
        />
        <MetricCell
          before={before?.people_evacuated_by_deadline}
          icon="people"
          label="Evacuated"
          riseIsBad={false}
          value={metrics.people_evacuated_by_deadline.toLocaleString()}
        />
        <MetricCell
          before={before?.critical_routes_lost}
          icon="road"
          label="Routes lost"
          value={`${metrics.critical_routes_lost}`}
        />
        <MetricCell
          icon="shield"
          label="Viable"
          tone={metrics.plan_viable ? "viable" : "not-viable"}
          value={metrics.plan_viable ? "YES" : "NO"}
        />
      </div>
      {shelterPressure ? (
        <div className="plan-footnote">
          <ShellIcon name="alert" size={12} />
          {metrics.shelter_overload.toLocaleString()} people over shelter capacity
        </div>
      ) : null}
    </article>
  );
}

export function RightRail({
  bootstrap,
  worldState,
  selectedPlanId,
  onSelectPlan,
  comparison,
  log,
  selection,
  onSelect,
}: RightRailProps) {
  const names = assetNames(bootstrap);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 15000);
    return () => window.clearInterval(timer);
  }, []);

  const connected = worldState.community_access.filter((access) => !access.isolated).length;
  const recommended = recommendedPlanId(worldState.plan_results);

  return (
    <aside className="right-rail" aria-label="Response plans, alerts and activity">
      <section className="right-section plans-panel panel-shell">
        <div className="section-title-row">
          <h2>
            Response plans <span>(counterfactuals)</span>
          </h2>
          <span
            className="help-mark"
            title="Every plan is scored against the same frozen world state version"
          >
            ?
          </span>
        </div>
        {comparison ? (
          <p className="panel-note">
            Compared against the pre-event result for{" "}
            {worldState.world_state_version}.
          </p>
        ) : null}
        <div className="plans-list">
          {worldState.plan_results.map((result, index) => (
            <PlanCard
              before={comparison?.get(result.plan_id)}
              index={index}
              key={result.plan_id}
              onSelect={() => onSelectPlan(result.plan_id)}
              recommended={result.plan_id === recommended}
              result={result}
              selected={result.plan_id === selectedPlanId}
            />
          ))}
        </div>
      </section>

      <section className="right-section alerts-panel panel-shell">
        <div className="section-title-row">
          <h2>Prioritized alerts</h2>
          <span className={`alert-count ${worldState.hazards.length === 0 ? "zero" : ""}`}>
            {worldState.hazards.length}
          </span>
        </div>
        {worldState.hazards.length > 0 ? (
          <div className="hazard-list alert-list">
            {worldState.hazards.map((hazard) => {
              const focused =
                selection?.kind === "hazard" && selection.id === hazard.hazard_id;
              return (
                <button
                  aria-pressed={focused}
                  className={`hazard-item ${hazard.priority} ${focused ? "focused" : ""}`}
                  key={hazard.hazard_id}
                  onClick={() =>
                    onSelect(focused ? null : { kind: "hazard", id: hazard.hazard_id })
                  }
                  type="button"
                >
                  <em>{hazard.priority}</em>
                  <div>
                    <strong>{describeAsset(names, bootstrap, hazard.asset_id)}</strong>
                    <span>{hazard.description ?? hazard.hazard_type.replaceAll("_", " ")}</span>
                  </div>
                  <span className="hazard-origin">
                    {hazard.source_event_id ? "injected" : "modeled"}
                    <i>{hazard.source_frame_id.replace("ktp-frame-", "")}</i>
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="quiet-state right-quiet">
            <span className="quiet-mark">
              <ShellIcon name="shield" size={20} />
            </span>
            <strong>No active alerts at this frame</strong>
            <span>The modeled network is fully traversable.</span>
          </div>
        )}
      </section>

      <section className="right-section access-panel panel-shell">
        <div className="section-title-row">
          <h2>Community access</h2>
          <span className="access-tally">
            <i className={connected === worldState.community_access.length ? "" : "warn"} />
            {connected}/{worldState.community_access.length} connected
          </span>
        </div>
        <div className="access-grid">
          {worldState.community_access.map((access) => (
            <div
              className={`access-cell ${access.isolated ? "is-isolated" : ""}`}
              key={access.community_id}
            >
              <span className="access-head">
                <i className={access.isolated ? "isolated" : "connected"} />
                <strong>{names.get(access.community_id)}</strong>
                <span className={`access-eta ${access.isolated ? "now" : ""}`}>
                  {access.isolated
                    ? "Isolated"
                    : access.time_to_isolation_hours === null
                      ? "Holds"
                      : formatHours(access.time_to_isolation_hours)}
                </span>
              </span>
              <span className="access-detail">
                {access.isolated
                  ? "No route to an open shelter or hospital"
                  : `${access.reachable_shelter_ids.length} shelters · ${
                      access.hospital_accessible ? "hospital reachable" : "hospital lost"
                    }`}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="right-section log-panel panel-shell">
        <div className="section-title-row">
          <h2>Decision log</h2>
          <span>{log.length} entries</span>
        </div>
        <div className="log-list">
          {log.slice(0, 8).map((entry) => (
            <article className={`log-item ${entry.kind}`} key={entry.id}>
              <span className="log-icon">
                <ShellIcon
                  name={
                    entry.kind === "event"
                      ? "alert"
                      : entry.kind === "recompute"
                        ? "activity"
                        : entry.kind === "reset"
                          ? "reset"
                          : "history"
                  }
                  size={12}
                />
              </span>
              <div>
                <strong>{entry.title}</strong>
                <span>{entry.detail}</span>
                <code>{entry.worldStateVersion}</code>
              </div>
              <em>{relativeTime(entry.at, now)}</em>
            </article>
          ))}
        </div>
      </section>
    </aside>
  );
}
