import { useEffect, useMemo, useState } from "react";

import type {
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { getBootstrap, getFrame } from "../api";
import type { MapSelection } from "../map/selection";
import { ScenarioMap } from "./ScenarioMap";

/**
 * Marketing embed of the same derived Kantipur map the command center uses.
 * Loads the baseline and horizon frames only — no plan evaluation happens here.
 */
export function LandingScenarioMap() {
  const [bootstrap, setBootstrap] = useState<ScenarioBootstrapResponse | null>(null);
  const [worldState, setWorldState] = useState<WorldStateSnapshot | null>(null);
  const [horizonState, setHorizonState] = useState<WorldStateSnapshot | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [selection, setSelection] = useState<MapSelection | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    (async () => {
      try {
        const loaded = await getBootstrap(controller.signal);
        const lastFrame = loaded.available_frames.at(-1);
        const [now, horizon] = await Promise.all([
          getFrame(loaded.initial_frame_id, [], controller.signal),
          lastFrame
            ? getFrame(lastFrame.frame_id, [], controller.signal)
            : Promise.resolve(undefined),
        ]);
        if (controller.signal.aborted) return;
        setBootstrap(loaded);
        setWorldState(now);
        setHorizonState(horizon);
      } catch (loadError) {
        if (controller.signal.aborted) return;
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Unable to load the scenario map",
        );
      }
    })();

    return () => controller.abort();
  }, []);

  const selectedPlan = useMemo(
    () => worldState?.plan_results[0],
    [worldState],
  );

  if (error) {
    return (
      <div className="landing-map-status" role="status">
        <strong>Scenario map unavailable</strong>
        <span>{error}</span>
      </div>
    );
  }

  if (!bootstrap || !worldState) {
    return (
      <div className="landing-map-status" role="status">
        <span className="map-booting-spinner" />
        Loading Kantipur scenario map…
      </div>
    );
  }

  return (
    <ScenarioMap
      bootstrap={bootstrap}
      embedded
      horizonState={horizonState}
      onSelect={setSelection}
      selectedPlan={selectedPlan}
      selection={selection}
      worldState={worldState}
    />
  );
}
