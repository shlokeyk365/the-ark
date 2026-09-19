import { useEffect, useState } from "react";

interface StatusBarProps {
  scenarioId: string;
  worldStateVersion: string;
  healthy: boolean;
}

function utcStamp(now: Date) {
  const iso = now.toISOString();
  return `UTC ${iso.slice(0, 10)} ${iso.slice(11, 16)}`;
}

export function StatusBar({ scenarioId, worldStateVersion, healthy }: StatusBarProps) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <footer className="status-bar">
      <span className="status-brand">the ark</span>
      <span>v0.1.0</span>
      <span className="status-wide">Deterministic flood-response world model</span>
      <span className="status-mono">{scenarioId}</span>
      <span className="status-mono status-wide">{worldStateVersion}</span>
      <span className={`system-status ${healthy ? "" : "degraded"}`}>
        <i />
        {healthy ? "World state current" : "Recompute required"}
      </span>
      <span className="status-mono">{utcStamp(now)}</span>
    </footer>
  );
}
