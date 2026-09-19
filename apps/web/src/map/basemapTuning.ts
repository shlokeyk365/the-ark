import type { LayerSpecification } from "maplibre-gl";

/**
 * Basemap tuning for the Kantipur operations map.
 *
 * The Protomaps dark theme is a general-purpose map: it gives every road class
 * similar weight, paints water the same grey as land, and labels shops. None of
 * that is wrong, it is just competing with the operational overlays for the same
 * ink. This module rewrites the generated style so OSM supplies geographic
 * context and nothing more:
 *
 * - POI and address symbols are dropped outright.
 * - Minor roads fade back and only appear once the operator has zoomed in.
 * - Waterways are the one basemap feature promoted rather than suppressed —
 *   the flood story is a river story.
 * - Buildings hold until close zoom, where they help read a neighbourhood.
 *
 * Everything is keyed by the layer ids the generator emits, so an upgrade that
 * renames a layer degrades to "left untouched" rather than throwing.
 */

/** Symbol layers that only add clutter over an incident map. */
const DROPPED = new Set([
  "pois",
  "address_label",
  "roads_shields",
  "roads_oneway",
  "landuse_zoo",
  "landuse_beach",
  "landuse_aerodrome",
  "landuse_runway",
  "roads_runway",
  "roads_taxiway",
]);

/** Local streets and service roads: present, but clearly below the arterials. */
const MINOR_ROAD_IDS = [
  "roads_other",
  "roads_link",
  "roads_minor_service",
  "roads_minor",
  "roads_minor_casing",
  "roads_minor_service_casing",
  "roads_link_casing",
  "roads_bridges_other",
  "roads_bridges_minor",
  "roads_bridges_link",
  "roads_bridges_other_casing",
  "roads_bridges_minor_casing",
  "roads_bridges_link_casing",
  "roads_tunnels_other",
  "roads_tunnels_minor",
  "roads_tunnels_link",
  "roads_tunnels_other_casing",
  "roads_tunnels_minor_casing",
  "roads_tunnels_link_casing",
  "roads_pier",
  "roads_rail",
];

const MAJOR_ROAD_IDS = [
  "roads_major",
  "roads_highway",
  "roads_bridges_major",
  "roads_bridges_highway",
  "roads_tunnels_major",
  "roads_tunnels_highway",
];

const WATER_FILL = "#10263c";
const WATER_LINE = "#1d5b8c";

/** Fade a line layer in over one zoom level instead of popping it on. */
function fadeIn(from: number, to: number, peak: number): unknown {
  return ["interpolate", ["linear"], ["zoom"], from, 0, to, peak];
}

function tuneLayer(layer: LayerSpecification): LayerSpecification | null {
  if (DROPPED.has(layer.id)) return null;

  const next = {
    ...layer,
    paint: { ...(layer as { paint?: Record<string, unknown> }).paint },
    layout: { ...(layer as { layout?: Record<string, unknown> }).layout },
  } as LayerSpecification & {
    paint: Record<string, unknown>;
    layout: Record<string, unknown>;
    minzoom?: number;
  };

  if (MINOR_ROAD_IDS.includes(layer.id)) {
    next.minzoom = Math.max(next.minzoom ?? 0, 13);
    next.paint["line-opacity"] = fadeIn(13, 14.5, layer.id.endsWith("casing") ? 0.3 : 0.5);
    return next;
  }

  if (MAJOR_ROAD_IDS.includes(layer.id)) {
    next.paint["line-opacity"] = 0.82;
    return next;
  }

  switch (layer.id) {
    // The river and its tributaries carry the scenario, so they read brighter
    // than a stock dark basemap would paint them.
    case "water":
      next.paint["fill-color"] = WATER_FILL;
      next.paint["fill-opacity"] = 0.95;
      return next;
    case "water_river":
      next.paint["line-color"] = WATER_LINE;
      next.paint["line-opacity"] = 0.8;
      return next;
    case "water_stream":
      next.minzoom = 12;
      next.paint["line-color"] = WATER_LINE;
      next.paint["line-opacity"] = 0.55;
      next.paint["line-width"] = fadeIn(12, 15, 1.6);
      return next;

    case "buildings":
      next.minzoom = 15;
      next.paint["fill-color"] = "#16202e";
      next.paint["fill-opacity"] = fadeIn(15, 16.5, 0.55);
      return next;

    case "landcover":
      next.paint["fill-opacity"] = 0.35;
      return next;

    // Administrative lines stay, but as a whisper.
    case "boundaries":
    case "boundaries_country":
      next.paint["line-opacity"] = 0.24;
      return next;

    case "roads_labels_minor":
      next.minzoom = 15;
      next.paint["text-opacity"] = fadeIn(15, 16, 0.7);
      return next;
    case "roads_labels_major":
      next.paint["text-opacity"] = 0.72;
      return next;

    // Place names are the context an operator actually reads off the basemap.
    case "places_locality":
    case "places_subplace":
      next.paint["text-halo-color"] = "rgba(4, 9, 16, 0.95)";
      next.paint["text-halo-width"] = 1.8;
      return next;
    case "places_region":
    case "places_country":
      next.paint["text-opacity"] = 0.5;
      return next;

    case "water_waterway_label":
      next.paint["text-color"] = "#79bce8";
      next.paint["text-halo-color"] = "rgba(4, 9, 16, 0.9)";
      return next;

    default:
      return next;
  }
}

/** Apply the operational treatment to a generated Protomaps layer list. */
export function tuneBasemapLayers(layers: LayerSpecification[]): LayerSpecification[] {
  return layers
    .map(tuneLayer)
    .filter((layer): layer is LayerSpecification => layer !== null);
}
