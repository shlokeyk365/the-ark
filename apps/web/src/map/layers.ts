import type { ExpressionSpecification, LayerSpecification } from "maplibre-gl";

/**
 * MapLibre layer stack for the Kantipur operations map.
 *
 * Order here is paint order (first = bottom), and the grouping follows the way
 * an operator reads the map: environment, then infrastructure, then operations,
 * then labels. The layer-panel list below is deliberately coarser — one toggle
 * usually drives several paint layers.
 *
 * Three conventions run through the whole stack:
 *
 * - **Shape is type, colour is status.** A shelter is a house whether it is
 *   reachable or not; the fill says which.
 * - **Solid is now, dashed is modeled.** Current flood extent, current routes
 *   and confirmed closures are solid. The +24h envelope and alternate plans are
 *   dashed. Operator-injected state is amber.
 * - **Hazards sit on the thing that is hazardous.** A blocked road is drawn on
 *   the road; a failed bridge is drawn on the span.
 *
 * Emphasis is carried by `feature-state` rather than by rebuilding sources, so
 * hover, selection and incident focus cost no GeoJSON churn.
 */

export const SOURCE = {
  context: "ark-context",
  floodForecast: "ark-flood-forecast",
  floodNow: "ark-flood-now",
  channel: "ark-channel",
  roads: "ark-roads",
  bridgeLines: "ark-bridge-lines",
  roadHazards: "ark-road-hazards",
  route: "ark-route",
  routeAlternate: "ark-route-alternate",
  teams: "ark-teams",
  assets: "ark-assets",
  bridges: "ark-bridges",
  hazards: "ark-hazards",
  predictions: "ark-predictions",
} as const;

export const COLORS = {
  open: "#b9cde0",
  restricted: "#f0a52a",
  closed: "#f24d63",
  route: "#5fc4ff",
  routeAlt: "#8ba0b8",
  water: "#2aa5ef",
  forecast: "#7d5cf0",
  hospital: "#e8536a",
  shelter: "#2eb277",
  community: "#eef5fc",
  isolated: "#f24d63",
  injected: "#f5b54a",
  context: "#9dc4e8",
  casing: "#040a12",
  /* Impact-prediction targets, from the CatBoost prior. */
  casualty: "#f24d63",
  housing: "#f0a52a",
  transport: "#ffd05a",
  severe: "#a768f0",
} as const;

export const CURRENT_FLOOD_OPACITY = 0.72;
export const FORECAST_FLOOD_OPACITY = 0.1;

const TEXT_HALO = "rgba(4, 9, 16, 0.92)";
const FONT_MEDIUM = ["Noto Sans Medium"];

/* ------------------------------------------------------------ emphasis */

/**
 * Fade a feature that is not part of the focused incident.
 *
 * `dim` is set on features outside the focus set; everything else keeps its
 * normal weight, so focus mode reads as "the rest recedes" rather than "the
 * selection glows".
 */
function dimmed(base: number, floor = 0.16): ExpressionSpecification {
  return [
    "case",
    ["boolean", ["feature-state", "dim"], false],
    base * floor,
    base,
  ] as ExpressionSpecification;
}

const isHovered: ExpressionSpecification = [
  "boolean",
  ["feature-state", "hover"],
  false,
];
const isSelected: ExpressionSpecification = [
  "boolean",
  ["feature-state", "selected"],
  false,
];

/**
 * Opacity for a selection/hover ring.
 *
 * Icons cannot respond to `feature-state` — MapLibre forbids it in layout
 * properties, and `icon-size` is layout — so emphasis on a point symbol is
 * carried by a ring drawn beneath it, which is paint and therefore can.
 */
function ringOpacity(selected: number, hovered: number): ExpressionSpecification {
  return [
    "case",
    isSelected,
    selected,
    isHovered,
    hovered,
    0,
  ] as ExpressionSpecification;
}

/**
 * One line of secondary label text, or nothing.
 *
 * `text-field` allows only a single zoom-based expression at the top level, so
 * the newline has to be added inside the branch rather than by nesting another
 * step.
 */
function labelLine(property: string): ExpressionSpecification {
  return [
    "case",
    ["==", ["get", property], ""],
    "",
    ["concat", "\n", ["get", property]],
  ] as ExpressionSpecification;
}

/** Widen a line on hover, wider still on selection. */
function emphasised(base: number, hover: number, selected: number): ExpressionSpecification {
  return [
    "case",
    isSelected,
    selected,
    isHovered,
    hover,
    base,
  ] as ExpressionSpecification;
}

/* --------------------------------------------------------------- flood */

/** Shared modeled-depth ramp. Forecast state is distinguished by opacity and outline. */
const floodDepthColor: ExpressionSpecification = [
  "step",
  ["get", "depth_max_m"],
  "#86c5e4",
  0.1,
  "#4e9ccd",
  0.2,
  "#2b6ca8",
  0.3,
  "#17427a",
];

/* --------------------------------------------------------------- roads */

const isBridge: ExpressionSpecification = ["==", ["get", "edge_type"], "bridge"];

/** Road width in screen pixels, wider for bridges, scaled by zoom. */
function roadWidth(base: number, bridge: number): ExpressionSpecification {
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    11,
    ["case", isBridge, bridge * 0.45, base * 0.45],
    14,
    ["case", isBridge, bridge, base],
    17,
    ["case", isBridge, bridge * 2.2, base * 2.2],
  ] as ExpressionSpecification;
}

export const LAYERS: LayerSpecification[] = [
  /* ============================================================ context */

  {
    id: "ark-context-fill",
    type: "fill",
    source: SOURCE.context,
    paint: { "fill-color": COLORS.context, "fill-opacity": 0.04 },
  },
  {
    id: "ark-context-line",
    type: "line",
    source: SOURCE.context,
    paint: {
      "line-color": COLORS.context,
      "line-width": 1.2,
      "line-opacity": 0.38,
      "line-dasharray": [4, 3],
    },
  },

  /* ====================================================== flood surface */

  // Modeled +24h envelope: translucent fill, dashed violet boundary.
  {
    id: "flood-modeled-fill",
    type: "fill",
    source: SOURCE.floodForecast,
    layout: { "fill-sort-key": ["get", "depth_min_m"] as never },
    paint: {
      "fill-color": floodDepthColor,
      "fill-opacity": FORECAST_FLOOD_OPACITY,
      "fill-opacity-transition": { duration: 320, delay: 0 },
    },
  },
  // Only the outermost band is outlined. Tracing all four produced a dense
  // violet crinkle around the water that read as damage rather than as a
  // forecast boundary.
  {
    id: "flood-modeled-outline",
    type: "line",
    source: SOURCE.floodForecast,
    filter: ["==", ["get", "depth_min_m"], 0],
    paint: {
      "line-color": COLORS.forecast,
      "line-width": 1.1,
      "line-opacity": 0.45,
      "line-dasharray": [3, 2.5],
    },
  },

  // Current extent: the dominant layer on the map. Shallow bands stay
  // translucent enough to read the road network through them.
  {
    id: "flood-current-fill",
    type: "fill",
    source: SOURCE.floodNow,
    layout: { "fill-sort-key": ["get", "depth_min_m"] as never },
    paint: {
      "fill-color": floodDepthColor,
      // Shallow water stays sheer enough to read the street grid through it;
      // deep water is where the fill is allowed to take over.
      "fill-opacity": [
        "interpolate",
        ["linear"],
        ["get", "depth_max_m"],
        0.1,
        0.34,
        0.3,
        0.58,
        0.5,
        0.72,
      ],
      "fill-opacity-transition": { duration: 320, delay: 0 },
    },
  },
  // A thin band boundary is what separates one depth from the next; without it
  // overlapping translucent fills read as a single smear.
  {
    id: "flood-current-outline",
    type: "line",
    source: SOURCE.floodNow,
    minzoom: 12.5,
    paint: {
      "line-color": floodDepthColor,
      "line-width": 0.8,
      "line-opacity": 0.4,
      "line-opacity-transition": { duration: 320, delay: 0 },
    },
  },

  {
    id: "ark-channel-line",
    type: "line",
    source: SOURCE.channel,
    paint: { "line-color": "#8fd4ff", "line-width": 1.1, "line-opacity": 0.35 },
  },
  // Downstream direction. Sparse and low-contrast: it should be noticed on a
  // second look, not compete with the depth bands.
  {
    id: "flood-flow-arrows",
    type: "symbol",
    source: SOURCE.channel,
    minzoom: 12,
    layout: {
      "icon-image": "ark-route-arrow-alt",
      "icon-size": 0.72,
      "symbol-placement": "line",
      "symbol-spacing": 120,
      "icon-rotation-alignment": "map",
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
    paint: { "icon-opacity": 0.42 },
  },

  /* ==================================================== infrastructure */

  // Standing water on the carriageway, read straight off the edge state. Kept
  // tight to the road rather than bloomed into a halo.
  {
    id: "roads-submerged",
    type: "line",
    source: SOURCE.roads,
    filter: ["==", ["get", "submerged"], true],
    layout: { "line-cap": "round" },
    paint: {
      "line-color": "#3aa9ef",
      "line-blur": 1.5,
      "line-opacity": dimmed(0.4),
      "line-width": [
        "interpolate",
        ["linear"],
        ["zoom"],
        11,
        ["min", ["*", ["get", "flood_depth_m"], 18], 9],
        16,
        ["min", ["*", ["get", "flood_depth_m"], 64], 30],
      ],
    },
  },

  {
    id: "roads-base-casing",
    type: "line",
    source: SOURCE.roads,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": COLORS.casing,
      "line-opacity": dimmed(0.85),
      "line-width": roadWidth(5.2, 8),
    },
  },
  {
    id: "roads-base",
    type: "line",
    source: SOURCE.roads,
    filter: ["==", ["get", "risk"], "clear"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": COLORS.open,
      "line-opacity": dimmed(0.92),
      "line-width": roadWidth(2.5, 4.4),
    },
  },

  // Affected segments get a heavier casing so the hazard reads as a property of
  // the road, not as something drawn near it.
  {
    id: "roads-affected-casing",
    type: "line",
    source: SOURCE.roads,
    filter: ["in", ["get", "risk"], ["literal", ["impaired", "blocked"]]],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": [
        "case",
        ["==", ["get", "risk"], "blocked"],
        "#3a0d16",
        "#33230a",
      ],
      "line-opacity": dimmed(0.95),
      "line-width": roadWidth(7, 10),
    },
  },
  {
    id: "roads-affected",
    type: "line",
    source: SOURCE.roads,
    filter: ["==", ["get", "risk"], "impaired"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": COLORS.restricted,
      "line-opacity": dimmed(1),
      "line-width": emphasised(3, 4.2, 5),
    },
  },
  {
    id: "roads-blocked",
    type: "line",
    source: SOURCE.roads,
    filter: ["==", ["get", "risk"], "blocked"],
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": COLORS.closed,
      "line-opacity": dimmed(1),
      "line-width": emphasised(3.2, 4.4, 5.2),
      "line-dasharray": [1.4, 1.1],
    },
  },

  // Bridges are drawn from their own geometry so a span failure can be shown on
  // the span rather than inherited from the road class.
  {
    id: "bridge-casing",
    type: "line",
    source: SOURCE.bridgeLines,
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": COLORS.casing,
      "line-opacity": dimmed(0.92),
      "line-width": ["interpolate", ["linear"], ["zoom"], 11, 7, 16, 16],
    },
  },
  {
    id: "bridge-deck",
    type: "line",
    source: SOURCE.bridgeLines,
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": [
        "match",
        ["get", "risk"],
        "blocked",
        COLORS.closed,
        "impaired",
        COLORS.restricted,
        "#cfe2f4",
      ],
      "line-opacity": dimmed(1),
      "line-width": emphasised(4.5, 5.8, 6.8),
    },
  },

  /* ========================================================= operations */

  // Alternate plans: dashed, desaturated, and below the active route.
  {
    id: "route-alternate-casing",
    type: "line",
    source: SOURCE.routeAlternate,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": COLORS.casing,
      "line-opacity": dimmed(0.6),
      "line-width": 6,
    },
  },
  {
    id: "route-alternate-line",
    type: "line",
    source: SOURCE.routeAlternate,
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": COLORS.routeAlt,
      "line-opacity": dimmed(0.72),
      "line-width": 2.2,
      "line-dasharray": [2.4, 2],
    },
  },
  {
    id: "route-alternate-arrows",
    type: "symbol",
    source: SOURCE.routeAlternate,
    minzoom: 12.5,
    layout: {
      "icon-image": "ark-route-arrow-alt",
      "icon-size": 0.72,
      "symbol-placement": "line",
      "symbol-spacing": 110,
      "icon-rotation-alignment": "map",
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
    paint: { "icon-opacity": dimmed(0.7) },
  },

  // Active plan: dark casing, bright core, chevrons in travel direction.
  {
    id: "route-casing",
    type: "line",
    source: SOURCE.route,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": COLORS.casing,
      "line-opacity": dimmed(0.92),
      "line-width": emphasised(7, 8.5, 9.5),
    },
  },
  {
    id: "route-line",
    type: "line",
    source: SOURCE.route,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": [
        "case",
        ["==", ["get", "role"], "blocked"],
        COLORS.closed,
        COLORS.route,
      ],
      "line-opacity": dimmed(1),
      "line-width": emphasised(3.2, 4.2, 5),
      // A route that crosses a failed edge is shown broken, not quietly redrawn.
      "line-dasharray": [
        "case",
        ["==", ["get", "role"], "blocked"],
        ["literal", [1.6, 1.2]],
        ["literal", [1, 0]],
      ] as never,
    },
  },
  {
    id: "route-arrows",
    type: "symbol",
    source: SOURCE.route,
    minzoom: 11.5,
    layout: {
      "icon-image": "ark-route-arrow",
      "icon-size": 0.95,
      "symbol-placement": "line",
      "symbol-spacing": 78,
      "icon-rotation-alignment": "map",
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
    paint: { "icon-opacity": dimmed(0.9) },
  },

  // Response teams in transit. Driven by the animation loop, which rewrites the
  // source each frame; everything here is static styling.
  {
    id: "response-teams",
    type: "symbol",
    source: SOURCE.teams,
    // The scenario's default extent sits near z11.3, so anything stricter than
    // this would hide the teams on the view the dashboard opens with.
    minzoom: 10.5,
    layout: {
      "icon-image": "ark-team",
      "icon-size": ["interpolate", ["linear"], ["zoom"], 10.5, 0.62, 15, 1],
      "icon-rotate": ["get", "bearing"],
      "icon-rotation-alignment": "map",
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
      // Empty unless the route is focused, so only one ETA is ever on screen.
      "text-field": ["get", "label"],
      "text-font": FONT_MEDIUM,
      "text-size": 9.5,
      "text-offset": [0, 1.3],
      "text-anchor": "top",
      "text-optional": true,
    },
    paint: {
      "icon-opacity": dimmed(1),
      "text-color": "#d6f0ff",
      "text-opacity": dimmed(1),
      "text-halo-color": TEXT_HALO,
      "text-halo-width": 1.8,
    },
  },

  /* ============================================ hazards on the geometry */

  {
    id: "road-hazard-icons",
    type: "symbol",
    source: SOURCE.roadHazards,
    minzoom: 11.5,
    layout: {
      "icon-image": [
        "case",
        ["==", ["get", "risk"], "blocked"],
        "ark-closure",
        "ark-closure-restricted",
      ],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 11, 0.7, 15, 1],
      "icon-allow-overlap": true,
      "symbol-sort-key": 1,
    },
    paint: { "icon-opacity": dimmed(1) },
  },

  {
    id: "bridge-hazards",
    type: "symbol",
    source: SOURCE.bridges,
    layout: {
      "icon-image": [
        "match",
        ["get", "risk"],
        "blocked",
        "ark-bridge-closed",
        "impaired",
        "ark-bridge-restricted",
        "ark-bridge",
      ],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 11, 0.7, 15, 1],
      "icon-allow-overlap": true,
      "symbol-sort-key": 0,
    },
    paint: { "icon-opacity": dimmed(1) },
  },

  /* ============================================== communities and sites */

  // Hover and selection emphasis for every point symbol. Normal objects carry
  // no ring at all — it appears only for the feature under the cursor or the
  // one the operator has focused.
  {
    id: "asset-selection-ring",
    type: "circle",
    source: SOURCE.assets,
    paint: {
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["zoom"],
        11,
        ["case", isSelected, 13, 10],
        16,
        ["case", isSelected, 24, 19],
      ],
      "circle-color": COLORS.route,
      "circle-opacity": ringOpacity(0.16, 0.08),
      "circle-stroke-color": COLORS.route,
      "circle-stroke-width": ["case", isSelected, 1.8, 1.1],
      "circle-stroke-opacity": ringOpacity(0.9, 0.5),
    },
  },
  {
    id: "bridge-selection-ring",
    type: "circle",
    source: SOURCE.bridges,
    paint: {
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["zoom"],
        11,
        ["case", isSelected, 13, 10],
        16,
        ["case", isSelected, 24, 19],
      ],
      "circle-color": COLORS.route,
      "circle-opacity": ringOpacity(0.16, 0.08),
      "circle-stroke-color": COLORS.route,
      "circle-stroke-width": ["case", isSelected, 1.8, 1.1],
      "circle-stroke-opacity": ringOpacity(0.9, 0.5),
    },
  },

  {
    id: "shelter-icons",
    type: "symbol",
    source: SOURCE.assets,
    filter: ["==", ["get", "asset_type"], "shelter"],
    layout: {
      "icon-image": [
        "case",
        ["==", ["get", "reachable"], false],
        "ark-shelter-unreachable",
        "ark-shelter",
      ],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 11, 0.75, 15, 1],
      "icon-allow-overlap": true,
    },
    paint: { "icon-opacity": dimmed(1) },
  },
  {
    id: "hospital-icons",
    type: "symbol",
    source: SOURCE.assets,
    filter: ["==", ["get", "asset_type"], "hospital"],
    layout: {
      "icon-image": [
        "case",
        ["==", ["get", "reachable"], false],
        "ark-hospital-unreachable",
        "ark-hospital",
      ],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 11, 0.75, 15, 1],
      "icon-allow-overlap": true,
    },
    paint: { "icon-opacity": dimmed(1) },
  },
  // Only a community that has actually lost every exit carries a ring, and only
  // one ring is ever on screen at a time for that reason.
  {
    id: "community-alert-ring",
    type: "circle",
    source: SOURCE.assets,
    filter: [
      "all",
      ["==", ["get", "asset_type"], "community"],
      ["==", ["get", "isolated"], true],
    ],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 11, 16, 22],
      "circle-color": "transparent",
      "circle-stroke-color": COLORS.isolated,
      "circle-stroke-width": 1.4,
      "circle-stroke-opacity": dimmed(0.65),
    },
  },
  {
    id: "community-icons",
    type: "symbol",
    source: SOURCE.assets,
    filter: ["==", ["get", "asset_type"], "community"],
    layout: {
      "icon-image": [
        "match",
        ["get", "risk"],
        "isolated",
        "ark-community-isolated",
        "at_risk",
        "ark-community-at-risk",
        "ark-community",
      ],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 11, 0.7, 15, 1],
      "icon-allow-overlap": true,
    },
    paint: { "icon-opacity": dimmed(1) },
  },

  /* ============================================================ hazards */

  // Critical hazards are never zoom-gated; lower priorities wait for a zoom
  // where they will not crowd the map.
  /*
   * Escalation pulse.
   *
   * Filtered to nothing until a hazard actually escalates, then animated by the
   * animation loop for a few seconds and filtered back out. It is the only
   * pulsing thing the map ever draws, and only ever one at a time.
   */
  {
    id: "hazard-escalation-pulse",
    type: "circle",
    source: SOURCE.hazards,
    filter: ["==", ["get", "hazard_id"], "__none__"],
    paint: {
      "circle-radius": 11,
      "circle-color": COLORS.closed,
      "circle-opacity": 0,
      "circle-stroke-color": COLORS.closed,
      "circle-stroke-width": 1.6,
      "circle-stroke-opacity": 0,
      "circle-translate": [0, -16],
    },
  },

  {
    id: "hazard-icons-critical",
    type: "symbol",
    source: SOURCE.hazards,
    filter: ["==", ["get", "priority"], "critical"],
    layout: {
      "icon-image": [
        "case",
        ["==", ["get", "operator_injected"], true],
        "ark-hazard-injected",
        "ark-hazard-critical",
      ],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 11, 0.72, 15, 1],
      "icon-offset": [0, -16],
      "icon-allow-overlap": true,
      "symbol-sort-key": -2,
    },
    paint: { "icon-opacity": dimmed(1) },
  },
  {
    id: "hazard-icons",
    type: "symbol",
    source: SOURCE.hazards,
    minzoom: 12.5,
    filter: ["!=", ["get", "priority"], "critical"],
    layout: {
      "icon-image": [
        "case",
        ["==", ["get", "operator_injected"], true],
        "ark-hazard-injected",
        ["==", ["get", "priority"], "high"],
        "ark-hazard-high",
        "ark-hazard-medium",
      ],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 12.5, 0.75, 15, 0.95],
      "icon-offset": [0, -16],
      "icon-allow-overlap": true,
      "symbol-sort-key": -1,
    },
    paint: { "icon-opacity": dimmed(1) },
  },

  /* ======================================================== predictions */

  /*
   * Impact-prediction pings. These are model output about what a location may
   * suffer, not observed state, so they ride above the operational symbols but
   * keep their own colour family — target, not status — to avoid being read as
   * a closure or a hazard.
   */
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
      "circle-opacity": [
        "case",
        ["==", ["get", "state"], "active"],
        dimmed(0.22),
        dimmed(0.1),
      ],
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
      "circle-stroke-opacity": dimmed(0.6),
    },
  },
  {
    id: "ark-prediction-ping",
    type: "circle",
    source: SOURCE.predictions,
    paint: {
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["get", "priority_score"],
        0,
        5,
        100,
        12,
      ],
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
      "circle-opacity": [
        "case",
        ["==", ["get", "state"], "active"],
        dimmed(1),
        dimmed(0.68),
      ],
      "circle-stroke-color": "#f7fbff",
      "circle-stroke-width": [
        "case",
        ["==", ["get", "priority_level"], "critical"],
        2.8,
        1.5,
      ],
    },
  },
  {
    id: "ark-prediction-label",
    type: "symbol",
    source: SOURCE.predictions,
    minzoom: 12,
    layout: {
      "text-field": [
        "concat",
        "#",
        ["to-string", ["get", "priority_rank"]],
        " ",
        ["get", "short_label"],
        " ",
        ["get", "percent_label"],
      ],
      "text-font": FONT_MEDIUM,
      "text-size": ["interpolate", ["linear"], ["zoom"], 11, 9.5, 16, 12.5],
      "text-offset": [0, 1.8],
      "text-anchor": "top",
      "text-allow-overlap": false,
      "text-optional": true,
      "text-padding": 4,
    },
    paint: {
      "text-color": "#ffffff",
      "text-opacity": dimmed(1),
      "text-halo-color": TEXT_HALO,
      "text-halo-width": 2,
    },
  },

  /* ============================================================= labels */

  // Band label on the water itself, close zoom only.
  {
    id: "flood-depth-labels",
    type: "symbol",
    source: SOURCE.floodNow,
    minzoom: 14,
    layout: {
      "text-field": ["get", "band_label"],
      "text-font": FONT_MEDIUM,
      "text-size": 10,
      "text-letter-spacing": 0.05,
      "text-optional": true,
    },
    paint: {
      "text-color": "#bfe4ff",
      "text-opacity": ["interpolate", ["linear"], ["zoom"], 14, 0, 14.8, 0.8],
      "text-halo-color": TEXT_HALO,
      "text-halo-width": 1.8,
    },
  },

  // Status reads along the affected segment, so the words sit on the road.
  {
    id: "road-status-labels",
    type: "symbol",
    source: SOURCE.roads,
    minzoom: 13,
    filter: ["!=", ["get", "risk"], "clear"],
    layout: {
      "text-field": ["get", "status_label"],
      "text-font": FONT_MEDIUM,
      "text-size": 9,
      "text-letter-spacing": 0.1,
      "symbol-placement": "line-center",
      "text-offset": [0, -1.1],
      "text-optional": true,
    },
    paint: {
      "text-color": [
        "case",
        ["==", ["get", "risk"], "blocked"],
        "#ffc3cb",
        "#ffd79a",
      ],
      "text-opacity": dimmed(1),
      "text-halo-color": TEXT_HALO,
      "text-halo-width": 1.8,
    },
  },

  {
    id: "bridge-labels",
    type: "symbol",
    source: SOURCE.bridges,
    minzoom: 12,
    layout: {
      // Status and depth appear once the operator is close enough to act.
      // MapLibre allows one zoom expression per `text-field`, so the zoom steps
      // choose between whole label forms rather than nesting per line.
      "text-field": [
        "step",
        ["zoom"],
        ["format", ["get", "name"], { "font-scale": 1 }],
        13,
        [
          "format",
          ["get", "name"],
          { "font-scale": 1 },
          labelLine("status_label"),
          { "font-scale": 0.8 },
        ],
        14,
        [
          "format",
          ["get", "name"],
          { "font-scale": 1 },
          labelLine("status_label"),
          { "font-scale": 0.8 },
          labelLine("depth_label"),
          { "font-scale": 0.78 },
        ],
      ],
      "text-font": FONT_MEDIUM,
      "text-size": ["interpolate", ["linear"], ["zoom"], 12, 10.5, 16, 13],
      "text-offset": [0, 1.3],
      "text-anchor": "top",
      "text-optional": true,
      "symbol-sort-key": 0,
    },
    paint: {
      "text-color": [
        "match",
        ["get", "risk"],
        "blocked",
        "#ffc3cb",
        "impaired",
        "#ffd79a",
        "#d8e7f5",
      ],
      "text-opacity": dimmed(1),
      "text-halo-color": TEXT_HALO,
      "text-halo-width": 2.1,
    },
  },

  {
    id: "facility-labels",
    type: "symbol",
    source: SOURCE.assets,
    minzoom: 12.5,
    filter: ["in", ["get", "asset_type"], ["literal", ["hospital", "shelter"]]],
    layout: {
      "text-field": [
        "step",
        ["zoom"],
        ["format", ["get", "name"], { "font-scale": 1 }],
        14,
        [
          "format",
          ["get", "name"],
          { "font-scale": 1 },
          labelLine("detail_label"),
          { "font-scale": 0.8 },
        ],
      ],
      "text-font": FONT_MEDIUM,
      "text-size": ["interpolate", ["linear"], ["zoom"], 12.5, 10.5, 16, 13],
      "text-offset": [0, 1.2],
      "text-anchor": "top",
      "text-optional": true,
      // Facilities win a collision against a community label.
      "symbol-sort-key": 1,
    },
    paint: {
      "text-color": [
        "case",
        ["==", ["get", "reachable"], false],
        "#93a7b9",
        "#e6f1fb",
      ],
      "text-opacity": dimmed(1),
      "text-halo-color": TEXT_HALO,
      "text-halo-width": 2.1,
    },
  },

  {
    id: "community-labels",
    type: "symbol",
    source: SOURCE.assets,
    minzoom: 11,
    filter: ["==", ["get", "asset_type"], "community"],
    layout: {
      // Population is detail, not headline: it waits for a closer zoom, and a
      // community that has lost its exits says so one zoom earlier.
      "text-field": [
        "step",
        ["zoom"],
        ["format", ["get", "name"], { "font-scale": 1 }],
        12.5,
        [
          "format",
          ["get", "name"],
          { "font-scale": 1 },
          labelLine("status_label"),
          { "font-scale": 0.78 },
        ],
        13.5,
        [
          "format",
          ["get", "name"],
          { "font-scale": 1 },
          labelLine("detail_label"),
          { "font-scale": 0.8 },
          labelLine("status_label"),
          { "font-scale": 0.78 },
        ],
      ],
      "text-font": FONT_MEDIUM,
      "text-size": ["interpolate", ["linear"], ["zoom"], 11, 11, 16, 14],
      "text-offset": [0, 1.1],
      "text-anchor": "top",
      "text-optional": true,
      "symbol-sort-key": 2,
    },
    paint: {
      "text-color": [
        "match",
        ["get", "risk"],
        "isolated",
        "#ffc3cb",
        "at_risk",
        "#ffe0b0",
        "#f1f7fc",
      ],
      "text-opacity": dimmed(1),
      "text-halo-color": TEXT_HALO,
      "text-halo-width": 2.2,
    },
  },

  {
    id: "hazard-labels",
    type: "symbol",
    source: SOURCE.hazards,
    minzoom: 13,
    filter: ["==", ["get", "priority"], "critical"],
    layout: {
      "text-field": ["get", "title"],
      "text-font": FONT_MEDIUM,
      "text-size": 9.5,
      "text-offset": [0, -2.6],
      "text-anchor": "bottom",
      "text-optional": true,
      "symbol-sort-key": -2,
    },
    paint: {
      "text-color": "#ffc3cb",
      "text-opacity": dimmed(1),
      "text-halo-color": TEXT_HALO,
      "text-halo-width": 1.9,
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
  | "routeAlternate"
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
    label: "Flood depth (current)",
    swatch: "flood-now",
    layerIds: [
      "flood-current-fill",
      "flood-current-outline",
      "flood-depth-labels",
      "ark-channel-line",
      "flood-flow-arrows",
      "roads-submerged",
    ],
  },
  {
    key: "floodForecast",
    label: "Modeled +24h extent",
    swatch: "flood-forecast",
    layerIds: ["flood-modeled-fill", "flood-modeled-outline"],
  },
  {
    key: "roads",
    label: "Roads & closures",
    swatch: "roads",
    layerIds: [
      "roads-base-casing",
      "roads-base",
      "roads-affected-casing",
      "roads-affected",
      "roads-blocked",
      "road-hazard-icons",
      "road-status-labels",
    ],
  },
  {
    key: "route",
    label: "Active response routes",
    swatch: "route",
    layerIds: ["route-casing", "route-line", "route-arrows", "response-teams"],
  },
  {
    key: "routeAlternate",
    label: "Alternate plan routes",
    swatch: "route-alt",
    layerIds: [
      "route-alternate-casing",
      "route-alternate-line",
      "route-alternate-arrows",
    ],
  },
  {
    key: "facilities",
    label: "Shelters & hospital",
    swatch: "facilities",
    layerIds: ["shelter-icons", "hospital-icons", "facility-labels"],
  },
  {
    key: "bridges",
    label: "Bridges",
    swatch: "bridges",
    layerIds: ["bridge-casing", "bridge-deck", "bridge-hazards", "bridge-labels"],
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
    label: "Hazards",
    swatch: "alerts",
    layerIds: [
      "hazard-escalation-pulse",
      "hazard-icons-critical",
      "hazard-icons",
      "hazard-labels",
    ],
  },
  {
    key: "predictions",
    label: "Impact predictions",
    swatch: "predictions",
    layerIds: ["ark-prediction-pulse", "ark-prediction-ping", "ark-prediction-label"],
  },
  {
    key: "labels",
    label: "Community labels",
    swatch: "labels",
    layerIds: ["community-labels"],
  },
  {
    key: "context",
    label: "Administrative context",
    swatch: "context",
    layerIds: ["ark-context-fill", "ark-context-line"],
  },
];

/** Layers off by default: useful on demand, noisy as a baseline. */
export const DEFAULT_OFF: LayerKey[] = ["routeAlternate", "gauges"];

/* ------------------------------------------------------------ interaction */

/** Road-like layers whose features map back to an edge state. */
export const EDGE_LAYERS = [
  "roads-base",
  "roads-affected",
  "roads-blocked",
  "bridge-deck",
];

/** Symbols that select an edge but carry their own source. */
export const EDGE_SYMBOL_LAYERS = ["road-hazard-icons", "bridge-hazards"];

export const ASSET_LAYERS = ["community-icons", "shelter-icons", "hospital-icons"];

export const HAZARD_LAYERS = ["hazard-icons-critical", "hazard-icons"];

export const PREDICTION_LAYERS = ["ark-prediction-ping", "ark-prediction-pulse"];

export const FLOOD_LAYERS = ["flood-current-fill", "flood-modeled-fill"];

/** Everything clickable, topmost first — click resolution walks this order. */
export const PICKABLE_LAYERS = [
  ...PREDICTION_LAYERS,
  ...HAZARD_LAYERS,
  ...ASSET_LAYERS,
  ...EDGE_SYMBOL_LAYERS,
  ...EDGE_LAYERS,
];
