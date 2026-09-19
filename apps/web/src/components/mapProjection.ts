import type { Position } from "@the-ark/shared-types";

export const BASE_W = 1200;
/** Fallback canvas height used before the container has been measured. */
export const DEFAULT_BASE_H = 700;

/** Padding reserved around the scenario extent inside the base canvas. */
const FIT = { left: 150, right: 150, top: 118, bottom: 112 };

/**
 * Base-canvas height matching the container's aspect ratio, so the SVG never
 * letterboxes and the scenario uses the full width of the panel.
 */
export function baseHeightFor(width: number, height: number): number {
  if (!width || !height) return DEFAULT_BASE_H;
  return Math.round(Math.min(1600, Math.max(380, BASE_W * (height / width))));
}

const KM_PER_DEG_LAT = 110.574;
const KM_PER_DEG_LON_EQUATOR = 111.32;

export interface ProjectedPoint {
  x: number;
  y: number;
}

export interface Projection {
  project: (position: Position) => ProjectedPoint;
  /** Base-canvas pixels per kilometre, before any zoom is applied. */
  pxPerKm: number;
  kmPerDegLon: number;
}

/**
 * Equirectangular projection anchored on the scenario's own centre latitude.
 *
 * Both axes share one scale so the rendered scale bar is honest and the
 * network keeps its true shape. The extent is fitted from the routed network
 * only; context geometry projects through the same transform and is allowed to
 * overflow the viewport, exactly as a basemap would.
 */
export function buildProjection(positions: Position[], baseH: number): Projection {
  const longitudes = positions.map(([longitude]) => longitude);
  const latitudes = positions.map(([, latitude]) => latitude);

  const minLongitude = Math.min(...longitudes);
  const maxLongitude = Math.max(...longitudes);
  const minLatitude = Math.min(...latitudes);
  const maxLatitude = Math.max(...latitudes);

  const referenceLatitude = (minLatitude + maxLatitude) / 2;
  const kmPerDegLon =
    KM_PER_DEG_LON_EQUATOR * Math.cos((referenceLatitude * Math.PI) / 180);

  const spanX = (maxLongitude - minLongitude) * kmPerDegLon || 1;
  const spanY = (maxLatitude - minLatitude) * KM_PER_DEG_LAT || 1;

  const innerWidth = BASE_W - FIT.left - FIT.right;
  const innerHeight = baseH - FIT.top - FIT.bottom;
  const pxPerKm = Math.min(innerWidth / spanX, innerHeight / spanY);

  const offsetX = FIT.left + (innerWidth - spanX * pxPerKm) / 2;
  const offsetY = FIT.top + (innerHeight - spanY * pxPerKm) / 2;

  const project = ([longitude, latitude]: Position): ProjectedPoint => ({
    x: offsetX + (longitude - minLongitude) * kmPerDegLon * pxPerKm,
    y: offsetY + (maxLatitude - latitude) * KM_PER_DEG_LAT * pxPerKm,
  });

  return { project, pxPerKm, kmPerDegLon };
}

export function kmToLatDegrees(km: number): number {
  return km / KM_PER_DEG_LAT;
}

/** Quadratic smoothing through a point sequence, for river-like geometry. */
export function smoothPath(points: ProjectedPoint[]): string {
  if (points.length === 0) return "";
  if (points.length < 3) {
    return points
      .map((point, index) => `${index === 0 ? "M" : "L"}${point.x} ${point.y}`)
      .join(" ");
  }

  let path = `M${points[0].x} ${points[0].y}`;
  for (let index = 1; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const midX = (current.x + next.x) / 2;
    const midY = (current.y + next.y) / 2;
    path += ` Q${current.x} ${current.y} ${midX} ${midY}`;
  }
  const last = points[points.length - 1];
  const penultimate = points[points.length - 2];
  path += ` Q${penultimate.x} ${penultimate.y} ${last.x} ${last.y}`;
  return path;
}

export interface LabelBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface LabelRequest {
  id: string;
  anchor: ProjectedPoint;
  text: string;
  /** Marker radius to keep clear of. */
  radius: number;
}

const LABEL_HEIGHT = 18;
const CHAR_WIDTH = 6.5;
const LABEL_PADDING = 10;
const EDGE_MARGIN = 10;

function overlapArea(a: LabelBox, b: LabelBox): number {
  const width = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
  const height = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
  return width > 0 && height > 0 ? width * height : 0;
}

/**
 * Deterministic greedy label placement.
 *
 * Each label tries a fixed sequence of offsets and takes the first that stays
 * inside the canvas and clears every box already placed, so labels never clip
 * at the map edge or collide with each other or with a marker.
 */
export function layoutLabels(
  requests: LabelRequest[],
  baseH: number,
  reserved: LabelBox[] = [],
): Map<string, LabelBox> {
  const placed: LabelBox[] = [
    ...reserved,
    ...requests.map((request) => ({
      x: request.anchor.x - request.radius,
      y: request.anchor.y - request.radius,
      width: request.radius * 2,
      height: request.radius * 2,
    })),
  ];

  const result = new Map<string, LabelBox>();
  const ordered = [...requests].sort((a, b) => a.id.localeCompare(b.id));

  ordered.forEach((request) => {
    const width = request.text.length * CHAR_WIDTH + LABEL_PADDING;
    const { x, y } = request.anchor;
    const gap = request.radius + 6;

    const candidates: LabelBox[] = [
      { x: x + gap, y: y - LABEL_HEIGHT - 4, width, height: LABEL_HEIGHT },
      { x: x - gap - width, y: y - LABEL_HEIGHT - 4, width, height: LABEL_HEIGHT },
      { x: x + gap, y: y + 4, width, height: LABEL_HEIGHT },
      { x: x - gap - width, y: y + 4, width, height: LABEL_HEIGHT },
      { x: x - width / 2, y: y - gap - LABEL_HEIGHT - 2, width, height: LABEL_HEIGHT },
      { x: x - width / 2, y: y + gap + 2, width, height: LABEL_HEIGHT },
      { x: x + gap, y: y - gap - LABEL_HEIGHT - 10, width, height: LABEL_HEIGHT },
      { x: x - gap - width, y: y + gap + 10, width, height: LABEL_HEIGHT },
      { x: x - width / 2, y: y - gap - LABEL_HEIGHT - 22, width, height: LABEL_HEIGHT },
      { x: x - width / 2, y: y + gap + 22, width, height: LABEL_HEIGHT },
    ];

    const outOfBounds = (box: LabelBox) =>
      Math.max(0, EDGE_MARGIN - box.x) +
      Math.max(0, box.x + box.width - (BASE_W - EDGE_MARGIN)) +
      Math.max(0, EDGE_MARGIN - box.y) +
      Math.max(0, box.y + box.height - (baseH - EDGE_MARGIN));

    const fits = (box: LabelBox) =>
      outOfBounds(box) === 0 &&
      placed.every((existing) => overlapArea(box, existing) === 0);

    // When nothing fits cleanly, take the least-bad position rather than a
    // fixed fallback that could sit under the map chrome.
    const cost = (box: LabelBox) =>
      outOfBounds(box) * 5000 +
      placed.reduce((total, existing) => total + overlapArea(box, existing), 0);

    const chosen =
      candidates.find(fits) ??
      candidates.reduce((best, candidate) =>
        cost(candidate) < cost(best) ? candidate : best,
      );

    placed.push(chosen);
    result.set(request.id, chosen);
  });

  return result;
}
