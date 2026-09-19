import { ShellIcon } from "./ShellIcon";
import type { WorldStateSnapshot } from "@the-ark/shared-types";

interface TopBarProps {
  alertCount?: number;
  worldState?: WorldStateSnapshot;
}

export function TopBar({ alertCount = 0, worldState }: TopBarProps) {
  return (
    <header className="topbar">
      <div className="brand" aria-label="the ark flood operations">
        <span className="brand-mark">
          <ShellIcon name="waves" size={22} />
        </span>
        <span className="brand-name">ARK</span>
        <span className="brand-divider">/</span>
        <span className="brand-context">FLOODWORLD</span>
      </div>

      <div className="command-centre-title">
        <span>Operational simulation</span>
        <strong>Kantipur River Command Center</strong>
      </div>

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
