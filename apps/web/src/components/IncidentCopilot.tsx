import { useEffect, useMemo, useRef, useState } from "react";

import type {
  CopilotAnswer,
  IntelligenceReport,
  MapSummaryResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";
import { getCopilotStatus } from "../api";

interface IncidentCopilotProps {
  busy: boolean;
  answers: CopilotAnswer[];
  reports: IntelligenceReport[];
  summary: MapSummaryResponse | null;
  baseline: WorldStateSnapshot;
  tentative: WorldStateSnapshot | null;
  onSubmit: (message: string) => Promise<void>;
  onSummarize: () => Promise<void>;
  onDismissSummary: () => void;
  onDeleteAnswer: (answerId: string) => void;
  onDelete: (reportId: string) => Promise<void>;
  onDecision: (
    reportId: string,
    decision: "confirm" | "keep_tentative" | "reject",
  ) => Promise<void>;
}

function impactSummary(
  baseline: WorldStateSnapshot,
  tentative: WorldStateSnapshot | null,
) {
  if (!tentative) return null;
  const beforeClosed = baseline.edge_states.filter((edge) => edge.status === "closed").length;
  const afterClosed = tentative.edge_states.filter((edge) => edge.status === "closed").length;
  const beforeIsolated = baseline.community_access.filter(
    (community) => community.isolated,
  ).length;
  const afterIsolated = tentative.community_access.filter(
    (community) => community.isolated,
  ).length;
  return {
    closedDelta: afterClosed - beforeClosed,
    isolatedDelta: afterIsolated - beforeIsolated,
    invalidPlans: tentative.plan_results.filter((plan) => !plan.metrics.plan_viable).length,
  };
}

export function IncidentCopilot({
  busy,
  answers,
  reports,
  summary,
  baseline,
  tentative,
  onSubmit,
  onSummarize,
  onDismissSummary,
  onDeleteAnswer,
  onDelete,
  onDecision,
}: IncidentCopilotProps) {
  const [message, setMessage] = useState("");
  const [configured, setConfigured] = useState<boolean | null>(null);
  const feed = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let cancelled = false;
    const refresh = () => void getCopilotStatus().then((status) => {
      if (!cancelled) setConfigured(status.assistant_configured);
    }).catch(() => { if (!cancelled) setConfigured(null); });
    refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);
  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight });
  }, [answers, reports, summary, busy]);
  const impact = useMemo(
    () => impactSummary(baseline, tentative),
    [baseline, tentative],
  );
  const latest = reports[0];

  return (
    <section className="copilot-card" aria-label="Incident Copilot">
      <header className="copilot-header">
        <div>
          <span className="eyebrow">Map-grounded assistant</span>
          <h2>Incident Copilot</h2>
        </div>
        <span className="copilot-live">{configured ? "LIVE" : configured === false ? "SETUP NEEDED" : "CONNECTING"}</span>
      </header>

      <div className="copilot-feed" aria-live="polite" ref={feed}>
        {!summary && answers.length === 0 && reports.length === 0 ? (
          <div className="copilot-empty">
            Ask about the current map, responder simulation, or plans. A supported
            field report will propose a map change without altering the baseline.
          </div>
        ) : null}
        {summary ? (
          <article className="intel-message map-summary-message">
            <div className="intel-message-meta">
              <span>Claude map briefing</span>
              <div className="intel-message-actions">
                <b data-status="confirmed">current</b>
                <button
                  aria-label="Delete map summary"
                  className="intel-delete"
                  disabled={busy}
                  onClick={onDismissSummary}
                  title="Delete summary"
                  type="button"
                >
                  ×
                </button>
              </div>
            </div>
            <strong className="map-summary-headline">{summary.headline}</strong>
            <p>{summary.overview}</p>
            <div className="map-summary-priorities">
              <strong>Operational priorities</strong>
              <ol>
                {summary.priorities.map((priority) => (
                  <li key={priority}>{priority}</li>
                ))}
              </ol>
            </div>
            {summary.recommended_plan ? (
              <p className="map-summary-plan">{summary.recommended_plan}</p>
            ) : null}
            <div className="copilot-evidence">
              <strong>Grounded evidence</strong>
              <span>{summary.evidence_ids.join(" · ")}</span>
            </div>
            <small>
              {summary.model} · State {summary.source_world_state_version} · {summary.limitations[0]}
            </small>
          </article>
        ) : null}
        {answers.slice(0, 5).map((answer) => {
          const current = answer.source_world_state_version === baseline.world_state_version;
          return (
            <article className="intel-message copilot-answer" key={answer.answer_id}>
              <div className="intel-message-meta">
                <span>
                  {answer.provider === "claude"
                    ? "Claude · grounded answer"
                    : "Deterministic map lookup"}
                </span>
                <div className="intel-message-actions">
                  <b data-status={current ? "confirmed" : "rejected"}>
                    {current ? "current" : "older state"}
                  </b>
                  <button
                    aria-label="Delete chatbot answer"
                    className="intel-delete"
                    disabled={busy}
                    onClick={() => onDeleteAnswer(answer.answer_id)}
                    title="Delete answer"
                    type="button"
                  >
                    ×
                  </button>
                </div>
              </div>
              <strong className="copilot-question">{answer.question}</strong>
              <p>{answer.message}</p>
              <div className="copilot-evidence">
                <strong>Evidence</strong>
                <span>{answer.evidence_ids.join(" · ")}</span>
              </div>
              <small>
                {answer.model ? `${answer.model} · ` : ""}
                State {answer.source_world_state_version}
                {answer.limitations[0] ? ` · ${answer.limitations[0]}` : ""}
              </small>
            </article>
          );
        })}
        {reports.slice(0, 3).map((report) => (
          <article className="intel-message" key={report.report_id}>
            <div className="intel-message-meta">
              <span>{report.source.name}</span>
              <div className="intel-message-actions">
                <b data-status={report.status}>{report.status}</b>
                <button
                  aria-label={`Delete report from ${report.source.name}`}
                  className="intel-delete"
                  disabled={busy}
                  onClick={() => void onDelete(report.report_id)}
                  title="Delete report"
                  type="button"
                >
                  ×
                </button>
              </div>
            </div>
            <p>{report.message}</p>
            <div className="intel-interpretation">
              <strong>Ark interpretation</strong>
              <span>{report.claim.summary}</span>
              <small>
                {report.asset_match
                  ? `${report.asset_match.display_name} · location match ${Math.round(
                      report.asset_match.confidence * 100,
                    )}%`
                  : "No map asset resolved"}
              </small>
            </div>
          </article>
        ))}
        {busy ? <p className="copilot-empty">Reading the current state…</p> : null}
      </div>

      {latest && latest.status !== "rejected" && latest.status !== "confirmed" ? (
        <div className="copilot-review">
          <div className="copilot-review-title">
            <strong>Proposed update</strong>
            <span>Baseline unchanged</span>
          </div>
          <p>{latest.proposed_change.reason}</p>
          {impact ? (
            <div className="copilot-impact">
              <span><b>{impact.closedDelta > 0 ? `+${impact.closedDelta}` : "0"}</b>routes closed</span>
              <span><b>{impact.isolatedDelta > 0 ? `+${impact.isolatedDelta}` : "0"}</b>communities isolated</span>
              <span><b>{impact.invalidPlans}</b>nonviable plans</span>
            </div>
          ) : null}
          <div className="copilot-actions">
            <button
              type="button"
              disabled={busy || latest.proposed_change.change_type === "none"}
              onClick={() => onDecision(latest.report_id, "confirm")}
            >
              Confirm update
            </button>
            <button type="button" disabled={busy} onClick={() => onDecision(latest.report_id, "keep_tentative")}>
              Keep tentative
            </button>
            <button type="button" disabled={busy} onClick={() => onDecision(latest.report_id, "reject")}>
              Reject
            </button>
          </div>
        </div>
      ) : null}

      <form
        className="copilot-composer"
        onSubmit={(event) => {
          event.preventDefault();
          const trimmed = message.trim();
          if (!trimmed || busy) return;
          void onSubmit(trimmed);
          setMessage("");
        }}
      >
        <textarea
          aria-label="Field communication"
          placeholder="Ask about routes and responders, or report that a mapped road is blocked."
          maxLength={4000}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <div className="copilot-submit-row">
          <button
            className="copilot-summary-button"
            disabled={busy}
            onClick={() => void onSummarize()}
            type="button"
          >
            Summarize map
          </button>
          <button type="submit" disabled={busy || !message.trim()}>Analyze</button>
        </div>
      </form>
    </section>
  );
}
