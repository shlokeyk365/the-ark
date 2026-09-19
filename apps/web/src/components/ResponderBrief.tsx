import type {
  PlanResult,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import {
  responseDestinations,
  type ResponseDestinationStatus,
} from "../derive";
import { ShellIcon } from "./ShellIcon";

interface ResponderBriefProps {
  bootstrap: ScenarioBootstrapResponse;
  worldState: WorldStateSnapshot;
  selectedPlan: PlanResult | undefined;
  focusedDestinationId: string | null;
  onFocusDestination: (destinationId: string | null, edgeIds: string[]) => void;
}

const STATUS_LABELS: Record<ResponseDestinationStatus, string> = {
  go_now: "Go now",
  priority: "Priority",
  planned: "Planned",
  blocked: "Blocked",
};

function planLetter(planId: string | undefined) {
  if (!planId) return "—";
  const match = planId.match(/plan-([a-z])$/i);
  return match?.[1]?.toUpperCase() ?? planId;
}

export function ResponderBrief({
  bootstrap,
  worldState,
  selectedPlan,
  focusedDestinationId,
  onFocusDestination,
}: ResponderBriefProps) {
  const destinations = responseDestinations(bootstrap, worldState, selectedPlan);
  const dispatchable = destinations.filter((item) => item.status !== "blocked");
  const people = dispatchable.reduce((total, item) => total + item.people, 0);
  const urgent = destinations.filter(
    (item) => item.status === "go_now" || item.status === "priority",
  ).length;

  return (
    <section className="right-section responder-brief panel-shell" aria-label="Responder destination brief">
      <div className="responder-brief-heading">
        <div>
          <span className="section-kicker">Simulation output</span>
          <h2>Where response teams go</h2>
        </div>
        <span className="brief-plan-chip">Plan {planLetter(selectedPlan?.plan_id)}</span>
      </div>

      <div className="brief-summary" aria-label="Selected plan destination summary">
        <span>
          <strong>{dispatchable.length}</strong>
          <small>reachable stops</small>
        </span>
        <span>
          <strong>{people.toLocaleString()}</strong>
          <small>people assigned</small>
        </span>
        <span>
          <strong>{urgent}</strong>
          <small>priority moves</small>
        </span>
      </div>

      {destinations.length > 0 ? (
        <div className="destination-list">
          {destinations.map((destination) => {
            const focused = destination.id === focusedDestinationId;
            const canFocus = destination.routeEdgeIds.length > 0;
            return (
              <article
                className={`destination-card ${destination.status} ${focused ? "focused" : ""}`}
                key={destination.id}
              >
                <div className="destination-rank" aria-label={`Priority ${destination.rank}`}>
                  {String(destination.rank).padStart(2, "0")}
                </div>
                <div className="destination-main">
                  <div className="destination-title-row">
                    <div>
                      <span>Primary destination</span>
                      <strong>{destination.communityName}</strong>
                    </div>
                    <em>{STATUS_LABELS[destination.status]}</em>
                  </div>

                  <p>{destination.instruction}</p>

                  <div className="destination-transfer">
                    <ShellIcon name="shelter" size={13} />
                    <span>Transfer to</span>
                    <strong>{destination.shelterName}</strong>
                  </div>

                  <div className="destination-metrics">
                    <span>
                      <ShellIcon name="people" size={12} />
                      {destination.people.toLocaleString()} assigned
                    </span>
                    <span>
                      <ShellIcon name="clock" size={12} />
                      {destination.arrivalMinutes === null
                        ? "No ETA"
                        : `${destination.arrivalMinutes} min arrival`}
                    </span>
                    <span>
                      <ShellIcon name="road" size={12} />
                      {destination.routeEdgeIds.length || 0} segments
                    </span>
                  </div>

                  <div className="destination-rationale">
                    <ShellIcon name="activity" size={12} />
                    <span>{destination.rationale.join(" · ")}</span>
                  </div>

                  <button
                    type="button"
                    className="destination-map-button"
                    disabled={!canFocus}
                    aria-pressed={focused}
                    onClick={() =>
                      onFocusDestination(
                        focused ? null : destination.id,
                        focused ? [] : destination.routeEdgeIds,
                      )
                    }
                  >
                    <ShellIcon name={focused ? "x" : "crosshair"} size={13} />
                    {focused ? "Show all plan routes" : canFocus ? "Focus route on map" : "Route unavailable"}
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="brief-empty">
          <ShellIcon name="report" size={20} />
          <strong>No destinations in this plan</strong>
          <span>Select another counterfactual plan to inspect its assignments.</span>
        </div>
      )}

      <p className="brief-disclaimer">
        Modeled synthetic decision support—not a live dispatch order. Prediction signals are
        unverified area risk; responder availability is not represented.
      </p>
    </section>
  );
}
