import { useCallback, useEffect, useMemo, useRef, useState } from "react";
// MapLibre v6 has no default export.
import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
import { Protocol } from "pmtiles";
import { DARK, layers as protomapsLayers } from "@protomaps/basemaps";

import "maplibre-gl/dist/maplibre-gl.css";

import type {
  DerivedEdgeState,
  PlanResult,
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
import {
  HOVERABLE_ROAD_LAYERS,
  LAYERS,
  LAYER_CONTROLS,
  SOURCE,
  type LayerKey,
} from "./layers";
import {
  assetsCollection,
  bridgesCollection,
  channelCollection,
  contextCollection,
  EMPTY,
  floodForecastCollection,
  floodNowCollection,
  hazardsCollection,
  predictionSignalsCollection,
  roadsCollection,
  routeCollection,
  routeEdgeIdsFor,
  scenarioBounds,
  type MapFeatureCollection,
} from "./scenarioSources";

const FIT_PADDING = { top: 78, right: 230, bottom: 74, left: 70 };
const LOAD_TIMEOUT_MS = 15000;
const BUILDING_3D_LAYER_ID = "basemap-buildings-3d";

/** Registered once per page; the protocol object is stateless across maps. */
let protocolRegistered = false;
function registerPmtilesProtocol() {
  if (protocolRegistered) return;
  maplibregl.addProtocol("pmtiles", new Protocol().tile);
  protocolRegistered = true;
}

function predictionPopupContent(properties: Record<string, unknown>): HTMLDivElement {
  const text = (key: string) => String(properties[key] ?? "");
  const root = document.createElement("div");
  root.className = "prediction-popup-card";

  const heading = document.createElement("div");
  heading.className = "prediction-popup-heading";
  const title = document.createElement("strong");
  title.textContent = text("label");
  const state = document.createElement("span");
  state.textContent = text("state");
  heading.append(title, state);

  const risk = document.createElement("div");
  risk.className = "prediction-popup-risk";
  const value = document.createElement("strong");
  value.textContent = `${text("percent")}%`;
  const valueLabel = document.createElement("span");
  valueLabel.textContent = "current timeline risk";
  risk.append(value, valueLabel);

  const metrics = document.createElement("div");
  metrics.className = "prediction-popup-metrics";
  const prior = document.createElement("span");
  prior.textContent = `Event prior ${text("base_percent")}%`;
  const depth = document.createElement("span");
  const depthValue = Number(properties.local_flood_depth_m ?? 0);
  depth.textContent = `Nearby depth ${depthValue.toFixed(2)} m`;
  metrics.append(prior, depth);

  const whyLabel = document.createElement("small");
  whyLabel.textContent = "Why this ping";
  const why = document.createElement("p");
  why.textContent = text("reason");
  const actionLabel = document.createElement("small");
  actionLabel.textContent = "Recommended action";
  const action = document.createElement("p");
  action.className = "prediction-popup-action";
  action.textContent = text("recommended_action");

  root.append(heading, risk, metrics, whyLabel, why, actionLabel, action);
  return root;
}

/**
 * Basemap layers, plus the subset that is labels-only.
 *
 * `lang` is required: without it the generator emits no symbol layers at all,
 * so place labels would silently disappear.
 */
const basemapLayers = protomapsLayers(BASEMAP_SOURCE_ID, DARK, {
  lang: BASEMAP_LANG,
});
const basemapLabelIds = new Set(
  protomapsLayers(BASEMAP_SOURCE_ID, DARK, {
    lang: BASEMAP_LANG,
    labelsOnly: true,
  }).map((layer) => layer.id),
);

function buildStyle(): StyleSpecification {
  return {
    version: 8,
    light: {
      anchor: "map",
      color: "#8ed8ff",
      intensity: 0.38,
      position: [1.15, 205, 35],
    },
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
      ...Object.fromEntries(
        Object.values(SOURCE).map((id) => [
          id,
          { type: "geojson" as const, data: EMPTY as never },
        ]),
      ),
    },
    layers: [
      {
        id: SATELLITE_LAYER_ID,
        type: "raster",
        source: SATELLITE_SOURCE_ID,
        layout: { visibility: "none" },
        paint: { "raster-opacity": 1, "raster-fade-duration": 250 },
      },
      ...basemapLayers,
      {
        id: BUILDING_3D_LAYER_ID,
        type: "fill-extrusion",
        source: BASEMAP_SOURCE_ID,
        "source-layer": "buildings",
        minzoom: 13,
        filter: ["in", "kind", "building", "building_part"],
        paint: {
          "fill-extrusion-color": [
            "interpolate",
            ["linear"],
            ["zoom"],
            13,
            "#132839",
            16,
            "#2c536a",
          ],
          "fill-extrusion-height": [
            "interpolate",
            ["linear"],
            ["zoom"],
            13,
            0,
            13.6,
            [
              "case",
              ["has", "height"],
              ["to-number", ["get", "height"]],
              ["has", "levels"],
              ["*", ["to-number", ["get", "levels"]], 3],
              8,
            ],
          ],
          "fill-extrusion-base": [
            "case",
            ["has", "min_height"],
            ["to-number", ["get", "min_height"]],
            0,
          ],
          "fill-extrusion-opacity": 0.78,
          "fill-extrusion-vertical-gradient": true,
        },
      },
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
  onFailure: (reason: string) => void;
}

const DEFAULT_LAYERS: Record<LayerKey, boolean> = {
  context: false,
  floodNow: true,
  floodForecast: true,
  roads: true,
  route: true,
  facilities: true,
  bridges: true,
  gauges: false,
  alerts: true,
  predictions: true,
  labels: true,
};

export function MapLibreScenarioMap({
  bootstrap,
  worldState,
  horizonState,
  selectedPlan,
  onFailure,
}: MapLibreScenarioMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const predictionPopupRef = useRef<maplibregl.Popup | null>(null);
  const [ready, setReady] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const [satellite, setSatellite] = useState(false);
  const [terrain3d, setTerrain3d] = useState(true);
  const [hovered, setHovered] = useState<DerivedEdgeState | null>(null);
  const [diagnostics, setDiagnostics] = useState<string[] | null>(null);
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>(DEFAULT_LAYERS);

  const routeEdgeIds = useMemo(() => routeEdgeIdsFor(selectedPlan), [selectedPlan]);

  const collections = useMemo(
    (): Record<string, MapFeatureCollection> => ({
      [SOURCE.context]: contextCollection(bootstrap),
      [SOURCE.floodForecast]: floodForecastCollection(horizonState),
      [SOURCE.floodNow]: floodNowCollection(worldState),
      [SOURCE.channel]: channelCollection(),
      [SOURCE.roads]: roadsCollection(bootstrap, worldState, routeEdgeIds),
      [SOURCE.route]: routeCollection(bootstrap, routeEdgeIds),
      [SOURCE.assets]: assetsCollection(bootstrap, worldState),
      [SOURCE.bridges]: bridgesCollection(bootstrap, worldState),
      [SOURCE.hazards]: hazardsCollection(bootstrap, worldState),
      [SOURCE.predictions]: predictionSignalsCollection(worldState),
    }),
    [bootstrap, horizonState, routeEdgeIds, worldState],
  );

  const edgeStateById = useMemo(
    () => new Map(worldState.edge_states.map((edge) => [edge.edge_id, edge])),
    [worldState.edge_states],
  );
  const edgeStateRef = useRef(edgeStateById);
  edgeStateRef.current = edgeStateById;

  const failureRef = useRef(onFailure);
  failureRef.current = onFailure;

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
        bounds: scenarioBounds(bootstrap, worldState),
        fitBoundsOptions: { padding: FIT_PADDING },
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
    });

    /*
     * MapLibre defers style loading to an animation frame, so in a context
     * where requestAnimationFrame never runs — a hidden tab, a throttled
     * webview, some headless browsers — "load" simply never fires and no error
     * is raised. Without this the panel would spin forever, so fall back to the
     * schematic instead.
     */
    const watchdog = window.setTimeout(() => {
      if (!map.isStyleLoaded()) {
        failureRef.current(
          document.visibilityState === "hidden"
            ? "Basemap could not start while the tab was hidden"
            : "Basemap did not finish loading",
        );
      }
    }, LOAD_TIMEOUT_MS);

    map.on("load", () => {
      window.clearTimeout(watchdog);
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
        }
      }, 250);
    });

    const enter = () => {
      map.getCanvas().style.cursor = "pointer";
    };
    const move = (event: maplibregl.MapLayerMouseEvent) => {
      const id = event.features?.[0]?.properties?.id;
      if (typeof id === "string") setHovered(edgeStateRef.current.get(id) ?? null);
    };
    const leave = () => {
      map.getCanvas().style.cursor = "";
      setHovered(null);
    };
    const showPrediction = (event: maplibregl.MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature || feature.geometry.type !== "Point") return;
      const coordinates = feature.geometry.coordinates as [number, number];
      predictionPopupRef.current?.remove();
      predictionPopupRef.current = new maplibregl.Popup({
        className: "ark-prediction-popup",
        closeButton: true,
        closeOnClick: true,
        maxWidth: "310px",
        offset: 16,
      })
        .setLngLat(coordinates)
        .setDOMContent(
          predictionPopupContent(feature.properties as Record<string, unknown>),
        )
        .addTo(map);
    };

    HOVERABLE_ROAD_LAYERS.forEach((layerId) => {
      map.on("mouseenter", layerId, enter);
      map.on("mousemove", layerId, move);
      map.on("mouseleave", layerId, leave);
    });
    map.on("mouseenter", "ark-prediction-ping", enter);
    map.on("mouseleave", "ark-prediction-ping", leave);
    map.on("click", "ark-prediction-ping", showPrediction);

    return () => {
      window.clearTimeout(watchdog);
      predictionPopupRef.current?.remove();
      predictionPopupRef.current = null;
      setReady(false);
      mapRef.current = null;
      map.remove();
    };
  }, [bootstrap]);

  useEffect(() => {
    const element = containerRef.current;
    const map = mapRef.current;
    if (!element || !map) return undefined;

    const observer = new ResizeObserver(() => map.resize());
    observer.observe(element);
    return () => observer.disconnect();
  }, [ready]);

  /* ----------------------------------------------- prediction ping pulse */

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return undefined;
    }

    let animationFrame = 0;
    const animate = (timestamp: number) => {
      if (!mapRef.current || !map.getLayer("ark-prediction-pulse")) return;
      const phase = (timestamp % 1800) / 1800;
      map.setPaintProperty("ark-prediction-pulse", "circle-radius", 14 + phase * 20);
      map.setPaintProperty(
        "ark-prediction-pulse",
        "circle-opacity",
        0.04 + (1 - phase) * 0.2,
      );
      animationFrame = window.requestAnimationFrame(animate);
    };
    animationFrame = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [ready]);

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
      const source = map.getSource(id);
      if (source && "setData" in source) {
        (source as maplibregl.GeoJSONSource).setData(
          data as unknown as GeoJSON.FeatureCollection,
        );
      }
    });
  }, [collections, ready]);

  useEffect(() => {
    predictionPopupRef.current?.remove();
    predictionPopupRef.current = null;
  }, [worldState.world_state_version]);

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
  }, [ready, satellite]);

  /* ----------------------------------------------------------- 3D terrain */

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    if (map.getLayer(BUILDING_3D_LAYER_ID)) {
      map.setLayoutProperty(
        BUILDING_3D_LAYER_ID,
        "visibility",
        terrain3d ? "visible" : "none",
      );
    }

    if (terrain3d) {
      map.setTerrain({ source: TERRAIN_SOURCE_ID, exaggeration: 1.4 });
      map.setSky({
        "sky-color": "#0d1b2c",
        "horizon-color": "#1d3350",
        "fog-color": "#0a1420",
        "sky-horizon-blend": 0.6,
        "horizon-fog-blend": 0.5,
        "fog-ground-blend": 0.2,
      });
      map.easeTo({ pitch: 52, bearing: -18, duration: 900 });
    } else {
      map.setTerrain(null);
      map.easeTo({ pitch: 0, bearing: 0, duration: 700 });
    }
  }, [ready, terrain3d]);

  const resetView = useCallback(() => {
    mapRef.current?.fitBounds(scenarioBounds(bootstrap, worldState), {
      padding: FIT_PADDING,
      duration: 900,
    });
  }, [bootstrap, worldState]);

  const toggleLayer = (key: LayerKey) =>
    setLayers((current) => ({ ...current, [key]: !current[key] }));

  const eventActive = worldState.active_event_ids.length > 0;

  return (
    <section className="map-card maplibre-card" aria-label="Nakkhu River scenario map">
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
        <button
          className="map-dimension-toggle"
          type="button"
          onClick={() => setTerrain3d((enabled) => !enabled)}
          aria-label={`Switch to ${terrain3d ? "2D" : "3D"} map view`}
          aria-pressed={terrain3d}
          title={`Switch to ${terrain3d ? "2D" : "3D"} map view`}
        >
          <span className={!terrain3d ? "selected" : ""}>2D</span>
          <span className={terrain3d ? "selected" : ""}>3D</span>
        </button>
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

            <div className="layer-divider" />

            <label className="layer-toggle">
              <input
                checked={satellite}
                onChange={() => setSatellite((on) => !on)}
                type="checkbox"
              />
              <span className="layer-swatch satellite" aria-hidden="true" />
              Satellite imagery
            </label>
            <label className="layer-toggle">
              <input
                checked={terrain3d}
                onChange={() => setTerrain3d((on) => !on)}
                type="checkbox"
              />
              <span className="layer-swatch terrain" aria-hidden="true" />
              3D terrain & buildings
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

      <div className={`edge-inspector ${hovered ? "visible" : ""}`} role="status">
        {hovered ? (
          <>
            <strong>{hovered.edge_id}</strong>
            <span className={`inspector-status ${hovered.status}`}>{hovered.status}</span>
            <span>{hovered.flood_depth_m.toFixed(2)} m depth</span>
            <span>
              {hovered.effective_travel_minutes === null
                ? "impassable"
                : `${hovered.effective_travel_minutes} min`}
            </span>
            {hovered.critical ? <span className="inspector-critical">critical</span> : null}
          </>
        ) : (
          <span className="inspector-hint">Hover a road or bridge for derived state</span>
        )}
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
        Water is a scenario envelope; POI risk adjusts a shared event prior by local depth and time.
      </div>
    </section>
  );
}
