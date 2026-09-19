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
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { ShellIcon } from "./ShellIcon";
import {
  BASE_W,
  DEFAULT_BASE_H,
  baseHeightFor,
  buildProjection,
  kmToLatDegrees,
  layoutLabels,
  smoothPath,
} from "./mapProjection";

interface SchematicMapProps {
  bootstrap: ScenarioBootstrapResponse;
  worldState: WorldStateSnapshot;
  selectedPlan: PlanResult | undefined;
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
 * it orients the two banks that the bridges connect. Inundation width is the
 * only part driven by frame data.
 */
const CHANNEL_CENTRELINE: Position[] = [
  [85.262, 27.6955],
  [85.29, 27.6884],
  [85.317, 27.6906],
  [85.334, 27.6872],
  [85.352, 27.6913],
  [85.378, 27.6858],
];

const CHANNEL_HALF_WIDTH_KM = 0.22;
/** Metres of depth to kilometres of modelled lateral spread. */
const SPREAD_KM_PER_METRE = 2.9;

type LayerKey =
  | "context"
  | "inundation"
  | "network"
  | "route"
  | "predictions"
  | "labels";

const LAYER_LABELS: { key: LayerKey; label: string }[] = [
  { key: "context", label: "Administrative context" },
  { key: "inundation", label: "Modeled inundation" },
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

/**
 * Token-free fallback renderer: a self-contained SVG schematic of the same
 * derived state. Used when no Mapbox token is configured, or when the Mapbox
 * basemap fails to load.
 */
export function SchematicMap({
  bootstrap,
  worldState,
  selectedPlan,
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
    return buildProjection(positions, baseH);
  }, [
    baseH,
    bootstrap.assets.features,
    bootstrap.road_network.features,
    worldState.prediction_signals,
  ]);

  const edgeStateById = useMemo(
    () => new Map(worldState.edge_states.map((edge) => [edge.edge_id, edge])),
    [worldState.edge_states],
  );

  const selectedRouteEdges = useMemo(() => {
    const edgeIds = new Set<string>();
    selectedPlan?.assignment_results.forEach((assignment) => {
      assignment.route?.edge_ids.forEach((edgeId) => edgeIds.add(edgeId));
    });
    return edgeIds;
  }, [selectedPlan]);

  const isolatedCommunities = useMemo(
    () =>
      new Set(
        worldState.community_access
          .filter((access) => access.isolated)
          .map((access) => access.community_id),
      ),
    [worldState.community_access],
  );

  const maxDepth = useMemo(
    () =>
      worldState.edge_states.reduce(
        (highest, edge) => Math.max(highest, edge.flood_depth_m),
        0,
      ),
    [worldState.edge_states],
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

  const channel = useMemo(() => {
    const band = (halfWidthKm: number) => {
      const offset = kmToLatDegrees(halfWidthKm);
      const north = CHANNEL_CENTRELINE.map(([longitude, latitude]) =>
        project([longitude, latitude + offset]),
      );
      const south = CHANNEL_CENTRELINE.map(([longitude, latitude]) =>
        project([longitude, latitude - offset]),
      ).reverse();
      return `${smoothPath(north)} ${smoothPath(south).replace(/^M/, "L")} Z`;
    };

    return {
      water: band(CHANNEL_HALF_WIDTH_KM),
      inundation: band(CHANNEL_HALF_WIDTH_KM + maxDepth * SPREAD_KM_PER_METRE),
      outer: band(CHANNEL_HALF_WIDTH_KM + maxDepth * SPREAD_KM_PER_METRE * 1.45),
      centreline: smoothPath(CHANNEL_CENTRELINE.map((position) => project(position))),
    };
  }, [maxDepth, project]);

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
            <stop offset="0" stopColor="#111d2b" />
            <stop offset="0.55" stopColor="#0d1825" />
            <stop offset="1" stopColor="#0a1420" />
          </linearGradient>
          <linearGradient id="water" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#1e7fd0" />
            <stop offset="0.5" stopColor="#2aa5ef" />
            <stop offset="1" stopColor="#1668b4" />
          </linearGradient>
          <linearGradient id="inundation" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#2b8fe0" stopOpacity="0.16" />
            <stop offset="0.5" stopColor="#38a9f5" stopOpacity="0.4" />
            <stop offset="1" stopColor="#2b8fe0" stopOpacity="0.16" />
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
              stroke="#6d8aa8"
              strokeOpacity="0.055"
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
            fill="#16283a"
            opacity="0.5"
          />
          <ellipse
            cx="1075"
            cy={baseH * 0.18}
            rx="300"
            ry={baseH * 0.22}
            fill="#16283a"
            opacity="0.42"
          />
          <ellipse
            cx="235"
            cy={baseH * 0.92}
            rx="340"
            ry={baseH * 0.24}
            fill="#152436"
            opacity="0.46"
          />
          <ellipse
            cx="1005"
            cy={baseH * 0.95}
            rx="320"
            ry={baseH * 0.23}
            fill="#152436"
            opacity="0.4"
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
          <g className="flood-layer" aria-hidden="true">
            <path className="flood-outer" d={channel.outer} />
            <path className="flood-band" d={channel.inundation} fill="url(#inundation)" />
            <path className="river-water" d={channel.water} fill="url(#water)" />
            <path className="river-centreline" d={channel.centreline} />
            <path className="river-flow river-flow-a" d={channel.centreline} />
            <path className="river-flow river-flow-b" d={channel.centreline} />
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
              const selected = layers.route && selectedRouteEdges.has(edge.id);
              return (
                <g
                  key={edge.id}
                  className={`road-group ${hoveredEdgeId === edge.id ? "hovered" : ""}`}
                  onMouseEnter={() => setHoveredEdgeId(edge.id)}
                  onMouseLeave={() =>
                    setHoveredEdgeId((current) => (current === edge.id ? null : current))
                  }
                >
                  <polyline className="road-hit" points={edge.points} />
                  <polyline className="road-casing" points={edge.points} />
                  <polyline
                    className={`road-edge ${status} ${edge.edgeType} ${selected ? "selected" : ""}`}
                    points={edge.points}
                    filter={selected ? "url(#route-glow)" : undefined}
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
              <g className={`asset-marker ${asset.kind} ${isolated ? "isolated" : ""}`} key={asset.id}>
                <g transform={`translate(${asset.point.x} ${asset.point.y}) scale(${counter})`}>
                  {isolated ? <circle className="isolation-ring" r="23" /> : null}
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
            {predictionSignals.map((signal, index) => {
              const labelLeft = index >= 2;
              const labelBelow = index === 1;
              const labelX = labelLeft ? -142 : 20;
              const labelY = labelBelow ? 19 : -48;
              return (
                <g
                  className={`prediction-ping ${signal.target} ${signal.state}`}
                  key={signal.ping_id}
                  role="img"
                  aria-label={`${signal.label}: ${signal.percent}% predicted risk, ${signal.state}`}
                >
                  <g
                    transform={`translate(${signal.point.x} ${signal.point.y}) scale(${counter})`}
                  >
                    <circle className="prediction-ring prediction-ring-outer" r="28" />
                    <circle className="prediction-ring prediction-ring-inner" r="19" />
                    <circle className="prediction-core" r="11" />
                    <text className="prediction-mark" textAnchor="middle" y="4">
                      !
                    </text>
                  </g>
                  <g
                    className="prediction-label-card"
                    transform={`translate(${signal.point.x} ${signal.point.y}) scale(${counter}) translate(${labelX} ${labelY})`}
                  >
                    <rect width="122" height="36" rx="6" />
                    <text className="prediction-label" x="9" y="14">
                      {signal.short_label}
                    </text>
                    <text className="prediction-percent" x="9" y="29">
                      {signal.percent}% predicted
                    </text>
                  </g>
                </g>
              );
            })}
          </g>
        ) : null}
      </svg>

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

      <div className={`edge-inspector ${hoveredEdge ? "visible" : ""}`} role="status">
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
        ) : (
          <span className="inspector-hint">Hover a road or bridge for derived state</span>
        )}
      </div>
      <div className="map-provenance">
        Water extent is a scenario envelope; pings are frozen event-level model predictions.
      </div>
    </section>
  );
}
