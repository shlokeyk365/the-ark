import { Suspense, lazy, useCallback, useState } from "react";

import type {
  PlanResult,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import type { MapSelection } from "../map/selection";
import { SchematicMap } from "./SchematicMap";
import { ShellIcon } from "./ShellIcon";

// MapLibre plus the basemap style is ~1.5 MB, so it loads after the shell.
const MapLibreScenarioMap = lazy(() =>
  import("../map/MapLibreScenarioMap").then((module) => ({
    default: module.MapLibreScenarioMap,
  })),
);

interface ScenarioMapProps {
  bootstrap: ScenarioBootstrapResponse;
  worldState: WorldStateSnapshot;
  horizonState: WorldStateSnapshot | undefined;
  selectedPlan: PlanResult | undefined;
  focusedRouteEdgeIds?: string[];
  /* Incident focus, shared with the rails and the asset panel. */
  selection: MapSelection | null;
  onSelect: (selection: MapSelection | null) => void;
  /** Landing embed: same derived map, without stealing page scroll. */
  embedded?: boolean;
}

function BasemapLoading() {
  return (
    <section className="map-card" aria-label="Loading basemap">
      <div className="map-booting" role="status">
        <span className="map-booting-spinner" />
        Loading basemap…
      </div>
    </section>
  );
}

/**
 * Chooses the basemap renderer.
 *
 * MapLibre needs no key, but it does need the PMTiles archive to be reachable.
 * If the archive is missing the dashboard degrades to the schematic renderer
 * rather than showing a dead panel, so the scenario stays inspectable.
 */
export function ScenarioMap({
  bootstrap,
  worldState,
  horizonState,
  selectedPlan,
  focusedRouteEdgeIds,
  selection,
  onSelect,
  embedded = false,
}: ScenarioMapProps) {
  const [failure, setFailure] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);

  const onFailure = useCallback((reason: string) => {
    setFailure((current) => current ?? reason);
  }, []);

  // Only point at the archive when the archive is plausibly the problem.
  const archiveLikely = failure !== null && /pmtiles|archive|404|fetch|network/i.test(failure);

  if (failure) {
    return (
      <div className="map-fallback-wrap">
        <SchematicMap
          bootstrap={bootstrap}
          focusedRouteEdgeIds={focusedRouteEdgeIds}
          horizonState={horizonState}
          selectedPlan={selectedPlan}
          worldState={worldState}
        />
        {!dismissed ? (
          <div className="basemap-notice" role="status">
            <ShellIcon name="layers" size={14} />
            <div>
              <strong>Basemap unavailable — showing schematic</strong>
              <span>
                {failure}
                {archiveLikely ? (
                  <>
                    {" · Run "}
                    <code>npm run basemap</code>
                    {" to fetch the Nakkhu scenario PMTiles archive."}
                  </>
                ) : null}
              </span>
            </div>
            <button type="button" onClick={() => setDismissed(true)} aria-label="Dismiss">
              <ShellIcon name="x" size={13} />
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <Suspense fallback={<BasemapLoading />}>
      <MapLibreScenarioMap
        bootstrap={bootstrap}
        embedded={embedded}
        focusedRouteEdgeIds={focusedRouteEdgeIds}
        horizonState={horizonState}
        onFailure={onFailure}
        onSelect={onSelect}
        selectedPlan={selectedPlan}
        selection={selection}
        worldState={worldState}
      />
    </Suspense>
  );
}
