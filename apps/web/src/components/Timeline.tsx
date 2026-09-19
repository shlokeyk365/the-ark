import type {
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { formatHours } from "../derive";
import { ShellIcon } from "./ShellIcon";

interface TimelineProps {
  bootstrap: ScenarioBootstrapResponse;
  worldState: WorldStateSnapshot;
  busy: boolean;
  playing: boolean;
  activeEventIds: string[];
  onSelectFrame: (frameId: string) => void;
  onTogglePlay: () => void;
  onApplyEvent: (eventId: string) => void;
  onClearEvent: () => void;
}

export function Timeline({
  bootstrap,
  worldState,
  busy,
  playing,
  activeEventIds,
  onSelectFrame,
  onTogglePlay,
  onApplyEvent,
  onClearEvent,
}: TimelineProps) {
  const horizon = bootstrap.evaluation_horizon_hours || 1;
  const event = bootstrap.events[0];
  const eventHeld = event ? activeEventIds.includes(event.event_id) : false;
  const eventInForce = worldState.active_event_ids.length > 0;
  const eventPending = eventHeld && !eventInForce;
  const progress = (worldState.simulation_time_hours / horizon) * 100;

  return (
    <section className="timeline-card panel-shell" aria-label="Simulation timeline">
      <div className="timeline-heading">
        <h2>Simulation timeline</h2>
        <span className="timeline-context">
          {worldState.rainfall_assumption} · {bootstrap.available_frames.length} modeled
          frames · 3h steps · {horizon}h horizon
        </span>
        <span className={`live-state ${eventInForce ? "event" : eventPending ? "pending" : ""}`}>
          <i />
          {eventInForce ? "Disrupted" : eventPending ? "Event pending" : "Baseline"}
        </span>
      </div>

      <div className="timeline-controls">
        <button
          className="play-button"
          type="button"
          aria-label={playing ? "Pause frame playback" : "Play through modeled frames"}
          onClick={onTogglePlay}
          disabled={busy}
        >
          <ShellIcon name={playing ? "pause" : "play"} size={17} />
        </button>

        <div className="timeline-track">
          <div className="track-line">
            <div className="track-progress" style={{ width: `${progress}%` }} />
          </div>

          {event ? (
            <div
              className={`event-marker ${eventInForce ? "fired" : eventHeld ? "armed" : ""}`}
              style={{ left: `${(event.effective_at_hours / horizon) * 100}%` }}
              title={`${event.description} (effective ${formatHours(event.effective_at_hours)})`}
            >
              <i />
              <span>{formatHours(event.effective_at_hours)} event</span>
            </div>
          ) : null}

          {bootstrap.available_frames.map((frame) => {
            const active = frame.frame_id === worldState.frame_id;
            const passed = frame.simulation_time_hours <= worldState.simulation_time_hours;
            return (
              <button
                aria-current={active ? "true" : undefined}
                aria-label={`Show modeled frame ${formatHours(frame.simulation_time_hours)}`}
                className={`frame-stop ${active ? "active" : ""} ${passed ? "passed" : ""}`}
                disabled={busy}
                key={frame.frame_id}
                onClick={() => onSelectFrame(frame.frame_id)}
                style={{ left: `${(frame.simulation_time_hours / horizon) * 100}%` }}
                type="button"
              >
                <i />
                <span>{formatHours(frame.simulation_time_hours)}</span>
              </button>
            );
          })}
        </div>

        {event ? (
          <div className="timeline-actions">
            <button
              className={`event-button ${eventHeld ? "clear" : ""}`}
              disabled={busy}
              onClick={() => (eventHeld ? onClearEvent() : onApplyEvent(event.event_id))}
              type="button"
            >
              <ShellIcon name={eventHeld ? "reset" : "alert"} size={15} />
              {eventHeld ? "Clear injected event" : "Inject bridge failure"}
            </button>
            <span className="event-caption">
              {eventPending
                ? `Takes effect at ${formatHours(event.effective_at_hours)}`
                : eventInForce
                  ? "Operator-injected · plans recomputed"
                  : `Operator-injected · effective ${formatHours(event.effective_at_hours)}`}
            </span>
          </div>
        ) : null}
      </div>
    </section>
  );
}
