import type {
  EventRecomputeResponse,
  ScenarioBootstrapResponse,
  SimulationReport,
  SimulationRun,
  SimulationRunSummary,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

/**
 * Keep the UI usable while a previously started API process is still serving
 * the pre-prediction payload. Missing additive fields represent unavailable
 * data; they must not become fabricated model output or crash the dashboard.
 */
function normalizeWorldState(state: WorldStateSnapshot): WorldStateSnapshot {
  return {
    ...state,
    prediction_signals: Array.isArray(state.prediction_signals)
      ? state.prediction_signals
      : [],
  };
}

function normalizeBootstrap(
  bootstrap: ScenarioBootstrapResponse,
): ScenarioBootstrapResponse {
  return {
    ...bootstrap,
    flood_polygons: bootstrap.flood_polygons ?? {
      type: "FeatureCollection",
      name: "Unavailable flood polygon surface",
      scenario_id: bootstrap.scenario_id,
      data_classification: "modeled_synthetic_demo",
      operational_use: false,
      source: {
        source_type: "modeled_input",
        description: "UNAVAILABLE — API process does not provide flood polygons",
      },
      features: [],
    },
  };
}

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

export async function getBootstrap(signal?: AbortSignal) {
  const bootstrap = await fetchJson<ScenarioBootstrapResponse>(
    "/scenarios/kantipur-river/bootstrap",
    { signal },
  );
  return normalizeBootstrap(bootstrap);
}

export async function getBaseline(signal?: AbortSignal) {
  const state = await fetchJson<WorldStateSnapshot>(
    "/scenarios/kantipur-river/baseline",
    { signal },
  );
  return normalizeWorldState(state);
}

/**
 * Fetch one frame, optionally holding a set of injected events active. Events
 * that are not yet effective at the frame are rejected by the API, so callers
 * must filter them first.
 */
export async function getFrame(frameId: string, eventIds: string[] = [], signal?: AbortSignal) {
  const query = new URLSearchParams();
  eventIds.forEach((eventId) => query.append("events", eventId));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const state = await fetchJson<WorldStateSnapshot>(
    `/scenarios/kantipur-river/frames/${encodeURIComponent(frameId)}${suffix}`,
    { signal },
  );
  return normalizeWorldState(state);
}

export async function applyEvent(eventId: string, signal?: AbortSignal) {
  const response = await fetchJson<EventRecomputeResponse>(
    `/scenarios/kantipur-river/events/${encodeURIComponent(eventId)}`,
    { method: "POST", signal },
  );
  return {
    ...response,
    updated_world_state: normalizeWorldState(response.updated_world_state),
  };
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
