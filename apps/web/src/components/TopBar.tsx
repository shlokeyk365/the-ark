import { ShellIcon } from "./ShellIcon";
import type { WorldStateSnapshot } from "@the-ark/shared-types";

interface TopBarProps {
  alertCount?: number;
  worldState?: WorldStateSnapshot;
  activeView?: "operations" | "reports";
  onNavigate?: (view: "operations" | "reports") => void;
}

export function TopBar({
  alertCount = 0,
  worldState,
  activeView = "operations",
  onNavigate,
}: TopBarProps) {
  return (
    <header className="topbar">
      <a className="brand" href="/" aria-label="Back to ARK landing page" title="Back to landing page">
        <span className="brand-mark">
          <img
            src="/assets/ark-longboat-logo.png"
            alt=""
            className="brand-logo"
          />
        </span>
        <span className="brand-name">ARK</span>
        <span className="brand-divider">/</span>
        <span className="brand-context">FLOODWORLD</span>
      </a>

      <nav className="command-view-tabs" aria-label="Command center views">
        <a className="command-home-link" href="/" title="Back to landing page">
          Home
        </a>
        <button
          aria-current={activeView === "operations" ? "page" : undefined}
          className={activeView === "operations" ? "active" : ""}
          onClick={() => onNavigate?.("operations")}
          type="button"
        >
          <ShellIcon name="map" size={13} /> Operations
        </button>
        <button
          aria-current={activeView === "reports" ? "page" : undefined}
          className={activeView === "reports" ? "active" : ""}
          onClick={() => onNavigate?.("reports")}
          type="button"
        >
          <ShellIcon name="report" size={13} /> Reports
        </button>
      </nav>

      <div className="command-tools">
        {worldState ? (
          <span className="operations-readout">
            <i />
            <span>{worldState.simulation_time_hours === 0 ? "NOW" : `+${worldState.simulation_time_hours}H`}</span>
            <span>{worldState.world_state_version}</span>
          </span>
        ) : null}
        <button className="icon-button" type="button" aria-label={`${alertCount} active alerts`} title={`${alertCount} active alerts`}>
          <ShellIcon name="bell" size={17} />
          {alertCount > 0 ? <span className="notification-dot" /> : null}
        </button>
        <div className="command-title">
          <strong>INCIDENT COMMAND</strong>
          <span>EXERCISE MODE</span>
        </div>
      </div>
    </header>
  );
}
