import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";

import type {
  CopilotResponse,
  IntelligenceReport,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { getCopilotStatus } from "../api";
import { ShellIcon } from "./ShellIcon";

export interface CommandChatSession {
  busy: boolean;
  replies: CopilotResponse[];
  reports: IntelligenceReport[];
  baseline: WorldStateSnapshot;
  tentative: WorldStateSnapshot | null;
  onSubmit: (message: string) => Promise<void>;
  onDecision: (
    reportId: string,
    decision: "confirm" | "keep_tentative" | "reject",
  ) => Promise<void>;
}

interface CommandChatOverlayProps {
  open: boolean;
  onClose: () => void;
  session?: CommandChatSession;
}

const SUGGESTIONS = [
  "Which community becomes isolated first?",
  "Compare Plan A, B, and C",
  "Hospital access at +12h",
  "Nakkhu East Bridge is blocked",
];

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

export function CommandChatOverlay({ open, onClose, session }: CommandChatOverlayProps) {
  const titleId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const threadRef = useRef<HTMLOListElement>(null);
  const [prompt, setPrompt] = useState("");
  const [configured, setConfigured] = useState<boolean | null>(null);

  const replies = session?.replies ?? [];
  const reports = session?.reports ?? [];
  const busy = session?.busy ?? false;
  const latest = reports[0];
  const impact = useMemo(
    () => (session ? impactSummary(session.baseline, session.tentative) : null),
    [session],
  );

  useEffect(() => {
    if (!open) return;

    const previous = document.activeElement;
    const frame = window.requestAnimationFrame(() => {
      inputRef.current?.focus();
    });

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKeyDown);
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const refresh = () =>
      void getCopilotStatus()
        .then((status) => {
          if (!cancelled) setConfigured(status.assistant_configured);
        })
        .catch(() => {
          if (!cancelled) setConfigured(null);
        });
    refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [open]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [replies, busy, open]);

  if (!open) return null;

  const submitPrompt = (message: string) => {
    const trimmed = message.trim();
    if (!trimmed || busy || !session) return;
    void session.onSubmit(trimmed);
    setPrompt("");
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submitPrompt(prompt);
  };

  const pendingReview =
    latest && latest.status !== "rejected" && latest.status !== "confirmed";

  return createPortal(
    <div className="command-chat-root">
      <button
        className="command-chat-backdrop"
        type="button"
        aria-label="Dismiss command chat"
        onClick={onClose}
      />
      <div
        className="command-chat-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="command-chat-shine" aria-hidden="true" />
        <div className="command-chat-spec" aria-hidden="true" />

        <form className="command-chat-search" onSubmit={onSubmit}>
          <ShellIcon name="search" size={18} />
          <h2 id={titleId} className="sr-only">
            Ask ARK
          </h2>
          <input
            ref={inputRef}
            name="prompt"
            type="text"
            autoComplete="off"
            spellCheck={false}
            maxLength={4000}
            disabled={busy || !session}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Ask about isolation, routes, or plans…"
            aria-label="Ask ARK"
          />
          <kbd className="command-chat-esc">esc</kbd>
          <button
            className="command-chat-send"
            type="submit"
            disabled={busy || !session || !prompt.trim()}
          >
            Send
          </button>
          <button
            className="command-chat-close"
            type="button"
            aria-label="Close command chat"
            onClick={onClose}
          >
            <ShellIcon name="x" size={14} />
          </button>
        </form>

        <div className="command-chat-body">
          <ol className="command-chat-thread" aria-label="Conversation" ref={threadRef}>
            {replies.length === 0 ? (
              <li className="command-chat-empty">
                Ask about the current map, compare plans, or report a road or bridge
                status. Map changes stay tentative until you confirm them.
                {configured === false ? (
                  <span> Assistant setup is still needed; status commands work now.</span>
                ) : null}
              </li>
            ) : (
              replies.map((reply, index) => (
                <li key={`${reply.context_digest}-${index}`} className="command-chat-turn">
                  <div className="command-chat-message user">
                    <span className="command-chat-role">You</span>
                    <p>{reply.message}</p>
                  </div>
                  <div className="command-chat-message assistant">
                    <span className="command-chat-role">ARK</span>
                    <p>{reply.answer}</p>
                    <small>
                      {reply.frame_id} · {reply.world_state_version}
                      {session &&
                      reply.world_state_version !== session.baseline.world_state_version
                        ? " · earlier snapshot"
                        : ""}
                    </small>
                  </div>
                </li>
              ))
            )}
            {busy ? (
              <li className="command-chat-empty">Reading the current world state…</li>
            ) : null}
          </ol>

          {pendingReview && session ? (
            <div className="command-chat-review">
              <div className="command-chat-review-title">
                <strong>Proposed update</strong>
                <span>Baseline unchanged</span>
              </div>
              <p>{latest.proposed_change.reason}</p>
              {impact ? (
                <div className="command-chat-impact">
                  <span>
                    <b>{impact.closedDelta > 0 ? `+${impact.closedDelta}` : "0"}</b>
                    routes closed
                  </span>
                  <span>
                    <b>{impact.isolatedDelta > 0 ? `+${impact.isolatedDelta}` : "0"}</b>
                    communities isolated
                  </span>
                  <span>
                    <b>{impact.invalidPlans}</b>
                    nonviable plans
                  </span>
                </div>
              ) : null}
              <div className="command-chat-actions">
                <button
                  type="button"
                  disabled={busy || latest.proposed_change.change_type === "none"}
                  onClick={() => session.onDecision(latest.report_id, "confirm")}
                >
                  Confirm
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => session.onDecision(latest.report_id, "keep_tentative")}
                >
                  Keep tentative
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => session.onDecision(latest.report_id, "reject")}
                >
                  Reject
                </button>
              </div>
            </div>
          ) : null}

          <div className="command-chat-suggestions">
            <span className="command-chat-hint">Suggested</span>
            {SUGGESTIONS.map((item) => (
              <button
                key={item}
                type="button"
                disabled={busy || !session}
                onClick={() => submitPrompt(item)}
              >
                {item}
              </button>
            ))}
          </div>
        </div>

        <footer className="command-chat-footer">
          <span>
            AI interpretation
            {configured ? " · live" : configured === false ? " · setup needed" : ""}
          </span>
          <span>Not operational truth</span>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
