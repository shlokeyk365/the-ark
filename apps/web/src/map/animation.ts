import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";

import {
  EMPTY,
  pointAlong,
  routePaths,
  type MapFeature,
  type MapFeatureCollection,
  type RoutePath,
} from "./scenarioSources";
import { SOURCE } from "./layers";

/**
 * The map's only animation loop.
 *
 * Two things on this map move, and both of them move because something in the
 * world state changed — not to make the interface feel alive:
 *
 * - **Response teams** travel along the active plan's routes, so an operator
 *   can see at a glance which corridors are carrying an evacuation.
 * - **A newly escalated critical hazard** pulses briefly, then stops. One at a
 *   time, for a fixed few seconds, and never again for the same asset.
 *
 * Both share a single `requestAnimationFrame` driver that parks itself the
 * moment there is nothing left to animate, and neither runs at all when the
 * viewer has asked for reduced motion.
 */

/** Seconds for a team marker to traverse a route once. */
const TRAVERSAL_SECONDS = 15;
/** How long a newly escalated hazard is allowed to pulse. */
const PULSE_DURATION_MS = 5200;
const PULSE_PERIOD_MS = 1300;

const PULSE_LAYER = "hazard-escalation-pulse";

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function teamFeature(
  path: RoutePath,
  t: number,
  labelled: boolean,
): MapFeature {
  const { position, bearing } = pointAlong(path, t);
  return {
    type: "Feature",
    id: `team-${path.id}`,
    geometry: { type: "Point", coordinates: position },
    properties: {
      id: path.id,
      community_id: path.communityId,
      shelter_id: path.shelterId,
      bearing,
      // Destination and ETA are detail for one route, not a caption on all of
      // them, so the text is only supplied while that route is focused.
      label: labelled ? path.label : "",
    },
  };
}

export interface MapAnimator {
  /** Active-plan routes the teams travel; pass `EMPTY` to clear them. */
  setRoutes: (routes: MapFeatureCollection) => void;
  /** Community ids whose route should show its destination and ETA. */
  setFocusedCommunities: (communityIds: Set<string> | null) => void;
  /** Start a bounded pulse on one hazard, or `null` to stop it immediately. */
  pulseHazard: (hazardId: string | null) => void;
  /** Motion state for the map diagnostics panel. */
  describe: () => string;
  destroy: () => void;
}

/**
 * Attach the animation loop to a map.
 *
 * The returned handle is the only way to drive it, and `destroy` must be called
 * when the map goes away — a stray frame callback would otherwise keep calling
 * into a removed map.
 */
export function createMapAnimator(map: MapLibreMap): MapAnimator {
  const reducedMotion = prefersReducedMotion();

  let paths: RoutePath[] = [];
  let focused: Set<string> | null = null;
  let pulseId: string | null = null;
  let pulseStartedAt = 0;
  let frame: number | null = null;
  let disposed = false;

  const setTeamData = (collection: MapFeatureCollection) => {
    const source = map.getSource(SOURCE.teams);
    if (source && "setData" in source) {
      (source as GeoJSONSource).setData(
        collection as unknown as GeoJSON.FeatureCollection,
      );
    }
  };

  const renderTeams = (elapsedSeconds: number) => {
    if (paths.length === 0) {
      setTeamData(EMPTY);
      return;
    }

    setTeamData({
      type: "FeatureCollection",
      features: paths.map((path, index) => {
        // Reduced motion still places the unit, it just does not move it.
        // Otherwise stagger the routes so they do not travel in lockstep.
        const t = reducedMotion
          ? 0.5
          : ((elapsedSeconds / TRAVERSAL_SECONDS + index / paths.length) % 1);
        return teamFeature(path, t, focused?.has(path.communityId) ?? false);
      }),
    });
  };

  const clearPulse = () => {
    pulseId = null;
    if (!map.getLayer(PULSE_LAYER)) return;
    map.setFilter(PULSE_LAYER, ["==", ["get", "hazard_id"], "__none__"]);
    map.setPaintProperty(PULSE_LAYER, "circle-opacity", 0);
    map.setPaintProperty(PULSE_LAYER, "circle-stroke-opacity", 0);
  };

  const renderPulse = (now: number): boolean => {
    if (!pulseId || !map.getLayer(PULSE_LAYER)) return false;

    const elapsed = now - pulseStartedAt;
    if (elapsed >= PULSE_DURATION_MS) {
      clearPulse();
      return false;
    }

    // One expanding ring per period, fading as it grows, and the whole effect
    // fades out over its lifetime so it ends rather than being cut off.
    const phase = (elapsed % PULSE_PERIOD_MS) / PULSE_PERIOD_MS;
    const remaining = 1 - elapsed / PULSE_DURATION_MS;
    map.setPaintProperty(PULSE_LAYER, "circle-radius", 11 + phase * 24);
    map.setPaintProperty(
      PULSE_LAYER,
      "circle-stroke-opacity",
      (1 - phase) * 0.75 * remaining,
    );
    map.setPaintProperty(PULSE_LAYER, "circle-opacity", (1 - phase) * 0.14 * remaining);
    return true;
  };

  const startedAt = performance.now();

  const tick = () => {
    frame = null;
    if (disposed) return;

    const now = performance.now();
    const teamsMoving = paths.length > 0 && !reducedMotion;

    if (teamsMoving) renderTeams((now - startedAt) / 1000);
    const pulsing = renderPulse(now);

    if (teamsMoving || pulsing) frame = requestAnimationFrame(tick);
  };

  const wake = () => {
    if (disposed || frame !== null) return;
    frame = requestAnimationFrame(tick);
  };

  return {
    setRoutes(routes) {
      paths = routePaths(routes);
      // Draw once immediately so a route change shows up even while parked.
      renderTeams((performance.now() - startedAt) / 1000);
      wake();
    },

    setFocusedCommunities(communityIds) {
      focused = communityIds;
      renderTeams((performance.now() - startedAt) / 1000);
    },

    pulseHazard(hazardId) {
      if (hazardId === null || reducedMotion) {
        clearPulse();
        return;
      }
      if (!map.getLayer(PULSE_LAYER)) return;

      pulseId = hazardId;
      pulseStartedAt = performance.now();
      map.setFilter(PULSE_LAYER, ["==", ["get", "hazard_id"], hazardId]);
      wake();
    },

    describe() {
      const motion = reducedMotion ? "reduced-motion (teams parked)" : "animating";
      const running = frame !== null ? "frame loop running" : "frame loop parked";
      return `teams: ${paths.length} · ${motion} · ${running} · pulse: ${pulseId ?? "idle"}`;
    },

    destroy() {
      disposed = true;
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
    },
  };
}
