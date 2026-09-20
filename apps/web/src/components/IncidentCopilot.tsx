import { useEffect, useMemo, useRef, useState } from "react";

import type { CopilotResponse, IntelligenceReport, WorldStateSnapshot } from "@the-ark/shared-types";
import { getCopilotStatus } from "../api";

interface IncidentCopilotProps {
  busy: boolean;
  reports: IntelligenceReport[];
  replies: CopilotResponse[];
  baseline: WorldStateSnapshot;
  tentative: WorldStateSnapshot | null;
  onSubmit: (message: string) => Promise<void>;
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
  replies,
  baseline,
  tentative,
  onSubmit,
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
  useEffect(() => { feed.current?.scrollTo({ top: feed.current.scrollHeight }); }, [replies, busy]);
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
        {replies.length === 0 ? (
          <div className="copilot-empty">
            Ask about the map, compare plan results, or report a road or bridge
            status. Changes appear as previews until you confirm them.
            {configured === false ? <p>Complete the private server assistant setup to enable questions. Status commands work now.</p> : null}
          </div>
        ) : (
          replies.map((reply, index) => (
            <article className="intel-message" key={`${reply.context_digest}-${index}`}>
              <div className="intel-message-meta">
                <span>You</span>
                <b>Incident briefing</b>
              </div>
              <p>{reply.message}</p>
              <div className="intel-interpretation">
                <strong>Ark</strong>
                <span style={{ whiteSpace: "pre-wrap" }}>{reply.answer}</span>
                <small>{reply.frame_id} · {reply.world_state_version}</small>
                {reply.world_state_version !== baseline.world_state_version ? <small>Earlier snapshot — ask again for the current map.</small> : null}
              </div>
            </article>
          ))
        )}
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
          aria-label="Message Incident Copilot"
          placeholder="Ask about this map, or try: ktp-bridge-02 is blocked"
          maxLength={4000}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <button type="submit" disabled={busy || !message.trim()}>Send</button>
      </form>
    </section>
  );
}
