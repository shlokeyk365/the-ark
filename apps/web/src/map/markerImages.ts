/**
 * Map symbols, drawn at runtime.
 *
 * The operational entities need a visual language of their own — a shelter
 * should not be a circle that happens to be green — but the basemap sprite only
 * carries OSM POI icons. Rather than ship and serve a second sprite sheet,
 * every symbol is rasterised here into an `ImageData` and registered with
 * `map.addImage`.
 *
 * Shape carries entity type, fill carries status. That pairing is deliberate:
 * an operator reading the map in a hurry, or one who cannot separate the
 * amber from the red, still gets the type from the outline.
 *
 * Non-SDF images cannot be tinted by a paint property, so each type/status pair
 * is registered as its own image and selected with a `match` expression.
 */

const RATIO = 2;
const DARK = "#060d16";

export type MarkerShape =
  | "community"
  | "shelter"
  | "hospital"
  | "hazard"
  | "closure"
  | "bridge"
  | "team"
  | "convoy";

interface MarkerStyle {
  /** Icon footprint in CSS pixels; stays inside the 12–20px operational range. */
  size: number;
  fill: string;
  /** Outline drawn around the badge, keeping symbols legible over imagery. */
  ring: string;
  /** Glyph colour, when the shape carries one. */
  glyph: string;
}

function context(size: number): CanvasRenderingContext2D {
  const canvas = document.createElement("canvas");
  canvas.width = size * RATIO;
  canvas.height = size * RATIO;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("2D canvas context unavailable for map symbols");
  ctx.scale(RATIO, RATIO);
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  return ctx;
}

function roundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + width, y, x + width, y + height, radius);
  ctx.arcTo(x + width, y + height, x, y + height, radius);
  ctx.arcTo(x, y + height, x, y, radius);
  ctx.arcTo(x, y, x + width, y, radius);
  ctx.closePath();
}

function drawShape(ctx: CanvasRenderingContext2D, shape: MarkerShape, style: MarkerStyle) {
  const { size } = style;
  const centre = size / 2;
  const inset = 2.5;
  const span = size - inset * 2;

  ctx.fillStyle = style.fill;
  ctx.strokeStyle = style.ring;
  ctx.lineWidth = 1.6;

  switch (shape) {
    case "community": {
      ctx.beginPath();
      ctx.arc(centre, centre, span / 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      break;
    }

    case "shelter": {
      // House outline: gable over a square body.
      const half = span / 2;
      ctx.beginPath();
      ctx.moveTo(centre, inset);
      ctx.lineTo(centre + half, centre - half * 0.15);
      ctx.lineTo(centre + half, size - inset);
      ctx.lineTo(centre - half, size - inset);
      ctx.lineTo(centre - half, centre - half * 0.15);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      break;
    }

    case "hospital": {
      roundedRect(ctx, inset, inset, span, span, 3);
      ctx.fill();
      ctx.stroke();

      const arm = span * 0.3;
      const thickness = Math.max(1.8, span * 0.16);
      ctx.fillStyle = style.glyph;
      ctx.fillRect(centre - thickness / 2, centre - arm, thickness, arm * 2);
      ctx.fillRect(centre - arm, centre - thickness / 2, arm * 2, thickness);
      break;
    }

    case "hazard": {
      // Warning triangle with an exclamation cut into it.
      const half = span / 2;
      ctx.beginPath();
      ctx.moveTo(centre, inset);
      ctx.lineTo(size - inset, size - inset * 1.2);
      ctx.lineTo(inset, size - inset * 1.2);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = style.glyph;
      const barWidth = Math.max(1.5, half * 0.22);
      ctx.fillRect(centre - barWidth / 2, centre - half * 0.28, barWidth, half * 0.72);
      ctx.beginPath();
      ctx.arc(centre, centre + half * 0.68, barWidth * 0.62, 0, Math.PI * 2);
      ctx.fill();
      break;
    }

    case "closure": {
      ctx.beginPath();
      ctx.arc(centre, centre, span / 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      const arm = span * 0.24;
      ctx.strokeStyle = style.glyph;
      ctx.lineWidth = Math.max(1.8, span * 0.15);
      ctx.beginPath();
      ctx.moveTo(centre - arm, centre - arm);
      ctx.lineTo(centre + arm, centre + arm);
      ctx.moveTo(centre + arm, centre - arm);
      ctx.lineTo(centre - arm, centre + arm);
      ctx.stroke();
      break;
    }

    case "bridge": {
      /*
       * A viaduct: a deck carried on two arches.
       *
       * Two details decide whether this reads at marker size. The arches must
       * bulge *upward* toward the deck — canvas arcs sweep clockwise with y
       * pointing down, so they need the anticlockwise flag or they come out as
       * bowls and the glyph turns into an "m". And the arch legs are the piers,
       * so drawing separate verticals just fills the circle with ink.
       */
      ctx.beginPath();
      ctx.arc(centre, centre, span / 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      const radius = span * 0.25;
      const deckY = centre - span * 0.2;
      const footY = deckY + radius + Math.max(1, span * 0.07);

      ctx.strokeStyle = style.glyph;
      ctx.lineCap = "butt";

      ctx.lineWidth = Math.max(1.6, span * 0.12);
      ctx.beginPath();
      ctx.moveTo(centre - radius * 2.05, deckY);
      ctx.lineTo(centre + radius * 2.05, deckY);
      ctx.stroke();

      ctx.lineWidth = Math.max(1.2, span * 0.085);
      for (const archCentre of [centre - radius, centre + radius]) {
        ctx.beginPath();
        ctx.arc(archCentre, footY, radius, Math.PI, 0, true);
        ctx.stroke();
      }

      ctx.lineCap = "round";
      break;
    }

    case "team": {
      const half = span / 2;
      ctx.beginPath();
      ctx.moveTo(centre, inset);
      ctx.lineTo(size - inset, centre);
      ctx.lineTo(centre, size - inset);
      ctx.lineTo(inset, centre);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      break;
    }

    case "convoy": {
      // A navigation puck: the disc locates the unit, the nose gives heading.
      // Drawn pointing north so `icon-rotate` can carry the route bearing.
      ctx.beginPath();
      ctx.arc(centre, centre, span / 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      const reach = span * 0.24;
      ctx.fillStyle = style.glyph;
      ctx.beginPath();
      ctx.moveTo(centre, centre - reach * 1.15);
      ctx.lineTo(centre + reach * 0.62, centre + reach * 0.5);
      ctx.lineTo(centre, centre + reach * 0.16);
      ctx.lineTo(centre - reach * 0.62, centre + reach * 0.5);
      ctx.closePath();
      ctx.fill();
      break;
    }
  }
}

function marker(shape: MarkerShape, style: MarkerStyle): ImageData {
  const ctx = context(style.size);
  drawShape(ctx, shape, style);
  return ctx.getImageData(0, 0, style.size * RATIO, style.size * RATIO);
}

/** A directional chevron laid along response routes. */
function chevron(color: string): ImageData {
  const size = 11;
  const ctx = context(size);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  ctx.moveTo(size * 0.32, size * 0.22);
  ctx.lineTo(size * 0.7, size * 0.5);
  ctx.lineTo(size * 0.32, size * 0.78);
  ctx.stroke();
  return ctx.getImageData(0, 0, size * RATIO, size * RATIO);
}

/**
 * Every registered image id.
 *
 * Names are `ark-<shape>-<status>` and referenced from layer expressions, so
 * they are spelled once here and matched literally there.
 */
export const MARKER_IMAGES: Record<string, ImageData> = {
  "ark-community": marker("community", {
    size: 14,
    fill: "#cfe2f4",
    ring: DARK,
    glyph: DARK,
  }),
  "ark-community-at-risk": marker("community", {
    size: 15,
    fill: "#f0a52a",
    ring: DARK,
    glyph: DARK,
  }),
  "ark-community-isolated": marker("community", {
    size: 16,
    fill: "#f24d63",
    ring: "#ffd8dd",
    glyph: DARK,
  }),

  "ark-shelter": marker("shelter", {
    size: 17,
    fill: "#2eb277",
    ring: "#081a13",
    glyph: "#ffffff",
  }),
  "ark-shelter-unreachable": marker("shelter", {
    size: 16,
    fill: "#2b4a41",
    ring: "#4a6c61",
    glyph: "#8fb0a4",
  }),

  "ark-hospital": marker("hospital", {
    size: 17,
    fill: "#e8536a",
    ring: "#200810",
    glyph: "#ffffff",
  }),
  "ark-hospital-unreachable": marker("hospital", {
    size: 16,
    fill: "#4a2731",
    ring: "#6f4450",
    glyph: "#c39aa3",
  }),

  "ark-hazard-critical": marker("hazard", {
    size: 18,
    fill: "#f24d63",
    ring: "#ffd8dd",
    glyph: "#1a0509",
  }),
  "ark-hazard-high": marker("hazard", {
    size: 16,
    fill: "#f0a52a",
    ring: "#2a1c05",
    glyph: "#1a1205",
  }),
  "ark-hazard-medium": marker("hazard", {
    size: 14,
    fill: "#7fc4ff",
    ring: "#06121f",
    glyph: "#06121f",
  }),
  /** Operator-injected events carry an amber diamond, per the state grammar. */
  "ark-hazard-injected": marker("team", {
    size: 16,
    fill: "#f5b54a",
    ring: "#2a1c05",
    glyph: "#1a1205",
  }),

  "ark-closure": marker("closure", {
    size: 15,
    fill: "#f24d63",
    ring: "#ffd8dd",
    glyph: "#ffffff",
  }),
  "ark-closure-restricted": marker("closure", {
    size: 13,
    fill: "#f0a52a",
    ring: "#2a1c05",
    glyph: "#2a1c05",
  }),

  "ark-bridge": marker("bridge", {
    size: 18,
    fill: "#16293d",
    ring: "#9fc0dc",
    glyph: "#cfe2f4",
  }),
  "ark-bridge-restricted": marker("bridge", {
    size: 19,
    fill: "#f0a52a",
    ring: "#2a1c05",
    glyph: "#1a1205",
  }),
  "ark-bridge-closed": marker("bridge", {
    size: 20,
    fill: "#f24d63",
    ring: "#ffd8dd",
    glyph: "#ffffff",
  }),

  /** Response team in transit along the active route. */
  "ark-team": marker("convoy", {
    size: 16,
    fill: "#5fc4ff",
    ring: "#04121f",
    glyph: "#04121f",
  }),

  "ark-route-arrow": chevron("#d6f0ff"),
  "ark-route-arrow-alt": chevron("#7f93ab"),
};

/**
 * Register every symbol on a map instance.
 *
 * Safe to call more than once — a style reload drops the images but keeps the
 * layers, and re-adding an image that already exists would throw.
 */
export function registerMarkerImages(map: {
  hasImage: (id: string) => boolean;
  addImage: (id: string, image: ImageData, options?: { pixelRatio?: number }) => void;
}): void {
  Object.entries(MARKER_IMAGES).forEach(([id, image]) => {
    if (map.hasImage(id)) return;
    map.addImage(id, image, { pixelRatio: RATIO });
  });
}
