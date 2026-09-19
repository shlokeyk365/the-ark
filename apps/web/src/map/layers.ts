import type { LayerSpecification } from "maplibre-gl";

/**
 * MapLibre layer stack for the Kantipur operations map.
 *
 * Order here is paint order (first = bottom). The layer-panel grouping below
 * mirrors the operator-facing list, which is deliberately coarser: one toggle
 * can drive several paint layers.
 */

export const SOURCE = {
  context: "ark-context",
  floodForecast: "ark-flood-forecast",
  floodNow: "ark-flood-now",
  channel: "ark-channel",
  roads: "ark-roads",
  route: "ark-route",
  assets: "ark-assets",
  bridges: "ark-bridges",
  hazards: "ark-hazards",
} as const;

export const COLORS = {
  open: "#aab8b2",
  restricted: "#a8967f",
  closed: "#b8797f",
  route: "#9aabb9",
  water: "#657d91",
  forecast: "#7f8f9d",
  hospital: "#b8797f",
  shelter: "#869b8c",
  community: "#d3d4cf",
  isolated: "#b8797f",
  context: "#77828a",
} as const;

const isBridge = ["==", ["get", "edge_type"], "bridge"];

/** Road width in screen pixels, wider for bridges, scaled by zoom. */
const roadWidth = (base: number, bridge: number): unknown => [
  "interpolate",
  ["linear"],
  ["zoom"],
  11,
  ["case", isBridge, bridge * 0.45, base * 0.45],
  14,
  ["case", isBridge, bridge, base],
  17,
  ["case", isBridge, bridge * 2.2, base * 2.2],
];

export const LAYERS: LayerSpecification[] = [
  {
    id: "ark-context-fill",
    type: "fill",
    source: SOURCE.context,
    paint: { "fill-color": COLORS.context, "fill-opacity": 0.05 },
  },
  {
    id: "ark-context-line",
    type: "line",
    source: SOURCE.context,
    paint: {
      "line-color": COLORS.context,
      "line-width": 1.4,
      "line-opacity": 0.5,
      "line-dasharray": [4, 3],
    },
  },

  {
    id: "ark-flood-forecast-fill",
    type: "fill",
    source: SOURCE.floodForecast,
    paint: { "fill-color": COLORS.forecast, "fill-opacity": 0.1 },
  },
  {
    id: "ark-flood-forecast-line",
    type: "line",
    source: SOURCE.floodForecast,
    paint: {
      "line-color": COLORS.forecast,
      "line-width": 1.2,
      "line-opacity": 0.72,
      "line-dasharray": [3, 2],
    },
  },

  {
    id: "ark-flood-now-fill",
    type: "fill",
    source: SOURCE.floodNow,
    paint: { "fill-color": COLORS.water, "fill-opacity": 0.25 },
  },
  {
    id: "ark-flood-now-line",
    type: "line",
    source: SOURCE.floodNow,
    paint: { "line-color": "#a5b4bf", "line-width": 1.1, "line-opacity": 0.62 },
  },
  {
    id: "ark-channel-line",
    type: "line",
    source: SOURCE.channel,
    paint: { "line-color": "#a9b9c3", "line-width": 1, "line-opacity": 0.36 },
  },

  // Depth read directly off each edge — this part is model output, not an envelope.
  {
    id: "ark-depth-halo",
    type: "line",
    source: SOURCE.roads,
    filter: [">", ["get", "flood_depth_m"], 0],
    layout: { "line-cap": "round" },
    paint: {
      "line-color": "#738b9d",
      "line-blur": 5,
      "line-opacity": 0.24,
      "line-width": [
        "interpolate",
        ["linear"],
        ["zoom"],
        11,
        ["*", ["get", "flood_depth_m"], 26],
        16,
        ["*", ["get", "flood_depth_m"], 120],
      ],
    },
  },

  {
    id: "ark-roads-casing",
    type: "line",
    source: SOURCE.roads,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": "#101315",
      "line-opacity": 0.8,
      "line-width": roadWidth(7, 11) as never,
    },
  },
  {
    id: "ark-roads-open",
    type: "line",
    source: SOURCE.roads,
    filter: ["==", ["get", "status"], "open"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": COLORS.open, "line-width": roadWidth(3.6, 6.5) as never },
  },
  {
    id: "ark-roads-restricted",
    type: "line",
    source: SOURCE.roads,
    filter: ["==", ["get", "status"], "restricted"],
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": COLORS.restricted,
      "line-width": roadWidth(3.6, 6.5) as never,
      "line-dasharray": [2, 1.4],
    },
  },
  {
    id: "ark-roads-closed",
    type: "line",
    source: SOURCE.roads,
    filter: ["==", ["get", "status"], "closed"],
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": COLORS.closed,
      "line-width": roadWidth(3.6, 6.5) as never,
      "line-dasharray": [1, 1.5],
    },
  },
  {
    id: "ark-selected-road",
    type: "line",
    source: SOURCE.roads,
    filter: ["==", ["get", "selected"], true],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": "#e0ded7",
      "line-width": roadWidth(7.5, 12) as never,
      "line-opacity": 0.85,
      "line-blur": 1.5,
    },
  },

  {
    id: "ark-route-glow",
    type: "line",
    source: SOURCE.route,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": COLORS.route,
      "line-width": 8,
      "line-blur": 9,
      "line-opacity": 0.18,
    },
  },
  {
    id: "ark-route-line",
    type: "line",
    source: SOURCE.route,
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": COLORS.route,
      "line-width": 2.2,
      "line-dasharray": [1.2, 1.4],
    },
  },

  {
    id: "ark-bridges-marker",
    type: "circle",
    source: SOURCE.bridges,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 3.5, 16, 8],
      "circle-color": [
        "match",
        ["get", "status"],
        "closed",
        COLORS.closed,
        "restricted",
        COLORS.restricted,
        "#242b2d",
      ],
      "circle-stroke-color": "#d0d2cd",
      "circle-stroke-width": 1.6,
    },
  },
  {
    id: "ark-selected-bridge",
    type: "circle",
    source: SOURCE.bridges,
    filter: ["==", ["get", "selected"], true],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 8, 16, 16],
      "circle-color": "rgba(0, 0, 0, 0)",
      "circle-stroke-color": "#e4e1d8",
      "circle-stroke-width": 2,
      "circle-stroke-opacity": 0.95,
    },
  },

  {
    id: "ark-assets-halo",
    type: "circle",
    source: SOURCE.assets,
    filter: ["==", ["get", "isolated"], true],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 14, 16, 34],
      "circle-color": COLORS.isolated,
      "circle-opacity": 0.18,
      "circle-stroke-color": COLORS.isolated,
      "circle-stroke-width": 1.5,
      "circle-stroke-opacity": 0.7,
    },
  },
  {
    id: "ark-assets-risk-ring",
    type: "circle",
    source: SOURCE.assets,
    filter: ["==", ["get", "asset_type"], "community"],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 18, 16, 48],
      "circle-color": "rgba(0,0,0,0)",
      "circle-stroke-color": [
        "case",
        ["==", ["get", "isolated"], true],
        COLORS.isolated,
        "#89989a",
      ],
      "circle-stroke-width": 1,
      "circle-stroke-opacity": ["case", ["==", ["get", "isolated"], true], 0.7, 0.28],
    },
  },
  {
    id: "ark-assets-circle",
    type: "circle",
    source: SOURCE.assets,
    paint: {
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["zoom"],
        11,
        ["case", ["==", ["get", "asset_type"], "community"], 4.5, 6],
        16,
        ["case", ["==", ["get", "asset_type"], "community"], 9, 13],
      ],
      "circle-color": [
        "case",
        ["==", ["get", "isolated"], true],
        COLORS.isolated,
        [
          "match",
          ["get", "asset_type"],
          "hospital",
          COLORS.hospital,
          "shelter",
          COLORS.shelter,
          COLORS.community,
        ],
      ],
      "circle-stroke-color": "#171b1c",
      "circle-stroke-width": 2,
    },
  },
  {
    id: "ark-selected-asset",
    type: "circle",
    source: SOURCE.assets,
    filter: ["==", ["get", "selected"], true],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 10, 16, 20],
      "circle-color": "rgba(0, 0, 0, 0)",
      "circle-stroke-color": "#e4e1d8",
      "circle-stroke-width": 2,
      "circle-stroke-opacity": 0.95,
    },
  },
  {
    id: "ark-assets-glyph",
    type: "symbol",
    source: SOURCE.assets,
    minzoom: 12,
    filter: ["in", ["get", "asset_type"], ["literal", ["hospital", "shelter"]]],
    layout: {
      "text-field": ["case", ["==", ["get", "asset_type"], "hospital"], "H", "S"],
      "text-font": ["Noto Sans Medium"],
      "text-size": 11,
      "text-allow-overlap": true,
      "text-ignore-placement": true,
    },
    paint: { "text-color": "#f1eee7" },
  },

  {
    id: "ark-hazards",
    type: "symbol",
    source: SOURCE.hazards,
    layout: {
      "text-field": "!",
      "text-font": ["Noto Sans Medium"],
      "text-size": 13,
      "text-offset": [0, -1.5],
      "text-allow-overlap": true,
    },
    paint: {
      "text-color": [
        "match",
        ["get", "priority"],
        "critical",
        COLORS.closed,
        "high",
        COLORS.restricted,
        "#93a4ae",
      ],
      "text-halo-color": "#111416",
      "text-halo-width": 1.6,
    },
  },
  {
    id: "ark-hazard-labels",
    type: "symbol",
    source: SOURCE.hazards,
    layout: {
      "text-field": ["upcase", ["get", "priority"]],
      "text-font": ["Noto Sans Medium"],
      "text-size": 9,
      "text-offset": [1.1, -1.5],
      "text-anchor": "left",
      "text-allow-overlap": false,
    },
    paint: {
      "text-color": "#d1c9c5",
      "text-halo-color": "rgba(17,20,22,0.94)",
      "text-halo-width": 2,
    },
  },

  {
    id: "ark-bridge-labels",
    type: "symbol",
    source: SOURCE.bridges,
    minzoom: 11,
    layout: {
      "text-field": ["get", "name"],
      "text-font": ["Noto Sans Medium"],
      "text-size": 9,
      "text-offset": [0, -1.5],
      "text-anchor": "bottom",
      "text-optional": true,
    },
    paint: {
      "text-color": "#c8c8c2",
      "text-halo-color": "rgba(17,20,22,0.94)",
      "text-halo-width": 1.5,
    },
  },
  {
    id: "ark-road-labels",
    type: "symbol",
    source: SOURCE.roads,
    minzoom: 12,
    filter: ["any", ["==", ["get", "critical"], true], ["==", ["get", "selected"], true]],
    layout: {
      "symbol-placement": "line",
      "text-field": ["concat", ["get", "id"], "  ·  ", ["upcase", ["get", "status"]]],
      "text-font": ["Noto Sans Medium"],
      "text-size": 8,
      "text-letter-spacing": 0.08,
      "text-offset": [0, 0.9],
      "text-optional": true,
    },
    paint: {
      "text-color": "#aeb2ae",
      "text-halo-color": "rgba(17,20,22,0.94)",
      "text-halo-width": 1.6,
    },
  },

  {
    id: "ark-asset-labels",
    type: "symbol",
    source: SOURCE.assets,
    layout: {
      "text-field": ["get", "name"],
      "text-font": ["Noto Sans Medium"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 11, 10, 16, 14],
      "text-offset": [0, 1.4],
      "text-anchor": "top",
      "text-optional": true,
    },
    paint: {
      "text-color": "#deddd7",
      "text-halo-color": "rgba(17, 20, 22, 0.94)",
      "text-halo-width": 1.7,
    },
  },
];

/** Operator-facing toggles, in the order the panel lists them. */
export type LayerKey =
  | "context"
  | "floodNow"
  | "floodForecast"
  | "roads"
  | "route"
  | "facilities"
  | "bridges"
  | "gauges"
  | "alerts"
  | "labels";

export interface LayerControl {
  key: LayerKey;
  label: string;
  swatch: string;
  layerIds: string[];
  /** Set when the scenario has no data for this layer yet. */
  unavailable?: string;
}

export const LAYER_CONTROLS: LayerControl[] = [
  {
    key: "floodNow",
    label: "Flood inundation (now)",
    swatch: "flood-now",
    layerIds: ["ark-flood-now-fill", "ark-flood-now-line", "ark-channel-line", "ark-depth-halo"],
  },
  {
    key: "floodForecast",
    label: "Predicted inundation",
    swatch: "flood-forecast",
    layerIds: ["ark-flood-forecast-fill", "ark-flood-forecast-line"],
  },
  {
    key: "roads",
    label: "Roads",
    swatch: "roads",
    layerIds: [
      "ark-roads-casing",
      "ark-roads-open",
      "ark-roads-restricted",
      "ark-roads-closed",
      "ark-selected-road",
    ],
  },
  {
    key: "route",
    label: "Evacuation routes",
    swatch: "route",
    layerIds: ["ark-route-glow", "ark-route-line"],
  },
  {
    key: "facilities",
    label: "Hospitals & shelters",
    swatch: "facilities",
    layerIds: ["ark-assets-circle", "ark-assets-glyph", "ark-assets-halo", "ark-assets-risk-ring", "ark-selected-asset"],
  },
  {
    key: "bridges",
    label: "Bridges",
    swatch: "bridges",
    layerIds: ["ark-bridges-marker", "ark-selected-bridge", "ark-bridge-labels"],
  },
  {
    key: "gauges",
    label: "River gauges",
    swatch: "gauges",
    layerIds: [],
    unavailable: "No gauge observations in this scenario fixture yet.",
  },
  {
    key: "alerts",
    label: "Alerts",
    swatch: "alerts",
    layerIds: ["ark-hazards", "ark-hazard-labels"],
  },
  {
    key: "labels",
    label: "Community labels",
    swatch: "labels",
    layerIds: ["ark-asset-labels", "ark-road-labels"],
  },
  {
    key: "context",
    label: "Administrative context",
    swatch: "context",
    layerIds: ["ark-context-fill", "ark-context-line"],
  },
];

export const HOVERABLE_ROAD_LAYERS = [
  "ark-roads-open",
  "ark-roads-restricted",
  "ark-roads-closed",
];
