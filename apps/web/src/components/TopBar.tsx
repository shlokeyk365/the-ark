import { ShellIcon } from "./ShellIcon";

interface TopBarProps {
  alertCount?: number;
  activeView?: "operations" | "reports";
  onNavigate?: (view: "operations" | "reports") => void;
}

export function TopBar({
  alertCount = 0,
  activeView = "operations",
  onNavigate,
}: TopBarProps) {
  return (
    <header className="topbar">
      <div className="brand" aria-label="the ark flood operations">
        <span className="brand-mark">
          <ShellIcon name="waves" size={26} />
        </span>
        <span className="brand-name">the ark</span>
        <span className="brand-path" aria-hidden="true">
          <span>MODEL</span>
          <ShellIcon name="chevron" size={10} />
          <span>ANTICIPATE</span>
          <ShellIcon name="chevron" size={10} />
          <span>PROTECT</span>
        </span>
      </div>

      <nav className="primary-nav" aria-label="Primary navigation">
        <button
          className={`nav-item ${activeView === "operations" ? "active" : ""}`}
          type="button"
          aria-current={activeView === "operations" ? "page" : undefined}
          onClick={() => onNavigate?.("operations")}
        >
          <ShellIcon name="map" size={15} /> Operations
        </button>
        <button className="nav-item" type="button" disabled title="Not part of the MVP slice">
          <ShellIcon name="layers" size={15} /> Scenarios
        </button>
        <button
          className={`nav-item ${activeView === "reports" ? "active" : ""}`}
          type="button"
          aria-current={activeView === "reports" ? "page" : undefined}
          onClick={() => onNavigate?.("reports")}
        >
          <ShellIcon name="report" size={15} /> Reports
        </button>
      </nav>

      <div className="command-tools">
        <label className="search-control">
          <span className="sr-only">Search scenario assets</span>
          <ShellIcon name="search" size={14} />
          <input placeholder="Search assets or communities…" disabled />
        </label>
        <button className="icon-button" type="button" aria-label={`${alertCount} active alerts`}>
          <ShellIcon name="bell" size={17} />
          {alertCount > 0 ? <span className="notification-dot" /> : null}
        </button>
        <div className="command-avatar" aria-hidden="true">
          IC
        </div>
        <div className="command-title">
          <strong>Incident Command</strong>
          <span>NAKKHU · LALITPUR</span>
        </div>
      </div>
    </header>
  );
}
