import type {
  EventRecomputeResponse,
  ScenarioBootstrapResponse,
  SimulationReport,
  SimulationRun,
  SimulationRunSummary,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

async function fetchJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body);
    } catch {
      detail = await response.text().catch(() => "");
    }
    throw new Error(
      `API request failed (${response.status}): ${detail || response.statusText}`,
    );
  }

  return (await response.json()) as T;
}

export function getBootstrap(signal?: AbortSignal) {
  return fetchJson<ScenarioBootstrapResponse>(
    "/scenarios/kantipur-river/bootstrap",
    { signal },
  );
}

export function getBaseline(signal?: AbortSignal) {
  return fetchJson<WorldStateSnapshot>("/scenarios/kantipur-river/baseline", { signal });
}

/**
 * Fetch one frame, optionally holding a set of injected events active. Events
 * that are not yet effective at the frame are rejected by the API, so callers
 * must filter them first.
 */
export function getFrame(frameId: string, eventIds: string[] = [], signal?: AbortSignal) {
  const query = new URLSearchParams();
  eventIds.forEach((eventId) => query.append("events", eventId));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return fetchJson<WorldStateSnapshot>(
    `/scenarios/kantipur-river/frames/${encodeURIComponent(frameId)}${suffix}`,
    { signal },
  );
}

export function applyEvent(eventId: string, signal?: AbortSignal) {
  return fetchJson<EventRecomputeResponse>(
    `/scenarios/kantipur-river/events/${encodeURIComponent(eventId)}`,
    { method: "POST", signal },
  );
}

export function createSimulationRun(eventIds: string[] = [], signal?: AbortSignal) {
  return fetchJson<SimulationRun>("/scenarios/kantipur-river/runs", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_ids: eventIds }),
  });
}

export function listSimulationRuns(signal?: AbortSignal) {
  return fetchJson<SimulationRunSummary[]>("/scenarios/kantipur-river/runs", {
    signal,
  });
}

export function getSimulationReport(reportId: string, signal?: AbortSignal) {
  return fetchJson<SimulationReport>(
    `/reports/${encodeURIComponent(reportId)}`,
    { signal },
  );
}

export function reportExportUrl(reportId: string, format: "json" | "csv" | "html") {
  return `${API_BASE_URL}/reports/${encodeURIComponent(reportId)}/export?format=${format}`;
}
