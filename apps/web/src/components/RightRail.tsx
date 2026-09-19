import { useEffect, useState } from "react";

import type {
  PlanMetrics,
  PlanResult,
  PredictionSignal,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { assetNames, describeAsset, formatHours } from "../derive";
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
}

const PLAN_LETTERS = ["A", "B", "C"];

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
      <ShellIcon name={icon} size={13} />
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
  before,
  onSelect,
}: {
  result: PlanResult;
  index: number;
  selected: boolean;
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
      <div className="plan-heading">
        <span className="plan-letter">{PLAN_LETTERS[index] ?? index + 1}</span>
        <div>
          <strong>{result.plan_name.replace(/^Plan [A-C] — /, "")}</strong>
          <span className={result.status === "stale" ? "stale" : ""}>
            {result.status === "stale" ? "Stale — awaiting recompute" : "Current result"}
          </span>
        </div>
        <button type="button" onClick={onSelect} aria-pressed={selected}>
          {selected ? "Viewing" : "Inspect"}
          <ShellIcon name="chevron" size={12} />
        </button>
      </div>
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
}: RightRailProps) {
  const names = assetNames(bootstrap);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 15000);
    return () => window.clearInterval(timer);
  }, []);

  const connected = worldState.community_access.filter((access) => !access.isolated).length;
  const signalSummaries = Array.from(
    worldState.prediction_signals.reduce(
      (groups, signal) => {
        const current = groups.get(signal.target);
        if (!current) {
          groups.set(signal.target, { signal, count: 1 });
        } else {
          groups.set(signal.target, {
            signal:
              signal.priority_score > current.signal.priority_score
                ? signal
                : current.signal,
            count: current.count + 1,
          });
        }
        return groups;
      },
      new Map<string, { signal: PredictionSignal; count: number }>(),
    ).values(),
  );

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
              result={result}
              selected={result.plan_id === selectedPlanId}
            />
          ))}
        </div>
      </section>

      <section className="right-section model-signals-panel panel-shell">
        <div className="section-title-row">
          <h2>Model prediction pings</h2>
          <span>{bootstrap.impact_model.evaluation.unseen_district_roc_auc.toFixed(2)} AUC</span>
        </div>
        <div className="model-signal-grid">
          {signalSummaries.map(({ signal, count }) => (
            <article
              className={`model-signal ${signal.target} ${signal.state}`}
              key={signal.ping_id}
              title={signal.recommended_action}
            >
              <i />
              <div>
                <strong>{signal.percent}%</strong>
                <span>
                  #{signal.priority_rank} {signal.priority_level} · {count} locations · prior {signal.base_percent}%
                </span>
              </div>
              <em>{signal.state}</em>
            </article>
          ))}
        </div>
        <p className="model-signal-note">
          Local risk combines the event prior with hazard, access, and exposed population.
          Pings remain area indicators, not building-level forecasts. Prototype only—not validated
          for live dispatch.
        </p>
      </section>

      <section className="right-section alerts-panel panel-shell">
        <div className="section-title-row">
          <h2>Prioritized alerts</h2>
          <span className={`alert-count ${worldState.hazards.length === 0 ? "zero" : ""}`}>
            {worldState.hazards.length}
          </span>
        </div>
        {worldState.hazards.length > 0 ? (
          <div className="hazard-list">
            {worldState.hazards.map((hazard) => (
              <article className={`hazard-item ${hazard.priority}`} key={hazard.hazard_id}>
                <span className="hazard-symbol">
                  <ShellIcon
                    name={hazard.hazard_type === "community_isolated" ? "people" : "alert"}
                    size={15}
                  />
                </span>
                <div>
                  <strong>{describeAsset(names, bootstrap, hazard.asset_id)}</strong>
                  <span>{hazard.description ?? hazard.hazard_type.replaceAll("_", " ")}</span>
                  <span className="hazard-origin">
                    {hazard.source_event_id ? "operator-injected" : "modeled"} ·{" "}
                    {hazard.source_frame_id.replace("ktp-frame-", "")}
                  </span>
                </div>
                <em>{hazard.priority}</em>
              </article>
            ))}
          </div>
        ) : (
          <div className="quiet-state right-quiet">
            <ShellIcon name="shield" size={24} />
            <strong>No active alerts at this frame</strong>
            <span>The modeled network is fully traversable.</span>
          </div>
        )}
      </section>

      <section className="right-section access-panel panel-shell">
        <div className="section-title-row">
          <h2>Community access</h2>
          <span>
            {connected}/{worldState.community_access.length} connected
          </span>
        </div>
        <div className="access-list">
          {worldState.community_access.map((access) => (
            <div
              className={`access-row ${access.isolated ? "is-isolated" : ""}`}
              key={access.community_id}
            >
              <i className={access.isolated ? "isolated" : "connected"} />
              <div>
                <strong>{names.get(access.community_id)}</strong>
                <span>
                  {access.isolated
                    ? "No route to an open shelter or hospital"
                    : `${access.reachable_shelter_ids.length} shelters · ${
                        access.hospital_accessible ? "hospital reachable" : "hospital lost"
                      }`}
                </span>
              </div>
              <em className={access.isolated ? "now" : ""}>
                {access.isolated
                  ? "isolated"
                  : access.time_to_isolation_hours === null
                    ? "—"
                    : formatHours(access.time_to_isolation_hours)}
              </em>
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
                  size={13}
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
