/** Client-side audit trail of what the operator did and what it changed. */
export type LogKind = "frame" | "event" | "recompute" | "reset" | "load";

export interface LogEntry {
  id: string;
  kind: LogKind;
  title: string;
  detail: string;
  worldStateVersion: string;
  at: Date;
}

let sequence = 0;

export function logEntry(
  kind: LogKind,
  title: string,
  detail: string,
  worldStateVersion: string,
): LogEntry {
  sequence += 1;
  return {
    id: `log-${sequence}`,
    kind,
    title,
    detail,
    worldStateVersion,
    at: new Date(),
  };
}

export function relativeTime(from: Date, now: Date): string {
  const seconds = Math.max(0, Math.round((now.getTime() - from.getTime()) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.round(minutes / 60)}h ago`;
}
