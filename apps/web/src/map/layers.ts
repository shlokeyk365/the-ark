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
  predictions: "ark-predictions",
} as const;

export const COLORS = {
  open: "#dce8f4",
  restricted: "#f0a52a",
  closed: "#f24d63",
  route: "#5fc4ff",
  water: "#2aa5ef",
  forecast: "#7d5cf0",
  hospital: "#e8536a",
  shelter: "#2eb277",
  community: "#eef5fc",
  isolated: "#f24d63",
  context: "#9dc4e8",
  casualty: "#f24d63",
  housing: "#f0a52a",
  transport: "#ffd05a",
  severe: "#a768f0",
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
    paint: { "fill-color": COLORS.forecast, "fill-opacity": 0.14 },
  },
  {
    id: "ark-flood-forecast-line",
    type: "line",
    source: SOURCE.floodForecast,
    paint: {
      "line-color": COLORS.forecast,
      "line-width": 1.2,
      "line-opacity": 0.55,
      "line-dasharray": [3, 2],
    },
  },

  {
    id: "ark-flood-now-fill",
    type: "fill",
    source: SOURCE.floodNow,
    paint: { "fill-color": COLORS.water, "fill-opacity": 0.32 },
  },
  {
    id: "ark-flood-now-line",
    type: "line",
    source: SOURCE.floodNow,
    paint: { "line-color": "#8ad6ff", "line-width": 1.4, "line-opacity": 0.7 },
  },
  {
    id: "ark-channel-line",
    type: "line",
    source: SOURCE.channel,
    paint: { "line-color": "#bfe8ff", "line-width": 1.2, "line-opacity": 0.45 },
  },
  {
    id: "ark-channel-flow-arrows",
    type: "symbol",
    source: SOURCE.channel,
    layout: {
      "symbol-placement": "line",
      "symbol-spacing": 72,
      "text-field": "›",
      "text-font": ["Noto Sans Medium"],
      "text-size": 18,
      "text-rotation-alignment": "map",
      "text-keep-upright": false,
      "text-allow-overlap": true,
    },
    paint: {
      "text-color": "#dff6ff",
      "text-opacity": 0.82,
      "text-halo-color": "rgba(25, 126, 194, 0.75)",
      "text-halo-width": 1.2,
    },
  },

  // Depth read directly off each edge — this part is model output, not an envelope.
  {
    id: "ark-depth-halo",
    type: "line",
    source: SOURCE.roads,
    filter: [">", ["get", "flood_depth_m"], 0],
    layout: { "line-cap": "round" },
    paint: {
      "line-color": "#49b6ff",
      "line-blur": 4,
      "line-opacity": 0.45,
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
      "line-color": "#050b12",
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
    id: "ark-route-glow",
    type: "line",
    source: SOURCE.route,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": COLORS.route,
      "line-width": 15,
      "line-blur": 11,
      "line-opacity": 0.4,
    },
  },
  {
    id: "ark-route-line",
    type: "line",
    source: SOURCE.route,
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": COLORS.route,
      "line-width": 3.4,
      "line-dasharray": [0.4, 1.6],
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
        "#0b1726",
      ],
      "circle-stroke-color": "#cddcea",
      "circle-stroke-width": 1.6,
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
      "circle-stroke-color": "#091421",
      "circle-stroke-width": 2,
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
    paint: { "text-color": "#ffffff" },
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
        "#7fc4ff",
      ],
      "text-halo-color": "#050b12",
      "text-halo-width": 1.6,
    },
  },

  {
    id: "ark-prediction-pulse",
    type: "circle",
    source: SOURCE.predictions,
    paint: {
      "circle-radius": 18,
      "circle-color": [
        "match",
        ["get", "target"],
        "casualty_or_missing",
        COLORS.casualty,
        "housing_damage",
        COLORS.housing,
        "transport_disruption",
        COLORS.transport,
        COLORS.severe,
      ],
      "circle-opacity": ["case", ["==", ["get", "state"], "active"], 0.22, 0.1],
      "circle-stroke-color": [
        "match",
        ["get", "target"],
        "casualty_or_missing",
        COLORS.casualty,
        "housing_damage",
        COLORS.housing,
        "transport_disruption",
        COLORS.transport,
        COLORS.severe,
      ],
      "circle-stroke-width": 1.5,
      "circle-stroke-opacity": 0.6,
    },
  },
  {
    id: "ark-prediction-ping",
    type: "circle",
    source: SOURCE.predictions,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 6, 16, 11],
      "circle-color": [
        "match",
        ["get", "target"],
        "casualty_or_missing",
        COLORS.casualty,
        "housing_damage",
        COLORS.housing,
        "transport_disruption",
        COLORS.transport,
        COLORS.severe,
      ],
      "circle-opacity": ["case", ["==", ["get", "state"], "active"], 1, 0.68],
      "circle-stroke-color": "#f7fbff",
      "circle-stroke-width": 1.5,
    },
  },
  {
    id: "ark-prediction-label",
    type: "symbol",
    source: SOURCE.predictions,
    layout: {
      "text-field": [
        "concat",
        ["get", "short_label"],
        " ",
        ["get", "percent_label"],
      ],
      "text-font": ["Noto Sans Medium"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 11, 9, 16, 12],
      "text-offset": [0, 1.8],
      "text-anchor": "top",
      "text-allow-overlap": true,
      "text-ignore-placement": true,
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "rgba(5, 11, 18, 0.96)",
      "text-halo-width": 2,
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
      "text-color": "#f1f7fc",
      "text-halo-color": "rgba(5, 11, 18, 0.92)",
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
  | "predictions"
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
    layerIds: [
      "ark-flood-now-fill",
      "ark-flood-now-line",
      "ark-channel-line",
      "ark-channel-flow-arrows",
      "ark-depth-halo",
    ],
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
    layerIds: ["ark-assets-circle", "ark-assets-glyph", "ark-assets-halo"],
  },
  {
    key: "bridges",
    label: "Bridges",
    swatch: "bridges",
    layerIds: ["ark-bridges-marker"],
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
    layerIds: ["ark-hazards"],
  },
  {
    key: "predictions",
    label: "Model prediction pings",
    swatch: "predictions",
    layerIds: [
      "ark-prediction-pulse",
      "ark-prediction-ping",
      "ark-prediction-label",
    ],
  },
  {
    key: "labels",
    label: "Community labels",
    swatch: "labels",
    layerIds: ["ark-asset-labels"],
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
