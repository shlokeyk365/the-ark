import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type {
  DerivedEdgeState,
  PlanResult,
  Position,
  PredictionSignal,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { ShellIcon } from "./ShellIcon";
import {
  BASE_W,
  DEFAULT_BASE_H,
  baseHeightFor,
  buildProjection,
  layoutLabels,
  smoothPath,
} from "./mapProjection";
import {
  floodForecastCollection,
  floodNowCollection,
  type MapFeatureCollection,
} from "../map/scenarioSources";

interface SchematicMapProps {
  bootstrap: ScenarioBootstrapResponse;
  worldState: WorldStateSnapshot;
  horizonState: WorldStateSnapshot | undefined;
  selectedPlan: PlanResult | undefined;
  focusedRouteEdgeIds?: string[];
  selectedAssetId: string | null;
  onSelectAsset: (assetId: string) => void;
}

interface Viewport {
  x: number;
  y: number;
  w: number;
  h: number;
}

const MAX_ZOOM = 6;

/**
 * Illustrative channel centreline. The river itself carries no derived state:
 * it orients the two banks that the bridges connect. The flood surface comes
 * from validated scenario polygons instead.
 */
const CHANNEL_CENTRELINE: Position[] = [
  [85.289, 27.688],
  [85.301, 27.685],
  [85.311, 27.686],
  [85.321, 27.689],
  [85.332, 27.687],
  [85.343, 27.688],
  [85.354, 27.682],
  [85.368, 27.684],
];

type LayerKey =
  | "context"
  | "inundation"
  | "network"
  | "route"
  | "predictions"
  | "labels";

const LAYER_LABELS: { key: LayerKey; label: string }[] = [
  { key: "context", label: "Administrative context" },
  { key: "inundation", label: "Modeled depth bands" },
  { key: "network", label: "Roads & bridges" },
  { key: "route", label: "Selected plan route" },
  { key: "predictions", label: "Model prediction pings" },
  { key: "labels", label: "Asset labels" },
];

function assetGlyph(assetType: string) {
  if (assetType === "hospital") return "+";
  if (assetType === "shelter") return "⌂";
  return "";
}

function assetKind(assetType: string) {
  if (assetType === "hospital") return "hospital";
  if (assetType === "shelter") return "shelter";
  return "community";
}

function niceScaleKm(pxPerKm: number) {
  const steps = [0.1, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20];
  return steps.find((step) => step * pxPerKm >= 72) ?? steps[steps.length - 1];
}

function depthClass(depthMaxM: number) {
  if (depthMaxM <= 0.1) return "depth-1";
  if (depthMaxM <= 0.2) return "depth-2";
  if (depthMaxM <= 0.3) return "depth-3";
  return "depth-4";
}

/**
 * Token-free fallback renderer: a self-contained SVG schematic of the same
 * derived state. Used when no Mapbox token is configured, or when the Mapbox
 * basemap fails to load.
 */
export function SchematicMap({
  bootstrap,
  worldState,
  horizonState,
  selectedPlan,
  focusedRouteEdgeIds,
  selectedAssetId,
  onSelectAsset,
}: SchematicMapProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const cardRef = useRef<HTMLElement | null>(null);
  const [baseH, setBaseH] = useState(DEFAULT_BASE_H);
  const [cardWidth, setCardWidth] = useState(0);
  const [view, setView] = useState<Viewport>({
    x: 0,
    y: 0,
    w: BASE_W,
    h: DEFAULT_BASE_H,
  });
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);
  const [hoveredFloodId, setHoveredFloodId] = useState<string | null>(null);
  const [selectedPredictionId, setSelectedPredictionId] = useState<string | null>(null);
  const [layersOpen, setLayersOpen] = useState(true);
  // Once the operator chooses, stop auto-collapsing on resize.
  const [layersPinned, setLayersPinned] = useState(false);
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    context: true,
    inundation: true,
    network: true,
    route: true,
    predictions: true,
    labels: true,
  });

  const zoom = BASE_W / view.w;
  const baseView: Viewport = { x: 0, y: 0, w: BASE_W, h: baseH };

  // Track the panel's aspect ratio so the SVG fills it instead of letterboxing.
  useLayoutEffect(() => {
    const element = cardRef.current;
    if (!element) return undefined;

    const measure = () => {
      const next = baseHeightFor(element.clientWidth, element.clientHeight);
      setBaseH((current) => (Math.abs(current - next) > 2 ? next : current));
      setCardWidth(element.clientWidth);
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (layersPinned || !cardWidth) return;
    setLayersOpen(cardWidth >= 700);
  }, [cardWidth, layersPinned]);

  // Keep the viewport consistent when the panel is resized.
  useEffect(() => {
    setView((current) => {
      const ratio = current.w / BASE_W;
      return { ...current, h: baseH * ratio, y: Math.min(current.y, baseH - baseH * ratio) };
    });
  }, [baseH]);

  const { project, pxPerKm } = useMemo(() => {
    const positions: Position[] = [];
    bootstrap.road_network.features.forEach((feature) => {
      positions.push(...feature.geometry.coordinates);
    });
    bootstrap.assets.features.forEach((feature) => {
      if (feature.geometry.type === "Point") {
        positions.push(feature.geometry.coordinates);
      }
    });
    worldState.prediction_signals.forEach((signal) => {
      positions.push(signal.geometry.coordinates);
    });
    bootstrap.flood_polygons.features.forEach((feature) => {
      feature.geometry.coordinates.forEach((ring) => positions.push(...ring));
    });
    return buildProjection(positions, baseH);
  }, [
    baseH,
    bootstrap.assets.features,
    bootstrap.flood_polygons.features,
    bootstrap.road_network.features,
    worldState.prediction_signals,
  ]);

  const edgeStateById = useMemo(
    () => new Map(worldState.edge_states.map((edge) => [edge.edge_id, edge])),
    [worldState.edge_states],
  );

  const selectedRouteEdges = useMemo(() => {
    if (focusedRouteEdgeIds?.length) return new Set(focusedRouteEdgeIds);
    const edgeIds = new Set<string>();
    selectedPlan?.assignment_results.forEach((assignment) => {
      assignment.route?.edge_ids.forEach((edgeId) => edgeIds.add(edgeId));
    });
    return edgeIds;
  }, [focusedRouteEdgeIds, selectedPlan]);

  const isolatedCommunities = useMemo(
    () =>
      new Set(
        worldState.community_access
          .filter((access) => access.isolated)
          .map((access) => access.community_id),
      ),
    [worldState.community_access],
  );

  const contextPaths = useMemo(
    () =>
      bootstrap.context_boundaries.features.map((feature) => ({
        id: feature.id,
        name: feature.properties.name,
        d: feature.geometry.coordinates
          .map(
            (ring) =>
              `${ring
                .map((position, index) => {
                  const point = project(position);
                  return `${index === 0 ? "M" : "L"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
                })
                .join(" ")} Z`,
          )
          .join(" "),
      })),
    [bootstrap.context_boundaries.features, project],
  );

  const channel = useMemo(
    () => smoothPath(CHANNEL_CENTRELINE.map((position) => project(position))),
    [project],
  );

  const floodBands = useMemo(() => {
    const projectCollection = (
      collection: MapFeatureCollection,
      displayState: "current" | "forecast",
    ) =>
      collection.features.map((feature) => ({
        id: String(feature.id),
        label: String(feature.properties.band_label),
        simulationTimeHours: Number(feature.properties.requested_time_hours),
        keyframeTimeHours: Number(feature.properties.keyframe_time_hours),
        interpolated: Boolean(feature.properties.interpolated),
        displayState,
        opacity: Number(feature.properties.frame_weight ?? 1),
        depthClass: depthClass(Number(feature.properties.depth_max_m)),
        d:
          feature.geometry.type === "Polygon"
            ? feature.geometry.coordinates
                .map(
                  (ring) =>
                    `${ring
                      .map((position, index) => {
                        const point = project(position);
                        return `${index === 0 ? "M" : "L"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
                      })
                      .join(" ")} Z`,
                )
                .join(" ")
            : "",
      }));

    const current = projectCollection(
      floodNowCollection(bootstrap, worldState),
      "current",
    );
    const forecast = projectCollection(
      floodForecastCollection(bootstrap, worldState, horizonState),
      "forecast",
    );
    return {
      current,
      forecast,
      byId: new Map([...forecast, ...current].map((band) => [band.id, band])),
    };
  }, [bootstrap, horizonState, project, worldState]);

  const edges = useMemo(
    () =>
      bootstrap.road_network.features.map((feature) => {
        const state = edgeStateById.get(feature.id);
        const projected = feature.geometry.coordinates.map(project);
        const points = projected
          .map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`)
          .join(" ");
        const midpoint = projected[Math.floor(projected.length / 2)] ?? projected[0];
        return {
          id: feature.id,
          edgeType: feature.properties.edge_type,
          state,
          points,
          midpoint,
        };
      }),
    [bootstrap.road_network.features, edgeStateById, project],
  );

  const assets = useMemo(
    () =>
      bootstrap.assets.features
        .filter((feature) => feature.geometry.type === "Point")
        .map((feature) => ({
          id: feature.id,
          name: feature.properties.name,
          kind: assetKind(feature.properties.asset_type),
          assetType: feature.properties.asset_type,
          point: project(feature.geometry.coordinates as Position),
        })),
    [bootstrap.assets.features, project],
  );

  const predictionSignals = useMemo(
    () =>
      worldState.prediction_signals.map((signal) => ({
        ...signal,
        point: project(signal.geometry.coordinates),
      })),
    [project, worldState.prediction_signals],
  );
  const selectedPrediction: PredictionSignal | undefined = selectedPredictionId
    ? worldState.prediction_signals.find(
        (signal) => signal.ping_id === selectedPredictionId,
      )
    : undefined;

  useEffect(() => {
    setSelectedPredictionId(null);
  }, [worldState.world_state_version]);

  /**
   * The floating map chrome sits above the SVG, so its footprint is reserved
   * before labels are placed. Positions mirror the CSS, converted from screen
   * pixels into base-canvas units.
   */
  const reservedRegions = useMemo(() => {
    if (!cardWidth) return [];
    const unit = BASE_W / cardWidth;
    const cardHeight = baseH / unit;
    const box = (x: number, y: number, width: number, height: number) => ({
      x: x * unit,
      y: y * unit,
      width: width * unit,
      height: height * unit,
    });

    return [
      box(6, 6, 360, 36), // status chips
      box(cardWidth - 208, 6, 202, layersOpen ? 230 : 40), // layers panel
      box(cardWidth - 48, cardHeight - 108, 42, 102), // zoom + compass
      box(8, cardHeight - 46, 160, 40), // scale bar
    ];
  }, [baseH, cardWidth, layersOpen]);

  const labelBoxes = useMemo(
    () =>
      layoutLabels(
        assets.map((asset) => ({
          id: asset.id,
          anchor: asset.point,
          text: asset.name,
          radius: asset.kind === "community" ? 11 : 16,
        })),
        baseH,
        reservedRegions,
      ),
    [assets, baseH, reservedRegions],
  );

  const clampView = useCallback(
    (next: Viewport): Viewport => {
      const w = Math.min(BASE_W, Math.max(BASE_W / MAX_ZOOM, next.w));
      const h = (w / BASE_W) * baseH;
      return {
        w,
        h,
        x: Math.min(Math.max(0, next.x), BASE_W - w),
        y: Math.min(Math.max(0, next.y), baseH - h),
      };
    },
    [baseH],
  );

  const zoomAt = useCallback(
    (factor: number, focusX: number, focusY: number) => {
      setView((current) => {
        const w = current.w / factor;
        const clamped = Math.min(BASE_W, Math.max(BASE_W / MAX_ZOOM, w));
        const ratio = clamped / current.w;
        return clampView({
          w: clamped,
          h: (clamped / BASE_W) * baseH,
          x: focusX - (focusX - current.x) * ratio,
          y: focusY - (focusY - current.y) * ratio,
        });
      });
    },
    [baseH, clampView],
  );

  const toBaseCoords = useCallback(
    (clientX: number, clientY: number) => {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return { x: view.x + view.w / 2, y: view.y + view.h / 2 };
      return {
        x: view.x + ((clientX - rect.left) / rect.width) * view.w,
        y: view.y + ((clientY - rect.top) / rect.height) * view.h,
      };
    },
    [view],
  );

  // Registered manually so the wheel listener can be non-passive.
  useEffect(() => {
    const element = svgRef.current;
    if (!element) return undefined;

    const onWheel = (nativeEvent: WheelEvent) => {
      nativeEvent.preventDefault();
      const rect = element.getBoundingClientRect();
      const focusX = view.x + ((nativeEvent.clientX - rect.left) / rect.width) * view.w;
      const focusY = view.y + ((nativeEvent.clientY - rect.top) / rect.height) * view.h;
      zoomAt(nativeEvent.deltaY < 0 ? 1.18 : 1 / 1.18, focusX, focusY);
    };

    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [view, zoomAt]);

  const dragState = useRef<{ pointerId: number; x: number; y: number } | null>(null);

  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (zoom <= 1.001) return;
    dragState.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const drag = dragState.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const dx = ((event.clientX - drag.x) / rect.width) * view.w;
    const dy = ((event.clientY - drag.y) / rect.height) * view.h;
    dragState.current = { ...drag, x: event.clientX, y: event.clientY };
    setView((current) => clampView({ ...current, x: current.x - dx, y: current.y - dy }));
  };

  const endDrag = (event: React.PointerEvent<SVGSVGElement>) => {
    if (dragState.current?.pointerId === event.pointerId) {
      dragState.current = null;
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const toggleLayer = (key: LayerKey) =>
    setLayers((current) => ({ ...current, [key]: !current[key] }));

  const toggleLayersPanel = () => {
    setLayersPinned(true);
    setLayersOpen((open) => !open);
  };

  const hoveredEdge: DerivedEdgeState | undefined = hoveredEdgeId
    ? edgeStateById.get(hoveredEdgeId)
    : undefined;
  const hoveredFlood = hoveredFloodId
    ? floodBands.byId.get(hoveredFloodId)
    : undefined;

  // The bar is an HTML overlay, so the scale must be in CSS pixels rather
  // than base-canvas units or the stated distance is wrong.
  const screenPxPerKm =
    pxPerKm * zoom * (cardWidth ? cardWidth / BASE_W : 1);
  const scaleKm = niceScaleKm(screenPxPerKm);
  const scalePx = scaleKm * screenPxPerKm;
  const counter = 1 / zoom;
  const eventActive = worldState.active_event_ids.length > 0;

  return (
    <section
      className="map-card schematic-card"
      ref={cardRef}
      aria-label="Nakkhu River scenario map (schematic)"
    >
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
          onClick={toggleLayersPanel}
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
            {LAYER_LABELS.map((layer) => (
              <label className="layer-toggle" key={layer.key}>
                <input
                  checked={layers[layer.key]}
                  onChange={() => toggleLayer(layer.key)}
                  type="checkbox"
                />
                <span className={`layer-swatch ${layer.key}`} aria-hidden="true" />
                {layer.label}
              </label>
            ))}
            <div className="layer-divider" />
            <div className="layer-key">
              <span><i className="key-line open" /> Open</span>
              <span><i className="key-line restricted" /> Restricted</span>
              <span><i className="key-line closed" /> Closed</span>
            </div>
          </div>
        ) : null}
      </div>

      <svg
        className={`scenario-map ${zoom > 1.001 ? "pannable" : ""}`}
        ref={svgRef}
        preserveAspectRatio="xMidYMid slice"
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        role="img"
        aria-labelledby="map-title map-description"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <title id="map-title">Nakkhu River infrastructure and model-risk status</title>
        <desc id="map-description">
          Synthetic road network over Kathmandu and Lalitpur administrative
          context, showing communities, bridges, shelters, a hospital, modeled
          inundation, current closures, the selected response plan route, and
          event-level impact-model prediction pings.
        </desc>

        <defs>
          <linearGradient id="terrain" x1="0" y1="0" x2="0.4" y2="1">
            <stop offset="0" stopColor="#202729" />
            <stop offset="0.55" stopColor="#181e20" />
            <stop offset="1" stopColor="#121718" />
          </linearGradient>
          <filter id="soft-blur" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="14" />
          </filter>
          <filter id="route-glow" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="3.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <pattern id="grid" width="60" height="60" patternUnits="userSpaceOnUse">
            <path
              d="M60 0H0V60"
              fill="none"
              stroke="#8c9793"
              strokeOpacity="0.045"
              strokeWidth="1"
            />
          </pattern>
        </defs>

        <rect x="-600" y="-400" width="2400" height="1560" fill="url(#terrain)" />
        <g className="terrain-relief" aria-hidden="true" filter="url(#soft-blur)">
          <ellipse
            cx="140"
            cy={baseH * 0.12}
            rx="330"
            ry={baseH * 0.24}
            fill="#2c3435"
            opacity="0.4"
          />
          <ellipse
            cx="1075"
            cy={baseH * 0.18}
            rx="300"
            ry={baseH * 0.22}
            fill="#293132"
            opacity="0.34"
          />
          <ellipse
            cx="235"
            cy={baseH * 0.92}
            rx="340"
            ry={baseH * 0.24}
            fill="#282f30"
            opacity="0.36"
          />
          <ellipse
            cx="1005"
            cy={baseH * 0.95}
            rx="320"
            ry={baseH * 0.23}
            fill="#252c2d"
            opacity="0.32"
          />
        </g>
        <rect x="-600" y="-400" width="2400" height="1560" fill="url(#grid)" />

        {layers.context ? (
          <g className="context-layer">
            {contextPaths.map((boundary) => (
              <path className="context-boundary" d={boundary.d} key={boundary.id} />
            ))}
          </g>
        ) : null}

        {layers.inundation ? (
          <g className="flood-layer" key={worldState.frame_id}>
            {floodBands.forecast.map((band) => (
              <path
                className={`flood-depth-band forecast ${band.depthClass}`}
                d={band.d}
                key={band.id}
                style={{ opacity: band.opacity }}
                onMouseEnter={() => {
                  setHoveredEdgeId(null);
                  setHoveredFloodId(band.id);
                }}
                onMouseLeave={() =>
                  setHoveredFloodId((current) => (current === band.id ? null : current))
                }
              />
            ))}
            {floodBands.current.map((band) => (
              <path
                className={`flood-depth-band current ${band.depthClass}`}
                d={band.d}
                key={band.id}
                style={{ opacity: band.opacity }}
                onMouseEnter={() => {
                  setHoveredEdgeId(null);
                  setHoveredFloodId(band.id);
                }}
                onMouseLeave={() =>
                  setHoveredFloodId((current) => (current === band.id ? null : current))
                }
              />
            ))}
            <path className="river-centreline" d={channel} />
            <path className="river-flow river-flow-a" d={channel} />
            <path className="river-flow river-flow-b" d={channel} />
          </g>
        ) : null}

        {layers.network ? (
          <g className="depth-layer" aria-hidden="true">
            {edges.map((edge) =>
              edge.state && edge.state.flood_depth_m > 0 ? (
                <polyline
                  className="depth-halo"
                  key={`depth-${edge.id}`}
                  points={edge.points}
                  strokeWidth={5 + edge.state.flood_depth_m * 52}
                  strokeOpacity={0.1 + Math.min(0.34, edge.state.flood_depth_m * 0.9)}
                />
              ) : null,
            )}
          </g>
        ) : null}

        {layers.network ? (
          <g className="road-network">
            {edges.map((edge) => {
              const status = edge.state?.status ?? "open";
              const onRoute = layers.route && selectedRouteEdges.has(edge.id);
              const selected = edge.id === selectedAssetId;
              return (
                <g
                  key={edge.id}
                  className={`road-group ${hoveredEdgeId === edge.id ? "hovered" : ""}`}
                  onMouseEnter={() => {
                    setHoveredFloodId(null);
                    setHoveredEdgeId(edge.id);
                  }}
                  onMouseLeave={() =>
                    setHoveredEdgeId((current) => (current === edge.id ? null : current))
                  }
                  onClick={() => onSelectAsset(edge.id)}
                >
                  <polyline className="road-hit" points={edge.points} />
                  <polyline className="road-casing" points={edge.points} />
                  <polyline
                    className={`road-edge ${status} ${edge.edgeType} ${onRoute ? "selected" : ""} ${selected ? "asset-selected" : ""}`}
                    points={edge.points}
                    filter={onRoute ? "url(#route-glow)" : undefined}
                  />
                  {status === "closed" ? (
                    <g
                      className="closure-badge"
                      transform={`translate(${edge.midpoint.x} ${edge.midpoint.y}) scale(${counter})`}
                    >
                      <circle r="11" />
                      <path d="m-4.5 -4.5 9 9M4.5 -4.5l-9 9" />
                    </g>
                  ) : null}
                  {edge.edgeType === "bridge" && status !== "closed" ? (
                    <g
                      className="bridge-badge"
                      transform={`translate(${edge.midpoint.x} ${edge.midpoint.y}) scale(${counter})`}
                    >
                      <rect x="-9" y="-9" width="18" height="18" rx="5" />
                      <path d="M-5 1h10M-5 1v4M5 1v4M-5 1c2.5 0 3-4 5-4s2.5 4 5 4" />
                    </g>
                  ) : null}
                </g>
              );
            })}
          </g>
        ) : null}

        <g className="asset-layer">
          {assets.map((asset) => {
            const isolated = isolatedCommunities.has(asset.id);
            const box = labelBoxes.get(asset.id);
            return (
              <g
                className={`asset-marker ${asset.kind} ${isolated ? "isolated" : ""} ${selectedAssetId === asset.id ? "selected" : ""}`}
                key={asset.id}
                onClick={() => onSelectAsset(asset.id)}
              >
                <g transform={`translate(${asset.point.x} ${asset.point.y}) scale(${counter})`}>
                  {isolated ? <circle className="isolation-ring" r="23" /> : null}
                  {selectedAssetId === asset.id ? <circle className="asset-selection-ring" r="22" /> : null}
                  <circle className="asset-dot" r={asset.kind === "community" ? 8.5 : 13} />
                  {assetGlyph(asset.assetType) ? (
                    <text className="asset-glyph" textAnchor="middle" y={5}>
                      {assetGlyph(asset.assetType)}
                    </text>
                  ) : null}
                </g>
                {layers.labels && box ? (
                  <g
                    transform={`translate(${asset.point.x} ${asset.point.y}) scale(${counter}) translate(${box.x - asset.point.x} ${box.y - asset.point.y})`}
                  >
                    <text className="asset-label" x={0} y={13}>
                      {asset.name}
                    </text>
                  </g>
                ) : null}
              </g>
            );
          })}
        </g>

        {layers.predictions ? (
          <g className="prediction-layer">
            {predictionSignals.map((signal) => {
              const labelLeft = signal.point.x > BASE_W / 2;
              const labelBelow = signal.point.y < 72;
              const labelX = labelLeft ? -142 : 20;
              const labelY = labelBelow ? 19 : -48;
              return (
                <g
                  className={`prediction-ping ${signal.target} ${signal.state}`}
                  key={signal.ping_id}
                  role="button"
                  tabIndex={0}
                  aria-label={`Priority ${signal.priority_rank}, ${signal.label}: ${signal.percent}% localized risk score, ${signal.state}`}
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={() => setSelectedPredictionId(signal.ping_id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedPredictionId(signal.ping_id);
                    }
                  }}
                >
                  <g
                    transform={`translate(${signal.point.x} ${signal.point.y}) scale(${counter})`}
                  >
                    <circle className="prediction-ring prediction-ring-outer" r="28" />
                    <circle className="prediction-ring prediction-ring-inner" r="19" />
                    <circle
                      className="prediction-core"
                      r={7 + signal.priority_score * 0.05}
                    />
                    <text className="prediction-mark" textAnchor="middle" y="4">
                      !
                    </text>
                  </g>
                  {selectedPredictionId === signal.ping_id ? (
                    <g
                      className="prediction-label-card"
                      transform={`translate(${signal.point.x} ${signal.point.y}) scale(${counter}) translate(${labelX} ${labelY})`}
                    >
                      <rect width="122" height="36" rx="6" />
                      <text className="prediction-label" x="9" y="14">
                        #{signal.priority_rank} {signal.short_label}
                      </text>
                      <text className="prediction-percent" x="9" y="29">
                        {signal.percent}% predicted
                      </text>
                    </g>
                  ) : null}
                </g>
              );
            })}
          </g>
        ) : null}
      </svg>

      {selectedPrediction ? (
        <div className="schematic-prediction-popup prediction-popup-card" role="dialog">
          <button
            className="schematic-prediction-close"
            type="button"
            aria-label="Close prediction details"
            onClick={() => setSelectedPredictionId(null)}
          >
            ×
          </button>
          <div className="prediction-popup-heading">
            <strong>{selectedPrediction.label}</strong>
            <span className={`priority-${selectedPrediction.priority_level}`}>
              #{selectedPrediction.priority_rank} {selectedPrediction.priority_level}
            </span>
          </div>
          <div className="prediction-popup-risk">
            <strong>{selectedPrediction.percent}%</strong>
            <span>localized risk score</span>
          </div>
          <div className="prediction-popup-metrics">
            <span>Event prior {selectedPrediction.base_percent}%</span>
            <span>Nearby depth {selectedPrediction.local_flood_depth_m.toFixed(2)} m</span>
            <span>{selectedPrediction.exposed_people.toLocaleString()} people nearby</span>
          </div>
          <small>Why this ping</small>
          <p>{selectedPrediction.reason}</p>
          <small>Recommended action</small>
          <p className="prediction-popup-action">{selectedPrediction.recommended_action}</p>
        </div>
      ) : null}

      {layers.context ? (
        <div className="context-credit">
          Context: Kathmandu &amp; Lalitpur Metropolitan City · MIT, nepal-geojson
        </div>
      ) : null}

      <div className="map-controls">
        <button
          type="button"
          aria-label="Zoom in"
          onClick={() => zoomAt(1.4, view.x + view.w / 2, view.y + view.h / 2)}
        >
          <ShellIcon name="plus" />
        </button>
        <button
          type="button"
          aria-label="Zoom out"
          onClick={() => zoomAt(1 / 1.4, view.x + view.w / 2, view.y + view.h / 2)}
        >
          <ShellIcon name="minus" />
        </button>
        <button
          type="button"
          aria-label="Reset map view"
          onClick={() => setView(baseView)}
          disabled={zoom <= 1.001}
        >
          <ShellIcon name="crosshair" />
        </button>
      </div>

      <div className="map-compass" aria-hidden="true">
        <ShellIcon name="compass" size={15} />
        <span>N</span>
      </div>

      <div className="map-scale" aria-label={`Scale bar, ${scaleKm} kilometres`}>
        <i style={{ width: `${Math.round(scalePx)}px` }} />
        <span>{scaleKm < 1 ? `${scaleKm * 1000} m` : `${scaleKm} km`}</span>
      </div>

      <div
        className={`edge-inspector ${hoveredEdge || hoveredFlood ? "visible" : ""}`}
        role="status"
      >
        {hoveredEdge ? (
          <>
            <strong>{hoveredEdge.edge_id}</strong>
            <span className={`inspector-status ${hoveredEdge.status}`}>
              {hoveredEdge.status}
            </span>
            <span>{hoveredEdge.flood_depth_m.toFixed(2)} m depth</span>
            <span>
              {hoveredEdge.effective_travel_minutes === null
                ? "impassable"
                : `${hoveredEdge.effective_travel_minutes} min`}
            </span>
            {hoveredEdge.critical ? <span className="inspector-critical">critical</span> : null}
          </>
        ) : hoveredFlood ? (
          <>
            <strong>{hoveredFlood.label}</strong>
            <span className="inspector-status flood">{hoveredFlood.displayState}</span>
            <span>+{hoveredFlood.simulationTimeHours}h frame</span>
            {hoveredFlood.interpolated ? (
              <span>blended from +{hoveredFlood.keyframeTimeHours}h</span>
            ) : null}
            <span>curated synthetic surface</span>
          </>
        ) : (
          <span className="inspector-hint">Hover a depth band, road, or bridge</span>
        )}
      </div>

      <div className="flood-legend" aria-label="Modeled flood depth legend">
        <strong>Modeled depth</strong>
        <span><i className="depth-1" />0–0.10 m</span>
        <span><i className="depth-2" />0.10–0.20 m</span>
        <span><i className="depth-3" />0.20–0.30 m</span>
        <span><i className="depth-4" />0.30–0.50 m</span>
        <span className="forecast-key"><i />24h extent</span>
      </div>
      <div className="map-provenance">
        Curated synthetic depth surface · not a hydraulic solve or operational forecast · POI risk uses local depth and time.
      </div>
    </section>
  );
}
