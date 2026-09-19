import { useCallback, useEffect, useMemo, useRef, useState } from "react";
// MapLibre v6 has no default export.
import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
import { Protocol } from "pmtiles";
import { DARK, layers as protomapsLayers } from "@protomaps/basemaps";

import "maplibre-gl/dist/maplibre-gl.css";

import type {
  PlanResult,
  Position,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { ShellIcon } from "../components/ShellIcon";
import {
  BASEMAP_GLYPHS,
  BASEMAP_LANG,
  BASEMAP_PMTILES,
  BASEMAP_SOURCE_ID,
  BASEMAP_SPRITE,
  OSM_ATTRIBUTION,
  PROTOMAPS_ATTRIBUTION,
  SATELLITE_ATTRIBUTION,
  SATELLITE_LAYER_ID,
  SATELLITE_SOURCE_ID,
  SATELLITE_TILES,
  TERRAIN_ATTRIBUTION,
  TERRAIN_SOURCE_ID,
  TERRAIN_TILES,
  pmtilesUrl,
} from "./basemap";
import { createMapAnimator, type MapAnimator } from "./animation";
import { tuneBasemapLayers } from "./basemapTuning";
import {
  ASSET_LAYERS,
  CURRENT_FLOOD_OPACITY,
  DEFAULT_OFF,
  EDGE_LAYERS,
  EDGE_SYMBOL_LAYERS,
  FLOOD_LAYERS,
  FORECAST_FLOOD_OPACITY,
  HAZARD_LAYERS,
  LAYERS,
  LAYER_CONTROLS,
  PICKABLE_LAYERS,
  SOURCE,
  type LayerKey,
} from "./layers";
import { registerMarkerImages } from "./markerImages";
import { buildFocus, type MapSelection } from "./selection";
import {
  alternateRouteCollection,
  assetsCollection,
  boundsFor,
  bridgeLinesCollection,
  bridgesCollection,
  channelCollection,
  contextCollection,
  EMPTY,
  edgeLabel,
  floodForecastCollection,
  floodNowCollection,
  hazardsCollection,
  nodeLabels,
  roadHazardsCollection,
  roadsCollection,
  routeCollection,
  routeEdgeIdsFor,
  scenarioBounds,
  type MapFeatureCollection,
} from "./scenarioSources";

const FIT_PADDING = { top: 78, right: 230, bottom: 74, left: 70 };
/** Focus keeps clear of the focus panel (left) and the layers panel (right). */
const FOCUS_PADDING = { top: 62, right: 210, bottom: 92, left: 268 };
const LOAD_TIMEOUT_MS = 15000;

type Padding = { top: number; right: number; bottom: number; left: number };

/**
 * Padding that always leaves the camera something to fit into.
 *
 * The panels this padding avoids are a fixed pixel size, so in a narrow map
 * column they can add up to more than the column is wide — at which point
 * `fitBounds` has no room left and flings the camera out to the whole basin.
 * Scaling both sides down together keeps the framing intent without that.
 */
function fitPadding(
  size: { width: number; height: number } | null,
  padding: Padding,
): Padding {
  const width = size?.width ?? 0;
  const height = size?.height ?? 0;
  if (width === 0 || height === 0) return padding;

  const horizontal = (padding.left + padding.right) / Math.max(width, 1);
  const vertical = (padding.top + padding.bottom) / Math.max(height, 1);
  // Leave at least ~58% of each axis for the scenario itself.
  const scale = Math.min(1, 0.42 / Math.max(horizontal, vertical, 0.0001));
  if (scale >= 1) return padding;

  return {
    top: padding.top * scale,
    right: padding.right * scale,
    bottom: padding.bottom * scale,
    left: padding.left * scale,
  };
}

/** Source each interactive layer draws from, for feature-state addressing. */
const LAYER_SOURCE = new Map<string, string>(
  LAYERS.flatMap((layer) =>
    "source" in layer && typeof layer.source === "string"
      ? [[layer.id, layer.source] as [string, string]]
      : [],
  ),
);

interface HoverInfo {
  kind: "edge" | "asset" | "hazard" | "flood";
  title: string;
  status?: string;
  statusTone?: string;
  details: string[];
}

/** Registered once per page; the protocol object is stateless across maps. */
let protocolRegistered = false;
function registerPmtilesProtocol() {
  if (protocolRegistered) return;
  maplibregl.addProtocol("pmtiles", new Protocol().tile);
  protocolRegistered = true;
}

/**
 * Basemap layers, plus the subset that is labels-only.
 *
 * `lang` is required: without it the generator emits no symbol layers at all,
 * so place labels would silently disappear. `tuneBasemapLayers` then strips the
 * POI clutter and rebalances roads and water for operational reading.
 */
const basemapLayers = tuneBasemapLayers(
  protomapsLayers(BASEMAP_SOURCE_ID, DARK, { lang: BASEMAP_LANG }),
);
const basemapLabelIds = new Set(
  protomapsLayers(BASEMAP_SOURCE_ID, DARK, {
    lang: BASEMAP_LANG,
    labelsOnly: true,
  }).map((layer) => layer.id),
);

function buildStyle(): StyleSpecification {
  return {
    version: 8,
    glyphs: BASEMAP_GLYPHS,
    sprite: BASEMAP_SPRITE,
    sources: {
      [BASEMAP_SOURCE_ID]: {
        type: "vector",
        url: pmtilesUrl(BASEMAP_PMTILES),
        attribution: `${OSM_ATTRIBUTION} · ${PROTOMAPS_ATTRIBUTION}`,
      },
      [SATELLITE_SOURCE_ID]: {
        type: "raster",
        tiles: [SATELLITE_TILES],
        tileSize: 256,
        maxzoom: 19,
        attribution: SATELLITE_ATTRIBUTION,
      },
      [TERRAIN_SOURCE_ID]: {
        type: "raster-dem",
        tiles: [TERRAIN_TILES],
        tileSize: 256,
        maxzoom: 15,
        encoding: "terrarium",
        attribution: TERRAIN_ATTRIBUTION,
      },
      // `promoteId` lifts each feature's own string id into the id slot, which
      // is what `setFeatureState` addresses. Without it hover, selection and
      // focus would all need numeric ids the domain does not have.
      ...Object.fromEntries(
        Object.values(SOURCE).map((id) => [
          id,
          { type: "geojson" as const, data: EMPTY as never, promoteId: "id" },
        ]),
      ),
    },
    layers: [
      {
        id: SATELLITE_LAYER_ID,
        type: "raster",
        source: SATELLITE_SOURCE_ID,
        layout: { visibility: "none" },
        paint: {
          "raster-opacity": 1,
          "raster-fade-duration": 250,
          // Imagery is busy; a slight desaturation keeps the overlays on top.
          "raster-saturation": -0.3,
          "raster-brightness-max": 0.82,
        },
      },
      ...basemapLayers,
      ...LAYERS,
    ],
  };
}

interface MapLibreScenarioMapProps {
  bootstrap: ScenarioBootstrapResponse;
  worldState: WorldStateSnapshot;
  /** Last frame in the horizon, used for the predicted-inundation layer. */
  horizonState: WorldStateSnapshot | undefined;
  selectedPlan: PlanResult | undefined;
  selection: MapSelection | null;
  onSelect: (selection: MapSelection | null) => void;
  onFailure: (reason: string) => void;
}

const DEFAULT_LAYERS = Object.fromEntries(
  LAYER_CONTROLS.map((control) => [
    control.key,
    !DEFAULT_OFF.includes(control.key) && !control.unavailable,
  ]),
) as Record<LayerKey, boolean>;

export function MapLibreScenarioMap({
  bootstrap,
  worldState,
  horizonState,
  selectedPlan,
  selection,
  onSelect,
  onFailure,
}: MapLibreScenarioMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const animatorRef = useRef<MapAnimator | null>(null);
  const [ready, setReady] = useState(false);
  const [layersOpen, setLayersOpen] = useState(true);
  const [basemapMode, setBasemapMode] = useState<"operational" | "satellite">(
    "satellite",
  );
  const [terrain3d, setTerrain3d] = useState(false);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [diagnostics, setDiagnostics] = useState<string[] | null>(null);
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>(DEFAULT_LAYERS);

  const routeEdgeIds = useMemo(() => routeEdgeIdsFor(selectedPlan), [selectedPlan]);
  const labels = useMemo(() => nodeLabels(bootstrap), [bootstrap]);

  const floodNow = useMemo(
    () => floodNowCollection(bootstrap, worldState),
    [bootstrap, worldState.frame_id],
  );
  const floodForecast = useMemo(
    () => floodForecastCollection(bootstrap, worldState, horizonState),
    [bootstrap, horizonState?.frame_id, worldState.frame_id],
  );

  const collections = useMemo(
    (): Record<string, MapFeatureCollection> => ({
      [SOURCE.context]: contextCollection(bootstrap),
      [SOURCE.floodForecast]: floodForecast,
      [SOURCE.floodNow]: floodNow,
      [SOURCE.channel]: channelCollection(),
      [SOURCE.roads]: roadsCollection(bootstrap, worldState, routeEdgeIds),
      [SOURCE.bridgeLines]: bridgeLinesCollection(bootstrap, worldState),
      [SOURCE.roadHazards]: roadHazardsCollection(bootstrap, worldState),
      [SOURCE.route]: routeCollection(bootstrap, worldState, selectedPlan),
      [SOURCE.routeAlternate]: alternateRouteCollection(
        bootstrap,
        worldState,
        selectedPlan,
      ),
      [SOURCE.assets]: assetsCollection(bootstrap, worldState),
      [SOURCE.bridges]: bridgesCollection(bootstrap, worldState),
      [SOURCE.hazards]: hazardsCollection(bootstrap, worldState),
    }),
    [bootstrap, floodForecast, floodNow, routeEdgeIds, selectedPlan, worldState],
  );

  const focus = useMemo(
    () => buildFocus(bootstrap, worldState, selection),
    [bootstrap, selection, worldState],
  );

  const edgeStateById = useMemo(
    () => new Map(worldState.edge_states.map((edge) => [edge.edge_id, edge])),
    [worldState.edge_states],
  );

  /* Refs keep the map's own event handlers reading current data without
   * re-registering them on every world-state change. */
  const edgeStateRef = useRef(edgeStateById);
  edgeStateRef.current = edgeStateById;
  const labelsRef = useRef(labels);
  labelsRef.current = labels;
  const bootstrapRef = useRef(bootstrap);
  bootstrapRef.current = bootstrap;
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const failureRef = useRef(onFailure);
  failureRef.current = onFailure;

  /** Assets already at critical, and the one hazard currently pulsing. */
  const criticalAssetsRef = useRef<Set<string> | null>(null);
  const pulsingRef = useRef<{ hazardId: string; assetId: string } | null>(null);

  /* ------------------------------------------------------------ map init */

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    registerPmtilesProtocol();

    let map: maplibregl.Map;
    try {
      map = new maplibregl.Map({
        container,
        style: buildStyle(),
        bounds: scenarioBounds(bootstrap),
        fitBoundsOptions: {
          padding: fitPadding(container.getBoundingClientRect(), FIT_PADDING),
        },
        attributionControl: false,
      });
    } catch (initError) {
      failureRef.current(
        initError instanceof Error ? initError.message : "MapLibre failed to initialize",
      );
      return undefined;
    }

    mapRef.current = map;

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric", maxWidth: 110 }), "bottom-left");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    // A missing or unreadable PMTiles archive is fatal; tile 404s are not.
    map.on("error", (event: maplibregl.ErrorEvent) => {
      const message = event.error?.message ?? "";
      if (import.meta.env.DEV) console.error("[maplibre]", event.error);

      if (/pmtiles|archive|unsupported|magic number|style/i.test(message)) {
        failureRef.current(message || "Basemap archive could not be read");
      }

      /*
       * A rejected layer spec — a bad expression, a paint-only property used in
       * a layout slot — discards the whole style, so "load" never fires and the
       * panel would otherwise spin indefinitely with no sign of why.
       */
      if (/^layers\[\d+\]|expression|not supported with layout/i.test(message)) {
        failureRef.current(`Map style rejected: ${message}`);
      }
    });

    /*
     * MapLibre defers style loading to an animation frame, so in a context
     * where requestAnimationFrame never runs — a hidden tab, a throttled
     * webview, some headless browsers — "load" simply never fires and no error
     * is raised. Without this the panel would spin forever, so fall back to the
     * schematic instead.
     */
    let loaded = false;
    const watchdog = window.setTimeout(() => {
      // Keyed on "load", not on `isStyleLoaded`: a style can report itself
      // loaded while the render loop never starts, and that case has to fall
      // back too rather than leave the panel spinning.
      if (loaded) return;
      failureRef.current(
        document.visibilityState === "hidden"
          ? "Basemap could not start while the tab was hidden"
          : "Basemap did not finish loading",
      );
    }, LOAD_TIMEOUT_MS);

    map.on("load", () => {
      loaded = true;
      window.clearTimeout(watchdog);

      // Symbols must exist before any data reaches the symbol layers, which is
      // why this runs before `ready` unlocks the data effects.
      try {
        registerMarkerImages(map);
      } catch (imageError) {
        failureRef.current(
          imageError instanceof Error
            ? imageError.message
            : "Map symbols could not be rasterised",
        );
        return;
      }

      animatorRef.current = createMapAnimator(map);
      setReady(true);

      // A zero-sized drawing buffer renders nothing and raises no error, so
      // recover from it and surface it rather than showing an empty panel.
      window.setTimeout(() => {
        if (!mapRef.current) return;
        map.resize();
        const canvas = map.getCanvas();
        if (canvas.width === 0 || canvas.height === 0) {
          failureRef.current(
            "Map container has zero size — the GL canvas cannot render",
          );
          return;
        }

        // Re-fit once the canvas has its real size. The constructor runs before
        // layout has settled, so the padding clamp has nothing to measure then
        // and the scenario ends up framed at half the zoom it deserves.
        map.fitBounds(scenarioBounds(bootstrap), {
          padding: fitPadding(canvas.getBoundingClientRect(), FIT_PADDING),
          duration: 0,
        });
      }, 250);
    });

    return () => {
      window.clearTimeout(watchdog);
      setReady(false);
      animatorRef.current?.destroy();
      animatorRef.current = null;
      mapRef.current = null;
      map.remove();
    };
  }, [bootstrap]);

  /* ------------------------------------------------------- hover + click */

  /** The feature currently carrying `hover` state, so it can be cleared. */
  const hoveredRef = useRef<{ source: string; id: string } | null>(null);

  const clearHover = useCallback(() => {
    const map = mapRef.current;
    const previous = hoveredRef.current;
    if (map && previous) {
      map.setFeatureState(previous, { hover: false });
    }
    hoveredRef.current = null;
    setHover(null);
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return undefined;

    const describe = (feature: maplibregl.MapGeoJSONFeature): HoverInfo | null => {
      const properties = feature.properties ?? {};
      const layerId = feature.layer.id;

      if (HAZARD_LAYERS.includes(layerId)) {
        return {
          kind: "hazard",
          title: String(properties.title ?? "Hazard"),
          status: String(properties.priority ?? ""),
          statusTone: String(properties.priority ?? ""),
          details: [String(properties.subject ?? ""), String(properties.description ?? "")],
        };
      }

      if (ASSET_LAYERS.includes(layerId)) {
        const type = String(properties.asset_type ?? "asset");
        const details: string[] = [];
        if (properties.population) {
          details.push(`${Number(properties.population).toLocaleString()} residents`);
        }
        if (properties.capacity) {
          details.push(`capacity ${Number(properties.capacity).toLocaleString()}`);
        }
        if (type === "community") {
          details.push(
            properties.isolated
              ? "no reachable shelter"
              : `${properties.reachable_shelters} shelters reachable`,
          );
        }
        return {
          kind: "asset",
          title: String(properties.name ?? properties.id),
          status: type,
          statusTone: properties.isolated ? "closed" : "open",
          details,
        };
      }

      if (FLOOD_LAYERS.includes(layerId)) {
        return {
          kind: "flood",
          title: String(properties.band_label ?? "Modeled depth"),
          status: properties.display_state === "forecast" ? "modeled" : "current",
          statusTone: "flood",
          details: [
            `+${Number(properties.simulation_time_hours ?? 0)}h frame`,
            String(properties.surface_kind ?? "").replaceAll("_", " "),
          ],
        };
      }

      // Everything else resolves to an edge, whether it was picked from the
      // road line, the bridge deck, or a closure symbol.
      const edgeId = String(
        layerId === "bridge-hazards" ? properties.edge_id : properties.id,
      );
      const state = edgeStateRef.current.get(edgeId);
      if (!state) return null;

      return {
        kind: "edge",
        title: edgeLabel(bootstrapRef.current, labelsRef.current, edgeId),
        status: state.status,
        statusTone: state.status,
        details: [
          `${state.flood_depth_m.toFixed(2)} m water`,
          state.effective_travel_minutes === null
            ? "impassable"
            : `${state.effective_travel_minutes} min`,
          state.critical ? "critical route" : "",
        ],
      };
    };

    const onMove = (event: maplibregl.MapMouseEvent) => {
      const picked = map.queryRenderedFeatures(event.point, {
        layers: PICKABLE_LAYERS.filter((id) => map.getLayer(id)),
      });
      const feature =
        picked[0] ??
        map.queryRenderedFeatures(event.point, {
          layers: FLOOD_LAYERS.filter((id) => map.getLayer(id)),
        })[0];

      if (!feature) {
        map.getCanvas().style.cursor = "";
        clearHover();
        return;
      }

      map.getCanvas().style.cursor = "pointer";

      const source = LAYER_SOURCE.get(feature.layer.id);
      const id = feature.id === undefined ? null : String(feature.id);
      const previous = hoveredRef.current;

      if (source && id && (previous?.id !== id || previous.source !== source)) {
        if (previous) map.setFeatureState(previous, { hover: false });
        map.setFeatureState({ source, id }, { hover: true });
        hoveredRef.current = { source, id };
      }

      setHover(describe(feature));
    };

    const onClick = (event: maplibregl.MapMouseEvent) => {
      const picked = map.queryRenderedFeatures(event.point, {
        layers: PICKABLE_LAYERS.filter((id) => map.getLayer(id)),
      })[0];

      if (!picked) {
        selectRef.current(null);
        return;
      }

      const properties = picked.properties ?? {};
      const layerId = picked.layer.id;

      if (HAZARD_LAYERS.includes(layerId)) {
        selectRef.current({ kind: "hazard", id: String(properties.hazard_id) });
        return;
      }
      if (ASSET_LAYERS.includes(layerId)) {
        selectRef.current({ kind: "asset", id: String(properties.id) });
        return;
      }
      if (layerId === "bridge-hazards") {
        selectRef.current({ kind: "edge", id: String(properties.edge_id) });
        return;
      }
      if ([...EDGE_LAYERS, ...EDGE_SYMBOL_LAYERS].includes(layerId)) {
        selectRef.current({ kind: "edge", id: String(properties.id) });
      }
    };

    map.on("mousemove", onMove);
    map.on("mouseout", clearHover);
    map.on("click", onClick);

    return () => {
      map.off("mousemove", onMove);
      map.off("mouseout", clearHover);
      map.off("click", onClick);
    };
  }, [clearHover, ready]);

  /* --------------------------------------------------------- diagnostics */

  const runDiagnostics = useCallback(() => {
    const map = mapRef.current;
    const element = containerRef.current;
    if (!map || !element) {
      setDiagnostics(["map instance: missing"]);
      return;
    }

    const canvas = map.getCanvas();
    const style = map.getStyle();
    const centre = map.getCenter();
    const lines = [
      `container: ${element.clientWidth}x${element.clientHeight}`,
      `canvas: ${canvas.width}x${canvas.height} (css ${canvas.clientWidth}x${canvas.clientHeight})`,
      `webgl context: ${canvas.getContext("webgl2") ? "webgl2" : canvas.getContext("webgl") ? "webgl1" : "NONE"}`,
      `style loaded: ${map.isStyleLoaded()} · layers: ${style?.layers?.length ?? 0}`,
      `camera: ${centre.lng.toFixed(4)},${centre.lat.toFixed(4)} z${map.getZoom().toFixed(2)} pitch${map.getPitch().toFixed(0)}`,
    ];

    [BASEMAP_SOURCE_ID, SATELLITE_SOURCE_ID, SOURCE.roads, SOURCE.assets].forEach((id) => {
      let state: string;
      try {
        state = map.getSource(id) ? `${map.isSourceLoaded(id)}` : "MISSING";
      } catch (error) {
        state = `err ${(error as Error).message}`;
      }
      lines.push(`source ${id}: ${state}`);
    });

    const roads = map.querySourceFeatures(SOURCE.roads);
    lines.push(`roads features in source: ${roads.length}`);
    lines.push(`map symbols registered: ${map.hasImage("ark-community") ? "yes" : "NO"}`);

    // Motion state comes from the animator rather than from the map, because
    // `querySourceFeatures` only sees sources whose layers are within their
    // zoom range — a parked loop and a zoomed-out layer would look identical.
    lines.push(`motion: ${animatorRef.current?.describe() ?? "animator missing"}`);
    lines.push(`escalated asset: ${pulsingRef.current?.assetId ?? "none"}`);
    lines.push(
      `rendered features at centre: ${map.queryRenderedFeatures().length}`,
    );

    setDiagnostics(lines);
    console.info("[ark map diagnostics]\n" + lines.join("\n"));
  }, []);

  /* ------------------------------------------------------------ map data */

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    Object.entries(collections).forEach(([id, data]) => {
      if (id === SOURCE.floodNow || id === SOURCE.floodForecast) return;
      const source = map.getSource(id);
      if (source && "setData" in source) {
        (source as maplibregl.GeoJSONSource).setData(
          data as unknown as GeoJSON.FeatureCollection,
        );
      }
    });
  }, [collections, ready]);

  // Depth bands cross-fade between frames rather than snapping, so scrubbing
  // the timeline reads as water moving instead of polygons flickering.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return undefined;

    map.setPaintProperty("flood-current-fill", "fill-opacity", 0.08);
    map.setPaintProperty("flood-modeled-fill", "fill-opacity", 0.015);

    const restore = window.setTimeout(() => {
      const currentSource = map.getSource(SOURCE.floodNow);
      const forecastSource = map.getSource(SOURCE.floodForecast);
      if (currentSource && "setData" in currentSource) {
        (currentSource as maplibregl.GeoJSONSource).setData(
          floodNow as unknown as GeoJSON.FeatureCollection,
        );
      }
      if (forecastSource && "setData" in forecastSource) {
        (forecastSource as maplibregl.GeoJSONSource).setData(
          floodForecast as unknown as GeoJSON.FeatureCollection,
        );
      }
      map.setPaintProperty("flood-current-fill", "fill-opacity", [
        "interpolate",
        ["linear"],
        ["get", "depth_max_m"],
        0.1,
        CURRENT_FLOOD_OPACITY * 0.62,
        0.5,
        CURRENT_FLOOD_OPACITY,
      ]);
      map.setPaintProperty(
        "flood-modeled-fill",
        "fill-opacity",
        FORECAST_FLOOD_OPACITY,
      );
    }, 70);

    return () => window.clearTimeout(restore);
  }, [floodForecast, floodNow, ready]);

  /* ------------------------------------------------- selection and focus */

  /** Feature-state written for the current focus, so it can be undone exactly. */
  const focusStateRef = useRef<Array<{ source: string; id: string }>>([]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    focusStateRef.current.forEach((target) => {
      map.setFeatureState(target, { dim: false, selected: false });
    });
    focusStateRef.current = [];

    if (!focus) return;

    const applied: Array<{ source: string; id: string }> = [];

    const apply = (
      source: string,
      id: string,
      state: { dim: boolean; selected: boolean },
    ) => {
      map.setFeatureState({ source, id }, state);
      applied.push({ source, id });
    };

    Object.entries(collections).forEach(([sourceId, collection]) => {
      collection.features.forEach((feature) => {
        const id = String(feature.properties.id ?? feature.id ?? "");
        if (!id) return;

        let related: boolean;
        let primary = false;

        switch (sourceId) {
          case SOURCE.assets:
            related = focus.assetIds.has(id);
            primary = focus.primaryAssetId === id;
            break;
          case SOURCE.roads:
          case SOURCE.roadHazards:
            related = focus.edgeIds.has(id);
            primary = focus.primaryEdgeId === id;
            break;
          case SOURCE.bridges:
          case SOURCE.bridgeLines: {
            const edgeId = String(feature.properties.edge_id ?? id);
            related = focus.edgeIds.has(edgeId);
            primary = focus.primaryEdgeId === edgeId;
            break;
          }
          case SOURCE.hazards:
            related = focus.hazardIds.has(id);
            primary = focus.selection.kind === "hazard" && focus.selection.id === id;
            break;
          case SOURCE.route:
          case SOURCE.routeAlternate:
            related = focus.assetIds.has(String(feature.properties.community_id ?? ""));
            // The team marker shares its route's id, so it fades with the
            // route it is travelling rather than floating at full weight.
            if (sourceId === SOURCE.route) {
              apply(SOURCE.teams, id, { dim: !related, selected: false });
            }
            break;
          default:
            return;
        }

        apply(sourceId, id, { dim: !related, selected: primary });
      });
    });

    focusStateRef.current = applied;
  }, [collections, focus, ready]);

  /* ------------------------------------------------------------ motion */

  /*
   * Response teams travel the selected plan's routes.
   *
   * Handing the animator an empty collection when the route layer is switched
   * off is what stops the loop — there is then nothing moving for it to draw,
   * and it parks itself until routes come back.
   */
  useEffect(() => {
    if (!ready) return;
    animatorRef.current?.setRoutes(
      layers.route ? collections[SOURCE.route] : EMPTY,
    );
  }, [collections, layers.route, ready]);

  useEffect(() => {
    if (!ready) return;
    animatorRef.current?.setFocusedCommunities(focus ? focus.assetIds : null);
  }, [focus, ready]);

  /*
   * Escalation pulse.
   *
   * Hazard ids carry the world-state version, so they are new on every frame
   * and cannot be compared directly. Escalation is therefore tracked per asset:
   * an asset that was not critical in the previous state and is critical now
   * has just escalated, and that is the only thing worth a pulse.
   */
  useEffect(() => {
    if (!ready) return;

    const criticalAssets = new Set(
      worldState.hazards
        .filter((hazard) => hazard.priority === "critical")
        .map((hazard) => hazard.asset_id),
    );
    const previous = criticalAssetsRef.current;
    criticalAssetsRef.current = criticalAssets;

    // Nothing has escalated on the first state the operator sees; everything
    // there is simply the starting condition.
    if (!previous) return;

    // Hazards arrive prioritised, so the first match is the one that matters.
    const escalated = worldState.hazards.find(
      (hazard) =>
        hazard.priority === "critical" && !previous.has(hazard.asset_id),
    );

    if (!escalated) {
      // A hazard that has stopped being critical should stop pulsing too.
      if (pulsingRef.current && !criticalAssets.has(pulsingRef.current.assetId)) {
        pulsingRef.current = null;
        animatorRef.current?.pulseHazard(null);
      }
      return;
    }

    pulsingRef.current = {
      hazardId: escalated.hazard_id,
      assetId: escalated.asset_id,
    };
    animatorRef.current?.pulseHazard(escalated.hazard_id);
  }, [ready, worldState]);

  // Acknowledgement stops the pulse: once the operator has selected the
  // incident, the map has already done its job of pointing at it.
  useEffect(() => {
    const pulsing = pulsingRef.current;
    if (!ready || !selection || !pulsing) return;

    const acknowledged =
      (selection.kind === "hazard" && selection.id === pulsing.hazardId) ||
      (selection.kind === "edge" && selection.id === pulsing.assetId) ||
      (selection.kind === "asset" && selection.id === pulsing.assetId);

    if (acknowledged) {
      pulsingRef.current = null;
      animatorRef.current?.pulseHazard(null);
    }
  }, [ready, selection]);

  // Clicking a hazard in a side panel should move the camera the same way
  // clicking it on the map does.
  const focusKey = focus
    ? `${focus.selection.kind}:${focus.selection.id}`
    : null;

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !focus) return;

    const bounds = boundsFor(focus.positions as Position[]);
    if (!bounds) return;

    const [[west, south], [east, north]] = bounds;
    if (west === east && south === north) {
      map.easeTo({ center: [west, south], zoom: Math.max(map.getZoom(), 14), duration: 800 });
      return;
    }

    map.fitBounds(bounds, {
      padding: fitPadding(map.getCanvas().getBoundingClientRect(), FOCUS_PADDING),
      duration: 850,
      maxZoom: 15.5,
    });
    // Only the identity of the focused incident should move the camera; a
    // timeline step that changes its metrics must not re-fly the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusKey, ready]);

  /* ---------------------------------------------------- layer visibility */

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    LAYER_CONTROLS.forEach((control) => {
      control.layerIds.forEach((layerId) => {
        if (map.getLayer(layerId)) {
          map.setLayoutProperty(
            layerId,
            "visibility",
            layers[control.key] ? "visible" : "none",
          );
        }
      });
    });
  }, [layers, ready]);

  /* -------------------------------------------------- satellite basemap */

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    const satellite = basemapMode === "satellite";

    if (map.getLayer(SATELLITE_LAYER_ID)) {
      map.setLayoutProperty(
        SATELLITE_LAYER_ID,
        "visibility",
        satellite ? "visible" : "none",
      );
    }

    // Over imagery, keep only the basemap's labels so the photo reads through.
    basemapLayers.forEach((layer) => {
      if (!map.getLayer(layer.id)) return;
      const keep = !satellite || basemapLabelIds.has(layer.id);
      map.setLayoutProperty(layer.id, "visibility", keep ? "visible" : "none");
    });
  }, [basemapMode, ready]);

  /* ----------------------------------------------------------- 3D terrain */

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    if (terrain3d) {
      // Kept deliberately gentle: enough relief to show water running off the
      // valley sides, not so much that markers slide off their locations.
      map.setTerrain({ source: TERRAIN_SOURCE_ID, exaggeration: 1.25 });
      map.setSky({
        "sky-color": "#0d1b2c",
        "horizon-color": "#1d3350",
        "fog-color": "#0a1420",
        "sky-horizon-blend": 0.6,
        "horizon-fog-blend": 0.5,
        "fog-ground-blend": 0.2,
      });
      map.easeTo({ pitch: 48, duration: 900 });
    } else {
      map.setTerrain(null);
      map.easeTo({ pitch: 0, bearing: 0, duration: 700 });
    }
  }, [ready, terrain3d]);

  const resetView = useCallback(() => {
    onSelect(null);
    const map = mapRef.current;
    if (!map) return;
    map.fitBounds(scenarioBounds(bootstrap), {
      padding: fitPadding(map.getCanvas().getBoundingClientRect(), FIT_PADDING),
      duration: 900,
    });
  }, [bootstrap, onSelect]);

  const toggleLayer = (key: LayerKey) =>
    setLayers((current) => ({ ...current, [key]: !current[key] }));

  const eventActive = worldState.active_event_ids.length > 0;

  return (
    <section
      className={`map-card maplibre-card ${focus ? "focused" : ""}`}
      aria-label="Kantipur River scenario map"
    >
      <div className="map-canvas" ref={containerRef} />
      {!ready ? (
        <div className="map-booting" role="status">
          <span className="map-booting-spinner" />
          Loading basemap…
        </div>
      ) : null}

      <div className="map-toolbar">
        <span className={`state-pill ${eventActive ? "event" : "baseline"}`}>
          <i />
          {eventActive ? "Event active" : "Baseline"}
        </span>
        <span className="frame-pill">
          {worldState.simulation_time_hours === 0
            ? "Now"
            : `+${worldState.simulation_time_hours}h modeled`}
        </span>
        <span className="state-version">{worldState.world_state_version}</span>
      </div>

      <div className={`map-layers ${layersOpen ? "open" : "closed"}`}>
        <button
          className="map-layers-toggle"
          type="button"
          onClick={() => setLayersOpen((open) => !open)}
          aria-expanded={layersOpen}
        >
          <ShellIcon name="layers" />
          <span>Map layers</span>
          <i className="layers-chevron" aria-hidden="true">
            <ShellIcon name="chevron" size={13} />
          </i>
        </button>
        {layersOpen ? (
          <div className="map-layers-body">
            <span className="layer-group-label">Basemap</span>
            <label className="layer-toggle">
              <input
                checked={basemapMode === "operational"}
                name="ark-basemap"
                onChange={() => setBasemapMode("operational")}
                type="radio"
              />
              <span className="layer-swatch operational" aria-hidden="true" />
              Operational
            </label>
            <label className="layer-toggle">
              <input
                checked={basemapMode === "satellite"}
                name="ark-basemap"
                onChange={() => setBasemapMode("satellite")}
                type="radio"
              />
              <span className="layer-swatch satellite" aria-hidden="true" />
              Satellite
            </label>

            <div className="layer-divider" />
            <span className="layer-group-label">Overlays</span>

            {LAYER_CONTROLS.map((control) => (
              <label
                className={`layer-toggle ${control.unavailable ? "unavailable" : ""}`}
                key={control.key}
                title={control.unavailable}
              >
                <input
                  checked={layers[control.key] && !control.unavailable}
                  disabled={Boolean(control.unavailable)}
                  onChange={() => toggleLayer(control.key)}
                  type="checkbox"
                />
                <span className={`layer-swatch ${control.swatch}`} aria-hidden="true" />
                {control.label}
              </label>
            ))}

            <label className="layer-toggle">
              <input
                checked={terrain3d}
                onChange={() => setTerrain3d((on) => !on)}
                type="checkbox"
              />
              <span className="layer-swatch terrain" aria-hidden="true" />
              3D terrain
            </label>

            <button className="layer-reset" type="button" onClick={resetView}>
              <ShellIcon name="crosshair" size={12} /> Reset to scenario extent
            </button>
            <button className="layer-reset" type="button" onClick={runDiagnostics}>
              <ShellIcon name="activity" size={12} /> Diagnose blank map
            </button>
          </div>
        ) : null}
      </div>

      {focus ? (
        <div className="incident-focus" role="region" aria-label="Focused incident">
          <header>
            <span className="focus-kind">{focus.kindLabel}</span>
            <button
              className="focus-exit"
              type="button"
              onClick={() => onSelect(null)}
            >
              <ShellIcon name="x" size={11} /> Exit focus
            </button>
          </header>
          <strong>{focus.title}</strong>
          <p>{focus.summary}</p>
          <dl>
            {focus.facts.map((fact) => (
              <div className={`focus-fact ${fact.tone ?? "neutral"}`} key={fact.label}>
                <dt>{fact.label}</dt>
                <dd>{fact.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      <div className={`edge-inspector ${hover ? "visible" : ""}`} role="status">
        {hover ? (
          <>
            <strong>{hover.title}</strong>
            {hover.status ? (
              <span className={`inspector-status ${hover.statusTone ?? ""}`}>
                {hover.status}
              </span>
            ) : null}
            {hover.details
              .filter(Boolean)
              .map((detail) => (
                <span key={detail}>{detail}</span>
              ))}
          </>
        ) : (
          <span className="inspector-hint">
            Hover to inspect · click to focus an incident
          </span>
        )}
      </div>

      <div className="map-legend" aria-label="Map legend">
        <div className="legend-block">
          <strong>Flood depth</strong>
          <span><i className="depth-1" />0–0.10 m</span>
          <span><i className="depth-2" />0.10–0.20 m</span>
          <span><i className="depth-3" />0.20–0.30 m</span>
          <span><i className="depth-4" />0.30–0.50 m</span>
        </div>
        <div className="legend-block">
          <strong>Status</strong>
          <span><i className="glyph community" />Community</span>
          <span><i className="glyph shelter" />Shelter</span>
          <span><i className="glyph hospital" />Hospital</span>
          <span><i className="glyph hazard" />Hazard</span>
          <span><i className="glyph team" />Response team</span>
        </div>
        <div className="legend-block wide">
          <span><i className="rule current" />Current</span>
          <span><i className="rule modeled" />Modeled +24h</span>
          <span><i className="glyph injected" />Operator injected</span>
        </div>
      </div>

      {diagnostics ? (
        <div className="map-diagnostics" role="status">
          <button type="button" onClick={() => setDiagnostics(null)} aria-label="Close diagnostics">
            <ShellIcon name="x" size={12} />
          </button>
          <strong>Map diagnostics</strong>
          {diagnostics.map((line) => (
            <code key={line}>{line}</code>
          ))}
        </div>
      ) : null}

      <div className="map-provenance">
        Curated synthetic depth surface for situational awareness · not a hydraulic solve or operational forecast.
      </div>
    </section>
  );
}
