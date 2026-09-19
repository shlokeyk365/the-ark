import { useCallback, useEffect, useState } from "react";

import type {
  SimulationReport,
  SimulationRunSummary,
} from "@the-ark/shared-types";

import {
  createSimulationRun,
  getSimulationReport,
  listSimulationRuns,
  reportExportUrl,
} from "../api";
import { formatHours } from "../derive";
import { ShellIcon } from "./ShellIcon";

const REPORT_DATE_FORMAT = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

interface ReportsPageProps {
  activeEventIds: string[];
  scenarioName: string;
}

function reportDate(value: string) {
  return REPORT_DATE_FORMAT.format(new Date(value));
}

function signed(value: number) {
  if (value === 0) return "No change";
  return `${value > 0 ? "+" : ""}${value.toLocaleString()}`;
}

function SummaryCard({
  icon,
  value,
  label,
  tone = "cyan",
}: {
  icon: Parameters<typeof ShellIcon>[0]["name"];
  value: string;
  label: string;
  tone?: "cyan" | "amber" | "red" | "green";
}) {
  return (
    <article className={`report-summary-card ${tone}`}>
      <span><ShellIcon name={icon} size={18} /></span>
      <strong>{value}</strong>
      <small>{label}</small>
    </article>
  );
}

export function ReportsPage({ activeEventIds, scenarioName }: ReportsPageProps) {
  const [runs, setRuns] = useState<SimulationRunSummary[]>([]);
  const [selectedReport, setSelectedReport] = useState<SimulationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const openReport = useCallback(async (reportId: string, signal?: AbortSignal) => {
    setError(null);
    try {
      const report = await getSimulationReport(reportId, signal);
      setSelectedReport(report);
    } catch (requestError) {
      if (signal?.aborted) return;
      setError(
        requestError instanceof Error ? requestError.message : "Unable to load report",
      );
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const loaded = await listSimulationRuns(controller.signal);
        if (controller.signal.aborted) return;
        setRuns(loaded);
        if (loaded[0]) await openReport(loaded[0].report_id, controller.signal);
      } catch (requestError) {
        if (controller.signal.aborted) return;
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Unable to load simulation reports",
        );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [openReport]);

  const createRun = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const run = await createSimulationRun(activeEventIds);
      setSelectedReport(run.report);
      setRuns((current) => [
        {
          run_id: run.run_id,
          report_id: run.report_id,
          scenario_id: run.scenario_id,
          status: run.status,
          completed_at: run.completed_at,
          title: run.report.title,
          event_ids: run.input.event_ids,
          input_fingerprint: run.input_fingerprint,
          summary: run.report.summary,
        },
        ...current,
      ]);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to complete simulation run",
      );
    } finally {
      setRunning(false);
    }
  }, [activeEventIds]);

  const report = selectedReport;

  return (
    <main className="reports-workspace" aria-busy={loading || running}>
      <aside className="report-library panel-shell" aria-label="Simulation reports">
        <div className="report-library-heading">
          <div>
            <span className="section-eyebrow">Run archive</span>
            <h1>Simulation reports</h1>
          </div>
          <span className="report-count">{runs.length}</span>
        </div>

        <button className="create-report-button" type="button" onClick={createRun} disabled={running}>
          <ShellIcon name={running ? "activity" : "play"} size={16} />
          <span>
            <strong>{running ? "Running full horizon…" : "Run simulation"}</strong>
            <small>
              {activeEventIds.length
                ? `${activeEventIds.length} injected event active`
                : "Baseline assumptions"}
            </small>
          </span>
        </button>

        {error ? <p className="report-error" role="alert">{error}</p> : null}

        <div className="report-run-list">
          {runs.map((run) => {
            const selected = report?.report_id === run.report_id;
            return (
              <button
                aria-pressed={selected}
                className={`report-run-card ${selected ? "selected" : ""}`}
                key={run.run_id}
                onClick={() => openReport(run.report_id)}
                type="button"
              >
                <span className="report-run-icon"><ShellIcon name="report" size={15} /></span>
                <span>
                  <strong>{run.event_ids.length ? "Disrupted run" : "Baseline run"}</strong>
                  <small>{reportDate(run.completed_at)}</small>
                  <code>{run.input_fingerprint.slice(0, 10)}</code>
                </span>
                <em>{run.summary.peak_isolated_people.toLocaleString()} isolated</em>
              </button>
            );
          })}
          {!loading && runs.length === 0 ? (
            <div className="report-empty-library">
              <ShellIcon name="history" size={24} />
              <strong>No completed runs yet</strong>
              <span>Run the current scenario to create its first immutable report.</span>
            </div>
          ) : null}
        </div>
      </aside>

      <section className="report-detail panel-shell" aria-live="polite">
        {report ? (
          <>
            <header className="report-detail-heading">
              <div>
                <span className="section-eyebrow">Completed analysis</span>
                <h2>{scenarioName}</h2>
                <p>{reportDate(report.generated_at)} · {report.event_ids.length ? "Event-disrupted" : "Baseline"} run</p>
              </div>
              <div className="report-export-actions" aria-label="Report exports">
                <a href={reportExportUrl(report.report_id, "json")} download>JSON</a>
                <a href={reportExportUrl(report.report_id, "csv")} download>CSV</a>
                <a href={reportExportUrl(report.report_id, "html")} target="_blank" rel="noreferrer">
                  Print / PDF
                </a>
              </div>
            </header>

            <div className="report-disclaimer">
              <ShellIcon name="alert" size={14} />
              Modeled synthetic demonstration data · not operational guidance
            </div>

            <section className="report-summary-grid" aria-label="Report headline metrics">
              <SummaryCard icon="drop" value={`${report.summary.peak_flood_depth_m.toFixed(2)} m`} label="Peak routed-edge depth" />
              <SummaryCard icon="people" value={report.summary.peak_isolated_people.toLocaleString()} label="People isolated" tone={report.summary.peak_isolated_people ? "red" : "green"} />
              <SummaryCard icon="road" value={`${report.summary.peak_critical_routes_lost}`} label="Critical routes lost" tone={report.summary.peak_critical_routes_lost ? "amber" : "green"} />
              <SummaryCard icon="shield" value={`${report.summary.viable_plans_at_horizon}/${report.plan_analysis.length}`} label="Viable plans at horizon" tone={report.summary.viable_plans_at_horizon ? "green" : "red"} />
            </section>

            <section className="report-section report-executive">
              <div className="report-section-heading">
                <div><span>01</span><h3>Executive analysis</h3></div>
                <code>{report.run_id}</code>
              </div>
              <ul>{report.narrative.map((item) => <li key={item}>{item}</li>)}</ul>
            </section>

            <section className="report-section">
              <div className="report-section-heading">
                <div><span>02</span><h3>Material changes</h3></div>
                <em>{report.changes.length} findings</em>
              </div>
              <div className="report-change-list">
                {report.changes.map((change) => (
                  <article className={`report-change ${change.comparison}`} key={change.change_id}>
                    <span className="change-time">{formatHours(change.at_hours)}</span>
                    <span className="change-marker"><i /></span>
                    <div>
                      <span className="change-label">
                        {change.comparison === "baseline_counterfactual" ? "Event effect" : change.category}
                      </span>
                      <strong>{change.subject_name}</strong>
                      <p>{change.description}</p>
                      <code>{change.before_value} → {change.after_value}</code>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <section className="report-section">
              <div className="report-section-heading">
                <div><span>03</span><h3>Plan outcomes</h3></div>
                <em>Same frozen horizon</em>
              </div>
              <div className="report-plan-grid">
                {report.plan_analysis.map((plan, index) => (
                  <article className="report-plan" key={plan.plan_id}>
                    <span className="report-plan-letter">{String.fromCharCode(65 + index)}</span>
                    <div>
                      <strong>{plan.plan_name.replace(/^Plan [A-C] — /, "")}</strong>
                      <p>{plan.analysis}</p>
                    </div>
                    <dl>
                      <div><dt>Evacuated</dt><dd>{plan.horizon_metrics.people_evacuated_by_deadline.toLocaleString()}</dd></div>
                      <div><dt>Change</dt><dd className={plan.people_evacuated_change < 0 ? "negative" : ""}>{signed(plan.people_evacuated_change)}</dd></div>
                      <div><dt>Viable</dt><dd className={plan.horizon_metrics.plan_viable ? "positive" : "negative"}>{plan.horizon_metrics.plan_viable ? "Yes" : "No"}</dd></div>
                    </dl>
                  </article>
                ))}
              </div>
            </section>

            <section className="report-section">
              <div className="report-section-heading">
                <div><span>04</span><h3>Community impact</h3></div>
                <em>{report.community_impacts.length} communities</em>
              </div>
              <div className="report-community-grid">
                {report.community_impacts.map((community) => (
                  <article className={community.horizon_isolated ? "isolated" : ""} key={community.community_id}>
                    <div><i /><strong>{community.community_name}</strong><span>{community.population.toLocaleString()} people</span></div>
                    <p>{community.analysis}</p>
                  </article>
                ))}
              </div>
            </section>

            <section className="report-section report-governance">
              <div className="report-section-heading">
                <div><span>05</span><h3>Assumptions, limitations, and provenance</h3></div>
              </div>
              <div className="report-governance-grid">
                <div><h4>Assumptions</h4><ul>{report.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></div>
                <div><h4>Limitations</h4><ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>
              </div>
              <dl className="report-provenance">
                <div><dt>Input fingerprint</dt><dd>{report.provenance.input_fingerprint}</dd></div>
                <div><dt>Fixture SHA-256</dt><dd>{report.provenance.fixture_sha256}</dd></div>
                <div><dt>Engine</dt><dd>{report.provenance.engine_version}</dd></div>
                <div><dt>Impact prior</dt><dd>Research-only · not used</dd></div>
              </dl>
            </section>
          </>
        ) : (
          <div className="report-empty-detail">
            <span><ShellIcon name="report" size={34} /></span>
            <strong>{loading ? "Loading report archive…" : "Run a simulation to create a report"}</strong>
            <p>Each completed run freezes its inputs, analyzes all four frames, and records an immutable audit trail.</p>
          </div>
        )}
      </section>
    </main>
  );
}
