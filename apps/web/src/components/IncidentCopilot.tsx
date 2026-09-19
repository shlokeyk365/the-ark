import { useMemo, useState } from "react";

import type { IntelligenceReport, WorldStateSnapshot } from "@the-ark/shared-types";

interface IncidentCopilotProps {
  busy: boolean;
  reports: IntelligenceReport[];
  baseline: WorldStateSnapshot;
  tentative: WorldStateSnapshot | null;
  onSubmit: (
    message: string,
    sourceType: IntelligenceReport["source"]["type"],
    sourceName: string,
  ) => Promise<void>;
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
  reports,
  baseline,
  tentative,
  onSubmit,
  onDecision,
}: IncidentCopilotProps) {
  const [message, setMessage] = useState("");
  const [sourceType, setSourceType] =
    useState<IntelligenceReport["source"]["type"]>("field_responder");
  const [sourceName, setSourceName] = useState("Field Team");
  const impact = useMemo(
    () => impactSummary(baseline, tentative),
    [baseline, tentative],
  );
  const latest = reports[0];

  return (
    <section className="copilot-card" aria-label="Incident Copilot">
      <header className="copilot-header">
        <div>
          <span className="eyebrow">Field intelligence</span>
          <h2>Incident Copilot</h2>
        </div>
        <span className="copilot-live">AUDITABLE</span>
      </header>

      <div className="copilot-feed" aria-live="polite">
        {reports.length === 0 ? (
          <div className="copilot-empty">
            Paste a radio call, responder message, or public report. Ark will
            propose a map change without altering the baseline.
          </div>
        ) : (
          reports.slice(0, 3).map((report) => (
            <article className="intel-message" key={report.report_id}>
              <div className="intel-message-meta">
                <span>{report.source.name}</span>
                <b data-status={report.status}>{report.status}</b>
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
          ))
        )}
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
          void onSubmit(trimmed, sourceType, sourceName.trim() || "Unknown source");
          setMessage("");
        }}
      >
        <textarea
          aria-label="Field communication"
          placeholder="Rescue 4 reports ktp-bridge-02 is underwater and vehicles cannot pass."
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <div className="copilot-source-row">
          <select
            aria-label="Source type"
            value={sourceType}
            onChange={(event) =>
              setSourceType(event.target.value as IntelligenceReport["source"]["type"])
            }
          >
            <option value="field_responder">Field responder</option>
            <option value="official">Official source</option>
            <option value="operator">Operator</option>
            <option value="public">Public report</option>
            <option value="unknown">Unknown source</option>
          </select>
          <input
            aria-label="Source name"
            value={sourceName}
            onChange={(event) => setSourceName(event.target.value)}
          />
          <button type="submit" disabled={busy || !message.trim()}>Analyze</button>
        </div>
      </form>
    </section>
  );
}
