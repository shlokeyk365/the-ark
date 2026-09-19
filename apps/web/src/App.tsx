import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  PlanMetrics,
  ScenarioBootstrapResponse,
} from "@the-ark/shared-types";

import { applyEvent, getBootstrap, getFrame } from "./api";
import { eventsActiveAt, formatHours, type FrameSeriesEntry } from "./derive";
import { logEntry, type LogEntry } from "./session";
import { IncidentSidebar } from "./components/IncidentSidebar";
import { RightRail } from "./components/RightRail";
import { ScenarioMap } from "./components/ScenarioMap";
import { StatusBar } from "./components/StatusBar";
import { Timeline } from "./components/Timeline";
import { TopBar } from "./components/TopBar";

const PLAYBACK_INTERVAL_MS = 1600;

interface Comparison {
  worldStateVersion: string;
  metrics: Map<string, PlanMetrics>;
}

/**
 * Load every modeled frame up front, holding the supplied events active
 * wherever they have already taken effect. Scrubbing and playback then read
 * from this set instead of re-querying, so the timeline never shows a frame
 * that disagrees with the event the operator has injected.
 */
async function loadSeries(
  bootstrap: ScenarioBootstrapResponse,
  eventIds: string[],
  signal?: AbortSignal,
): Promise<FrameSeriesEntry[]> {
  return Promise.all(
    bootstrap.available_frames.map(async (frame) => ({
      frameId: frame.frame_id,
      hours: frame.simulation_time_hours,
      state: await getFrame(
        frame.frame_id,
        eventsActiveAt(bootstrap, eventIds, frame.simulation_time_hours),
        signal,
      ),
    })),
  );
}

function LoadingScreen() {
  return (
    <main className="loading-screen" aria-live="polite">
      <div className="loading-mark">ARK</div>
      <div className="loading-copy">
        <strong>Initializing Nakkhu River world state</strong>
        <span>Loading assets, context, routes, and counterfactual plans…</span>
      </div>
      <div className="loading-bar">
        <i />
      </div>
    </main>
  );
}

export function App() {
  const [bootstrap, setBootstrap] = useState<ScenarioBootstrapResponse | null>(null);
  const [series, setSeries] = useState<FrameSeriesEntry[]>([]);
  const [selectedFrameId, setSelectedFrameId] = useState<string | null>(null);
  const [activeEventIds, setActiveEventIds] = useState<string[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState("ktp-plan-a");
  const [comparison, setComparison] = useState<Comparison | undefined>();
  const [log, setLog] = useState<LogEntry[]>([]);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);

  const pushLog = useCallback((entry: LogEntry) => {
    setLog((current) => [entry, ...current].slice(0, 40));
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    (async () => {
      try {
        const loaded = await getBootstrap(controller.signal);
        const entries = await loadSeries(loaded, [], controller.signal);
        if (controller.signal.aborted) return;
        setBootstrap(loaded);
        setSeries(entries);
        setSelectedFrameId(loaded.initial_frame_id);
        pushLog(
          logEntry(
            "load",
            "Baseline world state loaded",
            `${entries.length} modeled frames over a ${loaded.evaluation_horizon_hours}h horizon`,
            loaded.initial_world_state_version,
          ),
        );
      } catch (loadError) {
        if (controller.signal.aborted) return;
        setFatal(
          loadError instanceof Error
            ? loadError.message
            : "Unable to initialize the dashboard",
        );
      }
    })();

    return () => controller.abort();
  }, [pushLog]);

  const worldState = useMemo(
    () => series.find((entry) => entry.frameId === selectedFrameId)?.state,
    [series, selectedFrameId],
  );

  // Last frame in the horizon drives the predicted-inundation layer.
  const horizonState = useMemo(
    () => series[series.length - 1]?.state,
    [series],
  );

  const selectedPlan = useMemo(
    () =>
      worldState?.plan_results.find((result) => result.plan_id === selectedPlanId) ??
      worldState?.plan_results[0],
    [worldState, selectedPlanId],
  );

  const selectFrame = useCallback(
    (frameId: string) => {
      const entry = series.find((item) => item.frameId === frameId);
      if (!entry || frameId === selectedFrameId) return;
      setSelectedFrameId(frameId);
      pushLog(
        logEntry(
          "frame",
          `Viewing ${formatHours(entry.hours)}`,
          entry.state.active_event_ids.length
            ? "Injected event is in force at this frame"
            : "Modeled flood frame, no injected event in force",
          entry.state.world_state_version,
        ),
      );
    },
    [pushLog, selectedFrameId, series],
  );

  const onApplyEvent = useCallback(
    async (eventId: string) => {
      if (!bootstrap) return;
      setPlaying(false);
      setBusy(true);
      setError(null);
      try {
        const response = await applyEvent(eventId);
        const entries = await loadSeries(bootstrap, [eventId]);
        const updated = response.updated_world_state;

        setSeries(entries);
        setActiveEventIds([eventId]);
        setSelectedFrameId(updated.frame_id);
        setComparison({
          worldStateVersion: updated.world_state_version,
          metrics: new Map(
            response.stale_plan_results.map((result) => [result.plan_id, result.metrics]),
          ),
        });

        pushLog(
          logEntry(
            "recompute",
            `${response.recomputed_plan_results.length} plans recomputed`,
            `Scored against ${updated.world_state_version}`,
            updated.world_state_version,
          ),
        );
        pushLog(
          logEntry(
            "event",
            response.event.description,
            `Operator-injected · ${response.previous_world_state_version} superseded`,
            updated.world_state_version,
          ),
        );
      } catch (eventError) {
        setError(
          eventError instanceof Error
            ? eventError.message
            : "Unable to apply the selected event",
        );
      } finally {
        setBusy(false);
      }
    },
    [bootstrap, pushLog],
  );

  const onClearEvent = useCallback(async () => {
    if (!bootstrap) return;
    setPlaying(false);
    setBusy(true);
    setError(null);
    try {
      const entries = await loadSeries(bootstrap, []);
      setSeries(entries);
      setActiveEventIds([]);
      setComparison(undefined);
      const restored =
        entries.find((entry) => entry.frameId === selectedFrameId) ?? entries[0];
      setSelectedFrameId(restored.frameId);
      pushLog(
        logEntry(
          "reset",
          "Injected event cleared",
          "Reverted to the modeled baseline for every frame",
          restored.state.world_state_version,
        ),
      );
    } catch (resetError) {
      setError(
        resetError instanceof Error
          ? resetError.message
          : "Unable to clear the injected event",
      );
    } finally {
      setBusy(false);
    }
  }, [bootstrap, pushLog, selectedFrameId]);

  // Frame playback walks the loaded series and stops at the horizon.
  const seriesRef = useRef(series);
  seriesRef.current = series;

  useEffect(() => {
    if (!playing) return undefined;

    const timer = window.setInterval(() => {
      setSelectedFrameId((current) => {
        const entries = seriesRef.current;
        const index = entries.findIndex((entry) => entry.frameId === current);
        if (index < 0 || index >= entries.length - 1) {
          setPlaying(false);
          return current;
        }
        return entries[index + 1].frameId;
      });
    }, PLAYBACK_INTERVAL_MS);

    return () => window.clearInterval(timer);
  }, [playing]);

  const onTogglePlay = useCallback(() => {
    setPlaying((current) => {
      if (current) return false;
      const entries = seriesRef.current;
      const index = entries.findIndex((entry) => entry.frameId === selectedFrameId);
      if (index >= entries.length - 1) setSelectedFrameId(entries[0]?.frameId ?? null);
      return true;
    });
  }, [selectedFrameId]);

  if (fatal) {
    return (
      <div className="app-frame">
        <TopBar />
        <main className="fatal-error" role="alert">
          <strong>Dashboard initialization failed</strong>
          <span>{fatal}</span>
          <span>Start the API on port 8000, then refresh this page.</span>
        </main>
      </div>
    );
  }

  if (!bootstrap || !worldState) {
    return (
      <div className="app-frame">
        <TopBar />
        <LoadingScreen />
      </div>
    );
  }

  const activeComparison =
    comparison && comparison.worldStateVersion === worldState.world_state_version
      ? comparison.metrics
      : undefined;

  return (
    <div className="app-frame">
      <TopBar alertCount={worldState.hazards.length} />

      {error ? (
        <div className="error-banner" role="alert">
          <strong>Request failed</strong>
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      ) : null}

      <main className="dashboard-grid" aria-busy={busy}>
        <IncidentSidebar bootstrap={bootstrap} series={series} worldState={worldState} />

        <section className="map-workspace" aria-label="Operations workspace">
          <ScenarioMap
            bootstrap={bootstrap}
            horizonState={horizonState}
            selectedPlan={selectedPlan}
            worldState={worldState}
          />
          <Timeline
            activeEventIds={activeEventIds}
            bootstrap={bootstrap}
            busy={busy}
            onApplyEvent={onApplyEvent}
            onClearEvent={onClearEvent}
            onSelectFrame={selectFrame}
            onTogglePlay={onTogglePlay}
            playing={playing}
            worldState={worldState}
          />
        </section>

        <RightRail
          bootstrap={bootstrap}
          comparison={activeComparison}
          log={log}
          onSelectPlan={setSelectedPlanId}
          selectedPlanId={selectedPlan?.plan_id ?? selectedPlanId}
          worldState={worldState}
        />
      </main>

      <StatusBar
        healthy={error === null}
        scenarioId={worldState.scenario_id}
        worldStateVersion={worldState.world_state_version}
      />

      {busy ? <div className="busy-indicator" aria-label="Updating world state" /> : null}
    </div>
  );
}
