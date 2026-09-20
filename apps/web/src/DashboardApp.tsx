import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  CopilotAnswer,
  IntelligenceReport,
  MapSummaryResponse,
  PlanMetrics,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import {
  applyEvent,
  deleteIntelligenceReport,
  decideIntelligenceReport,
  getBootstrap,
  getFrame,
  sendCopilotMessage,
  summarizeCurrentMap,
} from "./api";
import { eventsActiveAt, formatHours, type FrameSeriesEntry } from "./derive";
import type { MapSelection } from "./map/selection";
import { logEntry, type LogEntry } from "./session";
import { RightRail } from "./components/RightRail";
import { IncidentCopilot } from "./components/IncidentCopilot";
import { ReportsPage } from "./components/ReportsPage";
import { ScenarioMap } from "./components/ScenarioMap";
import { SelectedAssetPanel } from "./components/SelectedAssetPanel";
import { StatusBar } from "./components/StatusBar";
import { TacticalAssetsPanel } from "./components/TacticalAssetsPanel";
import { Timeline } from "./components/Timeline";
import { TopBar } from "./components/TopBar";
import { TopStatusMetrics } from "./components/TopStatusMetrics";

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
  intelligenceReportIds: string[] = [],
): Promise<FrameSeriesEntry[]> {
  return Promise.all(
    bootstrap.available_frames.map(async (frame) => ({
      frameId: frame.frame_id,
      hours: frame.simulation_time_hours,
      state: await getFrame(
        frame.frame_id,
        eventsActiveAt(bootstrap, eventIds, frame.simulation_time_hours),
        signal,
        intelligenceReportIds,
      ),
    })),
  );
}

function LoadingScreen() {
  return (
    <main className="loading-screen" aria-live="polite">
      <div className="loading-mark">ARK</div>
      <div className="loading-copy">
        <strong>Initializing Kantipur world state</strong>
        <span>Loading assets, context, routes, and counterfactual plans…</span>
      </div>
      <div className="loading-bar">
        <i />
      </div>
    </main>
  );
}

export function App() {
  const [activeView, setActiveView] = useState<"operations" | "reports">("operations");
  const [bootstrap, setBootstrap] = useState<ScenarioBootstrapResponse | null>(null);
  const [series, setSeries] = useState<FrameSeriesEntry[]>([]);
  const [selectedFrameId, setSelectedFrameId] = useState<string | null>(null);
  const [activeEventIds, setActiveEventIds] = useState<string[]>([]);
  const [intelligenceReports, setIntelligenceReports] = useState<
    IntelligenceReport[]
  >([]);
  const [confirmedIntelligenceIds, setConfirmedIntelligenceIds] = useState<
    string[]
  >([]);
  const [tentativeWorldState, setTentativeWorldState] =
    useState<WorldStateSnapshot | null>(null);
  const [mapSummary, setMapSummary] = useState<MapSummaryResponse | null>(null);
  const [copilotAnswers, setCopilotAnswers] = useState<CopilotAnswer[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState("ktp-plan-a");
  /*
   * One selection for the whole dashboard.
   *
   * The map, the tactical list and the asset panel all used to track what was
   * selected separately, which meant clicking a community on the map left the
   * panel showing something else. `MapSelection` is now the single source of
   * truth; `selectedAssetId` below is a view of it for the components that only
   * care about assets.
   */
  const [selection, setSelection] = useState<MapSelection | null>(null);
  const selectedAssetId = useMemo(
    () => (selection?.kind === "asset" ? selection.id : null),
    [selection],
  );
  const selectAsset = useCallback(
    (assetId: string | null) =>
      setSelection(assetId ? { kind: "asset", id: assetId } : null),
    [],
  );
  const [comparison, setComparison] = useState<Comparison | undefined>();
  const [log, setLog] = useState<LogEntry[]>([]);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [focusedDestination, setFocusedDestination] = useState<{
    id: string;
    edgeIds: string[];
  } | null>(null);

  const pushLog = useCallback((entry: LogEntry) => {
    setLog((current) => [entry, ...current].slice(0, 40));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void import("./map/MapLibreScenarioMap");

    (async () => {
      try {
        const loaded = await getBootstrap(controller.signal);
        const frameLoads = loaded.available_frames.map(async (frame) => ({
          frameId: frame.frame_id,
          hours: frame.simulation_time_hours,
          state: await getFrame(
            frame.frame_id,
            eventsActiveAt(loaded, [], frame.simulation_time_hours),
            controller.signal,
          ),
        }));
        const initialIndex = Math.max(
          0,
          loaded.available_frames.findIndex(
            (frame) => frame.frame_id === loaded.initial_frame_id,
          ),
        );
        const first = await frameLoads[initialIndex];
        if (controller.signal.aborted) return;
        setBootstrap(loaded);
        setSeries([first]);
        setSelectedFrameId(first.frameId);
        setSelection((current) => {
          if (current) return current;
          const eventEdgeId = loaded.events[0]?.changes[0]?.edge_id;
          const assetId = loaded.assets.features.find(
            (feature) =>
              feature.id === eventEdgeId || feature.properties.edge_id === eventEdgeId,
          )?.id;
          return assetId ? { kind: "asset", id: assetId } : null;
        });
        pushLog(
          logEntry(
            "load",
            "Baseline world state loaded",
            `Frame ${first.frameId} ready; remaining modeled frames loading`,
            first.state.world_state_version,
          ),
        );
        const entries = await Promise.all(frameLoads);
        if (controller.signal.aborted) return;
        setSeries(entries);
        pushLog(
          logEntry(
            "load",
            "Horizon frames ready",
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

  useEffect(() => {
    setMapSummary((current) =>
      current?.source_world_state_version === worldState?.world_state_version
        ? current
        : null,
    );
  }, [worldState?.world_state_version]);

  const seriesComplete = Boolean(
    bootstrap && series.length === bootstrap.available_frames.length,
  );

  // Last *loaded* horizon frame drives the predicted-inundation layer.
  const horizonState = useMemo(() => {
    if (!bootstrap) return undefined;
    const horizonId = bootstrap.available_frames.at(-1)?.frame_id;
    return series.find((entry) => entry.frameId === horizonId)?.state;
  }, [bootstrap, series]);

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
        const entries = await loadSeries(
          bootstrap,
          [eventId],
          undefined,
          confirmedIntelligenceIds,
        );
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
    [bootstrap, confirmedIntelligenceIds, pushLog],
  );

  const onClearEvent = useCallback(async () => {
    if (!bootstrap) return;
    setPlaying(false);
    setBusy(true);
    setError(null);
    try {
      const entries = await loadSeries(
        bootstrap,
        [],
        undefined,
        confirmedIntelligenceIds,
      );
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
  }, [bootstrap, confirmedIntelligenceIds, pushLog, selectedFrameId]);

  const onSubmitIntelligence = useCallback(
    async (message: string) => {
      if (!worldState) return;
      setBusy(true);
      setError(null);
      try {
        const response = await sendCopilotMessage(
          message,
          worldState.frame_id,
          activeEventIds,
          confirmedIntelligenceIds,
        );
        if (response.mode !== "deterministic_update") {
          setCopilotAnswers((current) => [
            response.answer,
            ...current.filter(
              (answer) => answer.answer_id !== response.answer.answer_id,
            ),
          ]);
          pushLog(
            logEntry(
              "intelligence",
              response.mode === "claude_answer"
                ? "Claude answered from grounded context"
                : "Deterministic map lookup answered",
              response.answer.message,
              response.answer.source_world_state_version,
            ),
          );
          return;
        }
        setIntelligenceReports((current) => [
          response.report,
          ...current.filter(
            (report) => report.report_id !== response.report.report_id,
          ),
        ]);
        setMapSummary(null);
        setTentativeWorldState(response.tentative_world_state);
        pushLog(
          logEntry(
            "intelligence",
            `${response.report.status} field report received`,
            response.report.claim.summary,
            worldState.world_state_version,
          ),
        );
      } catch (intelligenceError) {
        setError(
          intelligenceError instanceof Error
            ? intelligenceError.message
            : "Unable to analyze field intelligence",
        );
      } finally {
        setBusy(false);
      }
    },
    [activeEventIds, confirmedIntelligenceIds, pushLog, worldState],
  );

  const onSummarizeMap = useCallback(async () => {
    if (!worldState) return;
    setBusy(true);
    setError(null);
    try {
      const summary = await summarizeCurrentMap(
        worldState.frame_id,
        activeEventIds,
        confirmedIntelligenceIds,
      );
      setMapSummary(summary);
      pushLog(
        logEntry(
          "intelligence",
          "Current map summarized",
          summary.headline,
          summary.source_world_state_version,
        ),
      );
    } catch (summaryError) {
      setError(
        summaryError instanceof Error
          ? summaryError.message
          : "Unable to summarize the current map",
      );
    } finally {
      setBusy(false);
    }
  }, [activeEventIds, confirmedIntelligenceIds, pushLog, worldState]);

  const onDeleteIntelligence = useCallback(
    async (reportId: string) => {
      if (!bootstrap || !worldState) return;
      const report = intelligenceReports.find(
        (candidate) => candidate.report_id === reportId,
      );
      setBusy(true);
      setError(null);
      try {
        const deleted = await deleteIntelligenceReport(reportId);
        const wasConfirmed = confirmedIntelligenceIds.includes(reportId);
        const nextIds = confirmedIntelligenceIds.filter((id) => id !== reportId);

        setIntelligenceReports((current) =>
          current.filter((candidate) => candidate.report_id !== reportId),
        );
        setMapSummary(null);
        setConfirmedIntelligenceIds(nextIds);
        setTentativeWorldState(null);

        let stateVersion = worldState.world_state_version;
        if (wasConfirmed) {
          const entries = await loadSeries(
            bootstrap,
            activeEventIds,
            undefined,
            nextIds,
          );
          setSeries(entries);
          const updated =
            entries.find((entry) => entry.frameId === worldState.frame_id) ??
            entries[0];
          stateVersion = updated.state.world_state_version;
        }

        pushLog(
          logEntry(
            "intelligence",
            "Field report deleted",
            report?.claim.summary ?? deleted.claim.summary,
            stateVersion,
          ),
        );
      } catch (deleteError) {
        setError(
          deleteError instanceof Error
            ? deleteError.message
            : "Unable to delete field report",
        );
      } finally {
        setBusy(false);
      }
    },
    [
      activeEventIds,
      bootstrap,
      confirmedIntelligenceIds,
      intelligenceReports,
      pushLog,
      worldState,
    ],
  );

  const onIntelligenceDecision = useCallback(
    async (
      reportId: string,
      decision: "confirm" | "keep_tentative" | "reject",
    ) => {
      if (!bootstrap || !worldState) return;
      setBusy(true);
      setError(null);
      try {
        const response = await decideIntelligenceReport(
          reportId,
          decision,
          worldState.frame_id,
          activeEventIds,
          confirmedIntelligenceIds,
        );
        setIntelligenceReports((current) =>
          current.map((report) =>
            report.report_id === reportId ? response.report : report,
          ),
        );
        setMapSummary(null);
        if (decision === "confirm") {
          const nextIds = Array.from(
            new Set([...confirmedIntelligenceIds, reportId]),
          );
          const entries = await loadSeries(
            bootstrap,
            activeEventIds,
            undefined,
            nextIds,
          );
          setConfirmedIntelligenceIds(nextIds);
          setSeries(entries);
          setTentativeWorldState(null);
          pushLog(
            logEntry(
              "intelligence",
              "Field report confirmed",
              response.report.claim.summary,
              response.updated_world_state.world_state_version,
            ),
          );
        } else if (decision === "reject") {
          setTentativeWorldState(null);
        }
      } catch (decisionError) {
        setError(
          decisionError instanceof Error
            ? decisionError.message
            : "Unable to apply intelligence decision",
        );
      } finally {
        setBusy(false);
      }
    },
    [
      activeEventIds,
      bootstrap,
      confirmedIntelligenceIds,
      pushLog,
      worldState,
    ],
  );

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
  const mapWorldState =
    tentativeWorldState?.frame_id === worldState.frame_id
      ? tentativeWorldState
      : worldState;

  return (
    <div className="app-frame">
      <TopBar
        activeView={activeView}
        alertCount={worldState.hazards.length}
        onNavigate={setActiveView}
        worldState={worldState}
      />

      {error ? (
        <div className="error-banner" role="alert">
          <strong>Request failed</strong>
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      ) : null}

      {activeView === "reports" ? (
        <ReportsPage activeEventIds={activeEventIds} scenarioName={bootstrap.name} />
      ) : <main className="dashboard-grid figma-operations-layout" aria-busy={busy}>
        <section className="map-workspace" aria-label="Operations workspace">
          <ScenarioMap
            bootstrap={bootstrap}
            focusedRouteEdgeIds={focusedDestination?.edgeIds}
            onSelect={setSelection}
            selection={selection}
            horizonState={horizonState}
            selectedPlan={selectedPlan}
            worldState={mapWorldState}
          />
          <TopStatusMetrics worldState={worldState} />
          <TacticalAssetsPanel
            bootstrap={bootstrap}
            onSelectAsset={selectAsset}
            selectedAssetId={selectedAssetId}
            selectedPlan={selectedPlan}
            worldState={worldState}
          />
          <div className="operations-right-stack">
            <IncidentCopilot
              answers={copilotAnswers}
              baseline={worldState}
              busy={busy}
              onDelete={onDeleteIntelligence}
              onDecision={onIntelligenceDecision}
              onDismissSummary={() => setMapSummary(null)}
              onDeleteAnswer={(answerId) =>
                setCopilotAnswers((current) =>
                  current.filter((answer) => answer.answer_id !== answerId),
                )
              }
              onSubmit={onSubmitIntelligence}
              onSummarize={onSummarizeMap}
              reports={intelligenceReports}
              summary={mapSummary}
              tentative={tentativeWorldState}
            />
            <SelectedAssetPanel
              activeEventIds={activeEventIds}
              bootstrap={bootstrap}
              busy={busy}
              onApplyEvent={onApplyEvent}
              selectedAssetId={selectedAssetId}
              worldState={worldState}
            />
            <RightRail
              bootstrap={bootstrap}
              comparison={activeComparison}
              focusedDestinationId={focusedDestination?.id ?? null}
              log={log}
              onSelect={setSelection}
              selection={selection}
              onFocusDestination={(id, edgeIds) =>
                setFocusedDestination(id ? { id, edgeIds } : null)
              }
              onSelectPlan={(planId) => {
                setFocusedDestination(null);
                setSelectedPlanId(planId);
              }}
              selectedPlanId={selectedPlan?.plan_id ?? selectedPlanId}
              worldState={worldState}
            />
          </div>
          <Timeline
            activeEventIds={activeEventIds}
            bootstrap={bootstrap}
            busy={busy}
            loadedFrameIds={series.map((entry) => entry.frameId)}
            onApplyEvent={onApplyEvent}
            onClearEvent={onClearEvent}
            onSelectFrame={selectFrame}
            onTogglePlay={onTogglePlay}
            playing={playing}
            seriesComplete={seriesComplete}
            worldState={worldState}
          />
        </section>
      </main>}

      <StatusBar
        healthy={error === null}
        scenarioId={worldState.scenario_id}
        worldStateVersion={worldState.world_state_version}
      />

      {busy ? <div className="busy-indicator" aria-label="Updating world state" /> : null}
    </div>
  );
}
