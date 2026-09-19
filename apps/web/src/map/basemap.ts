/**
 * Basemap configuration.
 *
 * Everything here is keyless. The vector basemap is a PMTiles archive served as
 * a static file, terrain comes from AWS Open Data, and satellite imagery is an
 * optional public raster service. No account, token, or metered API is
 * involved, and the archive can be served from the app's own origin so the map
 * keeps working offline.
 */

/** Static PMTiles archive. Point this at object storage in production. */
export const BASEMAP_PMTILES =
  import.meta.env.VITE_BASEMAP_PMTILES ?? "/basemap/kantipur.pmtiles";

/** Terrarium-encoded DEM, AWS Open Data. No key, no auth. */
export const TERRAIN_TILES =
  import.meta.env.VITE_TERRAIN_TILES ??
  "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";

/** Esri World Imagery. Optional layer — confirm terms for your deployment. */
export const SATELLITE_TILES =
  import.meta.env.VITE_SATELLITE_TILES ??
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

/** Glyphs and sprites for the Protomaps basemap. Self-hostable. */
export const BASEMAP_GLYPHS =
  import.meta.env.VITE_BASEMAP_GLYPHS ??
  "https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf";

export const BASEMAP_SPRITE =
  import.meta.env.VITE_BASEMAP_SPRITE ??
  "https://protomaps.github.io/basemaps-assets/sprites/v4/dark";

/** Label language for basemap place names. Required for label layers. */
export const BASEMAP_LANG = import.meta.env.VITE_BASEMAP_LANG ?? "en";

export const BASEMAP_SOURCE_ID = "protomaps";
export const TERRAIN_SOURCE_ID = "terrain-dem";
export const SATELLITE_SOURCE_ID = "satellite";
export const SATELLITE_LAYER_ID = "basemap-satellite";

export const OSM_ATTRIBUTION =
  '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">&copy; OpenStreetMap</a>';
export const PROTOMAPS_ATTRIBUTION =
  '<a href="https://protomaps.com" target="_blank" rel="noreferrer">Protomaps</a>';
export const TERRAIN_ATTRIBUTION =
  '<a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noreferrer">AWS Terrain Tiles</a>';
export const SATELLITE_ATTRIBUTION = "Imagery &copy; Esri";

/** Resolve a same-origin archive path into an absolute pmtiles:// URL. */
export function pmtilesUrl(path: string): string {
  if (path.startsWith("pmtiles://")) return path;
  const absolute = /^https?:\/\//.test(path)
    ? path
    : new URL(path, window.location.origin).href;
  return `pmtiles://${absolute}`;
}
