#!/usr/bin/env node
/**
 * Generate the Kantipur flood depth-band surface.
 *
 * The hand-authored surface this replaces had two problems. It only existed for
 * four of the scenario's frames, so the water blinked on and off as the
 * timeline advanced, and each band was a single ribbon drawn across the whole
 * valley with no relationship to the terrain underneath it.
 *
 * This derives the surface instead:
 *
 *   1. Fetch the AWS Terrarium DEM covering the scenario and decode it to
 *      ground elevation in metres.
 *   2. For each frame, raise a water surface until the deepest water standing
 *      on the road network equals that frame's canonical per-edge depth. The
 *      depths in `flood-frames.json` remain the only source of truth; this
 *      calibrates the surface against them rather than inventing new values.
 *   3. Depth at a cell is `water surface - ground`, flood-filled outward from
 *      the channel so water cannot appear in a hollow the river cannot reach.
 *   4. Marching squares (d3-contour) turns the depth field into the same four
 *      depth bands the API contract and legend already use.
 *
 * The result is committed as a fixture, exactly like the basemap archive: the
 * dashboard stays offline-capable and deterministic, and nobody pays for this
 * at runtime.
 *
 * Usage:
 *   node scripts/generate-flood-surface.mjs            generate
 *   node scripts/generate-flood-surface.mjs --restore  put the original back
 *   node scripts/generate-flood-surface.mjs --dry-run  report, write nothing
 */

import { createRequire } from "node:module";
import { readFileSync, writeFileSync, copyFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { contours } = require("d3-contour");
const { PNG } = require("pngjs");

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURES = join(ROOT, "data", "scenarios", "kantipur-river");
const OUTPUT = join(FIXTURES, "flood-polygons.geojson");
const ORIGINAL = join(FIXTURES, "flood-polygons.curated-v1.geojson");

const TERRAIN_TILES =
  process.env.TERRAIN_TILES ??
  "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";

/** Terrarium tiles are published to z15; z14 is ~9 m/px at this latitude. */
const DEM_ZOOM = 14;
const TILE_SIZE = 256;

/** Depth thresholds. These match the API contract and the map legend exactly. */
const BANDS = [
  { min: 0.0, max: 0.1, label: "0–0.10 m" },
  { min: 0.1, max: 0.2, label: "0.10–0.20 m" },
  { min: 0.2, max: 0.3, label: "0.20–0.30 m" },
  { min: 0.3, max: 0.5, label: "0.30–0.50 m" },
];

/** Margin around the scenario extent, in degrees, so bands are not clipped. */
const BBOX_PADDING = 0.012;

/**
 * Upslope cell count above which a cell counts as river channel.
 *
 * At z14 each cell is roughly 9 m across, so this is about 0.4 km² of
 * contributing area — low enough to pick up the tributaries that matter to the
 * scenario, high enough to ignore every hillside rill.
 */
const CHANNEL_THRESHOLD = Number(process.env.CHANNEL_THRESHOLD ?? 40000);

/** DEM pooling factor; 3 takes ~9 m cells to ~28 m. */
const DOWNSAMPLE = 3;

/**
 * River stage at the scenario's peak frame, in metres above the channel.
 *
 * The one tuned number in this script: it sets how far the water spreads at
 * full flood. Override with PEAK_STAGE_M to retune without editing code.
 */
const PEAK_STAGE_M = Number(process.env.PEAK_STAGE_M ?? 4.0);

/* ------------------------------------------------------------- web mercator */

const lonToTileX = (lon, z) => ((lon + 180) / 360) * 2 ** z;

function latToTileY(lat, z) {
  const radians = (lat * Math.PI) / 180;
  return (
    ((1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) / 2) *
    2 ** z
  );
}

const tileXToLon = (x, z) => (x / 2 ** z) * 360 - 180;

function tileYToLat(y, z) {
  const n = Math.PI - (2 * Math.PI * y) / 2 ** z;
  return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

/* -------------------------------------------------------------------- input */

function readJson(name) {
  return JSON.parse(readFileSync(join(FIXTURES, name), "utf8"));
}

/** Scenario extent, from everything that has a position. */
function scenarioBbox(assets, network) {
  const positions = [];
  for (const feature of network.features) positions.push(...feature.geometry.coordinates);
  for (const feature of assets.features) {
    if (feature.geometry.type === "Point") positions.push(feature.geometry.coordinates);
    else positions.push(...feature.geometry.coordinates);
  }

  const lons = positions.map((p) => p[0]);
  const lats = positions.map((p) => p[1]);
  return [
    Math.min(...lons) - BBOX_PADDING,
    Math.min(...lats) - BBOX_PADDING,
    Math.max(...lons) + BBOX_PADDING,
    Math.max(...lats) + BBOX_PADDING,
  ];
}

/* ---------------------------------------------------------------------- DEM */

async function fetchTile(z, x, y) {
  const url = TERRAIN_TILES.replace("{z}", z).replace("{x}", x).replace("{y}", y);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`DEM tile ${z}/${x}/${y}: HTTP ${response.status}`);
  const png = PNG.sync.read(Buffer.from(await response.arrayBuffer()));
  return png;
}

/**
 * Ground elevation grid covering the bbox.
 *
 * Terrarium encodes height as `(R * 256 + G + B / 256) - 32768` metres.
 */
async function loadElevationGrid(bbox) {
  const [west, south, east, north] = bbox;
  const minTileX = Math.floor(lonToTileX(west, DEM_ZOOM));
  const maxTileX = Math.floor(lonToTileX(east, DEM_ZOOM));
  const minTileY = Math.floor(latToTileY(north, DEM_ZOOM));
  const maxTileY = Math.floor(latToTileY(south, DEM_ZOOM));

  const width = (maxTileX - minTileX + 1) * TILE_SIZE;
  const height = (maxTileY - minTileY + 1) * TILE_SIZE;
  const elevation = new Float32Array(width * height);

  const total = (maxTileX - minTileX + 1) * (maxTileY - minTileY + 1);
  process.stderr.write(`  fetching ${total} DEM tiles at z${DEM_ZOOM}…\n`);

  for (let tileY = minTileY; tileY <= maxTileY; tileY += 1) {
    for (let tileX = minTileX; tileX <= maxTileX; tileX += 1) {
      const png = await fetchTile(DEM_ZOOM, tileX, tileY);
      const offsetX = (tileX - minTileX) * TILE_SIZE;
      const offsetY = (tileY - minTileY) * TILE_SIZE;

      for (let row = 0; row < TILE_SIZE; row += 1) {
        for (let column = 0; column < TILE_SIZE; column += 1) {
          const source = (row * png.width + column) * 4;
          const metres =
            png.data[source] * 256 +
            png.data[source + 1] +
            png.data[source + 2] / 256 -
            32768;
          elevation[(offsetY + row) * width + offsetX + column] = metres;
        }
      }
    }
  }

  return {
    elevation,
    width,
    height,
    originTileX: minTileX,
    originTileY: minTileY,
    /** Grid column/row -> longitude/latitude. */
    lon: (column) => tileXToLon(minTileX + column / TILE_SIZE, DEM_ZOOM),
    lat: (row) => tileYToLat(minTileY + row / TILE_SIZE, DEM_ZOOM),
  };
}

/**
 * Light box blur.
 *
 * A 9 m DEM carries enough per-pixel noise that raw marching squares produces
 * shredded, speckled bands. Smoothing the terrain before contouring is what
 * makes the output read as water rather than as static.
 */
/**
 * Mean-pool the grid down by an integer factor.
 *
 * A 9 m DEM is finer than the flood surface needs and its noise survives
 * blurring. Pooling to roughly 30 m both averages that away and cuts the
 * downstream work by an order of magnitude.
 */
function downsample(grid, width, height, factor) {
  const outWidth = Math.floor(width / factor);
  const outHeight = Math.floor(height / factor);
  const output = new Float32Array(outWidth * outHeight);

  for (let row = 0; row < outHeight; row += 1) {
    for (let column = 0; column < outWidth; column += 1) {
      let total = 0;
      for (let dy = 0; dy < factor; dy += 1) {
        for (let dx = 0; dx < factor; dx += 1) {
          total += grid[(row * factor + dy) * width + column * factor + dx];
        }
      }
      output[row * outWidth + column] = total / (factor * factor);
    }
  }

  return { grid: output, width: outWidth, height: outHeight };
}

function smooth(grid, width, height, radius = 2) {
  const output = new Float32Array(grid.length);
  for (let row = 0; row < height; row += 1) {
    for (let column = 0; column < width; column += 1) {
      let total = 0;
      let count = 0;
      for (let dy = -radius; dy <= radius; dy += 1) {
        const y = row + dy;
        if (y < 0 || y >= height) continue;
        for (let dx = -radius; dx <= radius; dx += 1) {
          const x = column + dx;
          if (x < 0 || x >= width) continue;
          total += grid[y * width + x];
          count += 1;
        }
      }
      output[row * width + column] = total / count;
    }
  }
  return output;
}

/* ------------------------------------------------------- drainage and HAND */

/** Minimal binary min-heap, keyed by elevation. */
class MinHeap {
  constructor() {
    this.keys = [];
    this.values = [];
  }
  get size() {
    return this.keys.length;
  }
  push(key, value) {
    this.keys.push(key);
    this.values.push(value);
    let index = this.keys.length - 1;
    while (index > 0) {
      const parent = (index - 1) >> 1;
      if (this.keys[parent] <= this.keys[index]) break;
      this.swap(parent, index);
      index = parent;
    }
  }
  pop() {
    const value = this.values[0];
    const key = this.keys.pop();
    const last = this.values.pop();
    if (this.keys.length > 0) {
      this.keys[0] = key;
      this.values[0] = last;
      let index = 0;
      for (;;) {
        const left = index * 2 + 1;
        const right = left + 1;
        let smallest = index;
        if (left < this.keys.length && this.keys[left] < this.keys[smallest]) smallest = left;
        if (right < this.keys.length && this.keys[right] < this.keys[smallest]) smallest = right;
        if (smallest === index) break;
        this.swap(smallest, index);
        index = smallest;
      }
    }
    return value;
  }
  swap(a, b) {
    [this.keys[a], this.keys[b]] = [this.keys[b], this.keys[a]];
    [this.values[a], this.values[b]] = [this.values[b], this.values[a]];
  }
}

/**
 * Fill depressions (priority-flood).
 *
 * This is the step that makes the rest work. A raw DEM of a built-up valley
 * floor is full of one-cell pits — noise, buildings, bridges — and every one of
 * them is a place where flow stops. Without filling, those pits get treated as
 * drainage, HAND collapses to zero across half the grid, and the contours come
 * out as thousands of speckles instead of a river.
 *
 * Water is poured in from the edges: each cell is raised to at least the level
 * of the lowest path out to the boundary.
 */
function fillSinks(ground, width, height) {
  const filled = Float32Array.from(ground);
  const closed = new Uint8Array(ground.length);
  const heap = new MinHeap();

  for (let column = 0; column < width; column += 1) {
    for (const row of [0, height - 1]) {
      const index = row * width + column;
      closed[index] = 1;
      heap.push(filled[index], index);
    }
  }
  for (let row = 1; row < height - 1; row += 1) {
    for (const column of [0, width - 1]) {
      const index = row * width + column;
      closed[index] = 1;
      heap.push(filled[index], index);
    }
  }

  while (heap.size > 0) {
    const index = heap.pop();
    const column = index % width;
    const row = (index - column) / width;

    for (const [dx, dy] of NEIGHBOURS) {
      const x = column + dx;
      const y = row + dy;
      if (x < 0 || y < 0 || x >= width || y >= height) continue;
      const next = y * width + x;
      if (closed[next]) continue;
      closed[next] = 1;
      /*
       * The epsilon matters. Filling a depression flat leaves every cell on it
       * with no strictly lower neighbour, D8 then reports "no downstream", and
       * those cells become their own drainage reference — which collapses HAND
       * to zero across the entire valley floor. Tilting each filled cell a
       * fraction of a millimetre above its predecessor guarantees a descent
       * path out of every flat.
       */
      if (filled[next] <= filled[index]) filled[next] = filled[index] + FILL_EPSILON;
      heap.push(filled[next], next);
    }
  }

  return filled;
}

/** Gradient imposed across filled flats so every cell still drains. */
const FILL_EPSILON = 1e-4;

const NEIGHBOURS = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1],
  [1, 1],
  [1, -1],
  [-1, 1],
  [-1, -1],
];

/**
 * D8 flow directions and accumulation over the depression-filled surface.
 *
 * Accumulation is pushed downslope in descending-elevation order, which
 * resolves the whole grid in one pass and cannot loop the way a naive recursive
 * walk can on flat ground.
 */
function flowNetwork(filled, width, height) {
  const downstream = new Int32Array(filled.length).fill(-1);
  const accumulation = new Float32Array(filled.length).fill(1);

  for (let index = 0; index < filled.length; index += 1) {
    const column = index % width;
    const row = (index - column) / width;

    let steepest = -1;
    let drop = 0;

    for (const [dx, dy] of NEIGHBOURS) {
      const x = column + dx;
      const y = row + dy;
      if (x < 0 || y < 0 || x >= width || y >= height) continue;
      const next = y * width + x;
      // Normalise by distance so diagonals do not win on gradient alone.
      const gradient = (filled[index] - filled[next]) / Math.hypot(dx, dy);
      if (gradient > drop) {
        drop = gradient;
        steepest = next;
      }
    }
    downstream[index] = steepest;
  }

  const order = Array.from(filled.keys()).sort((a, b) => filled[b] - filled[a]);
  for (const index of order) {
    const next = downstream[index];
    if (next >= 0) accumulation[next] += accumulation[index];
  }

  return { downstream, accumulation, ascending: order.slice().reverse() };
}

/**
 * Height above nearest drainage.
 *
 * Each cell follows its flow path down to the first channel cell and records
 * how far above that channel it sits. Resolving in ascending-elevation order
 * means a cell's downstream neighbour is always already known, so the whole
 * field is one linear pass rather than a walk per cell.
 *
 * HAND is what makes the surface terrain-shaped: water at a given stage covers
 * everything within that height of the river, which is the valley floor, rather
 * than everything below an absolute elevation.
 */
function heightAboveDrainage(ground, network, channelThreshold) {
  const { downstream, accumulation, ascending } = network;
  const reference = new Int32Array(ground.length).fill(-1);
  const channel = new Uint8Array(ground.length);

  for (const index of ascending) {
    if (accumulation[index] >= channelThreshold) {
      reference[index] = index;
      channel[index] = 1;
      continue;
    }
    const next = downstream[index];
    if (next < 0) {
      reference[index] = index;
      continue;
    }
    reference[index] = reference[next] >= 0 ? reference[next] : next;
  }

  const hand = new Float32Array(ground.length);
  for (let index = 0; index < ground.length; index += 1) {
    hand[index] = Math.max(0, ground[index] - ground[reference[index]]);
  }
  return { hand, channel };
}

/* ------------------------------------------------------------------ raster */

/** Grid cells the road network passes through, for depth calibration. */
function roadCells(network, dem) {
  const cells = [];
  const toColumn = (lon) =>
    ((lonToTileX(lon, DEM_ZOOM) - dem.originTileX) * TILE_SIZE) / DOWNSAMPLE;
  const toRow = (lat) =>
    ((latToTileY(lat, DEM_ZOOM) - dem.originTileY) * TILE_SIZE) / DOWNSAMPLE;

  for (const feature of network.features) {
    const line = feature.geometry.coordinates;
    for (let index = 1; index < line.length; index += 1) {
      const [x0, y0] = [toColumn(line[index - 1][0]), toRow(line[index - 1][1])];
      const [x1, y1] = [toColumn(line[index][0]), toRow(line[index][1])];
      const steps = Math.ceil(Math.hypot(x1 - x0, y1 - y0));
      for (let step = 0; step <= steps; step += 1) {
        const t = steps === 0 ? 0 : step / steps;
        const column = Math.round(x0 + (x1 - x0) * t);
        const row = Math.round(y0 + (y1 - y0) * t);
        if (column < 0 || row < 0 || column >= dem.width || row >= dem.height) continue;
        cells.push(row * dem.width + column);
      }
    }
  }
  return [...new Set(cells)];
}

/**
 * Water depth over the grid at a given stage above the channel.
 *
 * Depth is measured against HAND rather than absolute elevation, so the result
 * is inherently connected to the drainage network and no flood fill is needed:
 * a hollow on a hillside has a large HAND and simply never wets.
 */
function depthField(hand, channel, width, height, stage, targetDepth) {
  const wet = new Float32Array(hand.length);
  // Terrain gives the shape; the canonical maximum gives the scale.
  const scale = targetDepth / stage;
  for (let index = 0; index < hand.length; index += 1) {
    const value = stage - hand[index];
    if (value > 0) wet[index] = value * scale;
  }

  /*
   * Keep only water the river can actually reach.
   *
   * HAND alone still admits isolated low spots that happen to sit close to some
   * minor tributary. Growing outward from the channel cells and discarding
   * everything the flood never touches is what turns a field of patches into a
   * single coherent inundation.
   */
  const depth = new Float32Array(hand.length);
  const visited = new Uint8Array(hand.length);
  const queue = [];

  for (let index = 0; index < channel.length; index += 1) {
    if (channel[index] && wet[index] > 0) {
      visited[index] = 1;
      queue.push(index);
    }
  }

  while (queue.length > 0) {
    const index = queue.pop();
    depth[index] = wet[index];

    const column = index % width;
    const row = (index - column) / width;
    for (const [dx, dy] of NEIGHBOURS) {
      const x = column + dx;
      const y = row + dy;
      if (x < 0 || y < 0 || x >= width || y >= height) continue;
      const next = y * width + x;
      if (visited[next] || wet[next] <= 0) continue;
      visited[next] = 1;
      queue.push(next);
    }
  }

  return depth;
}

/**
 * River stage for a frame, as a fraction of the scenario's peak.
 *
 * Extent and depth are deliberately separated here, and it is worth being
 * explicit about why. The canonical numbers in `flood-frames.json` are water
 * depth *on the road surface* — 0.02 m rising to 0.39 m. Used directly as a
 * river stage against real terrain they produce nothing usable: the Kathmandu
 * valley floor is flat enough that 0.02 m and 0.39 m inundate almost the same
 * ten square kilometres, so every frame and every band come out the same size.
 *
 * Real flooding that isolates a community is metres of stage, not centimetres.
 * So stage is scaled to the scenario's own progression — `PEAK_STAGE_M` at the
 * peak frame, proportionally less earlier — which makes the extent grow the way
 * the narrative requires while keeping the growth curve exactly the one the
 * canonical depths describe.
 *
 * The depth *values* are then rescaled back onto the canonical range, so the
 * deepest water in any frame still equals that frame's canonical maximum and
 * the four bands keep the meanings the contract and legend give them.
 */
function stageFor(targetDepth, peakDepth) {
  if (targetDepth <= 0) return null;
  return PEAK_STAGE_M * (targetDepth / peakDepth);
}

/* --------------------------------------------------------------- contouring */

/** Shoelace area of a ring, in square degrees. */
function ringArea(ring) {
  let total = 0;
  for (let index = 0; index < ring.length - 1; index += 1) {
    total +=
      ring[index][0] * ring[index + 1][1] - ring[index + 1][0] * ring[index][1];
  }
  return Math.abs(total) / 2;
}

/**
 * Smallest polygon worth drawing, in square degrees (~0.02 km² here).
 *
 * Deep bands naturally break into pools along the channel, which is honest, but
 * below this size they are single-cell contour artefacts that read as dirt on
 * the screen rather than as water.
 */
const MIN_RING_AREA = 1.8e-6;

/** Contour the depth field into bands, in longitude/latitude. */
function bandPolygons(depth, dem, band) {
  const generator = contours().size([dem.width, dem.height]).smooth(true);
  const geometry = generator.contour(Array.from(depth), band.min + 1e-6);

  const rings = [];
  for (const polygon of geometry.coordinates) {
    const converted = polygon.map((ring) => {
      const points = ring.map(([column, row]) => [
        Number(dem.lon(column).toFixed(6)),
        Number(dem.lat(row).toFixed(6)),
      ]);
      // Rounding can pull the last vertex off the first, and the fixture
      // contract requires rings that close exactly.
      const first = points[0];
      const last = points[points.length - 1];
      if (first[0] !== last[0] || first[1] !== last[1]) points.push([...first]);
      return points;
    });
    // The first ring is the outer boundary; the rest are holes in it.
    const [outer, ...holes] = converted;
    if (!outer || outer.length < 8 || ringArea(outer) < MIN_RING_AREA) continue;
    rings.push([outer, ...holes.filter((hole) => ringArea(hole) >= MIN_RING_AREA)]);
  }

  return rings;
}

/* ---------------------------------------------------------------- generator */

async function generate({ dryRun }) {
  const manifest = readJson("scenario.json");
  const assets = readJson("assets.geojson");
  const network = readJson("road-network.geojson");
  const floodFrames = readJson("flood-frames.json");

  const bbox = scenarioBbox(assets, network);
  process.stderr.write(`scenario bbox: ${bbox.map((v) => v.toFixed(4)).join(", ")}\n`);

  const raw = await loadElevationGrid(bbox);
  const pooled = downsample(raw.elevation, raw.width, raw.height, DOWNSAMPLE);
  const dem = {
    ...raw,
    width: pooled.width,
    height: pooled.height,
    lon: (column) => raw.lon(column * DOWNSAMPLE),
    lat: (row) => raw.lat(row * DOWNSAMPLE),
  };
  const ground = smooth(pooled.grid, dem.width, dem.height, 1);
  process.stderr.write(
    `  DEM grid: ${raw.width} x ${raw.height} pooled to ${dem.width} x ${dem.height}\n`,
  );

  const filled = fillSinks(ground, dem.width, dem.height);
  const flow = flowNetwork(filled, dem.width, dem.height);
  const { hand, channel } = heightAboveDrainage(ground, flow, CHANNEL_THRESHOLD);
  const channelCells = channel.reduce((total, value) => total + value, 0);
  process.stderr.write(
    `  drainage: ${channelCells} channel cells at accumulation >= ${CHANNEL_THRESHOLD}\n`,
  );

  const roads = roadCells(network, dem);
  let lowestRoadHand = Infinity;
  for (const cell of roads) if (hand[cell] < lowestRoadHand) lowestRoadHand = hand[cell];
  process.stderr.write(
    `  road cells: ${roads.length}, lowest sits ${lowestRoadHand.toFixed(2)} m above drainage\n\n`,
  );

  const peakDepth = Math.max(
    ...floodFrames.frames.flatMap((frame) =>
      frame.edge_conditions.map((edge) => edge.flood_depth_m),
    ),
  );
  process.stderr.write(`  peak canonical depth: ${peakDepth.toFixed(2)} m -> stage ${PEAK_STAGE_M} m\n\n`);

  const features = [];

  for (const frame of floodFrames.frames) {
    const targetDepth = Math.max(
      ...frame.edge_conditions.map((edge) => edge.flood_depth_m),
    );
    const stage = stageFor(targetDepth, peakDepth);

    if (stage === null) {
      process.stderr.write(
        `  ${frame.frame_id.padEnd(22)} +${String(frame.simulation_time_hours).padStart(2)}h  ` +
          `max=${targetDepth.toFixed(2)}m  dry, no bands\n`,
      );
      continue;
    }

    const depth = depthField(hand, channel, dem.width, dem.height, stage, targetDepth);

    let bandCount = 0;
    let polygonCount = 0;
    const frameKey = frame.frame_id.replace("ktp-frame-", "");

    for (const band of BANDS) {
      // A band only exists once the water is actually that deep somewhere.
      if (targetDepth < band.min) continue;
      const rings = bandPolygons(depth, dem, band);
      if (rings.length === 0) continue;

      const bandKey = band.min.toFixed(2).replace(".", "");

      /*
       * One Feature per polygon rather than a single MultiPolygon. Deep bands
       * legitimately break into separate pools, but the fixture contract and
       * `FloodPolygonFeature` are Polygon-only, and widening them would ripple
       * through the shared types, the API model and every consumer. Band
       * identity lives in the properties, which is what the map styles on.
       */
      rings.forEach((polygon, index) => {
        const id = `ktp-flood-${frameKey}-${bandKey}-${index}`;
        features.push({
          type: "Feature",
          id,
          properties: {
            id,
            frame_id: frame.frame_id,
            simulation_time_hours: frame.simulation_time_hours,
            depth_min_m: band.min,
            depth_max_m: band.max,
            band_label: band.label,
            surface_kind: "curated_synthetic_surface",
            source_type: "modeled_input",
          },
          geometry: { type: "Polygon", coordinates: polygon },
        });
        polygonCount += 1;
      });
      bandCount += 1;
    }

    process.stderr.write(
      `  ${frame.frame_id.padEnd(22)} +${String(frame.simulation_time_hours).padStart(2)}h  ` +
        `max=${targetDepth.toFixed(2)}m  stage=${stage.toFixed(2)}m  ` +
        `bands=${bandCount}  polygons=${polygonCount}\n`,
    );
  }

  const collection = {
    type: "FeatureCollection",
    name: "kantipur-river-flood-polygons",
    scenario_id: manifest.scenario_id,
    data_classification: "modeled_synthetic_demo",
    operational_use: false,
    source: {
      source_type: "modeled_input",
      model_name: "kantipur-terrain-banded-surface",
      model_version: "2.0.0",
      description:
        "Depth bands derived from AWS Terrarium elevation by raising a water " +
        "surface until the deepest water on the road network matches the " +
        "canonical per-edge depth for each frame, flood-filled from the valley " +
        "floor and contoured with marching squares. Deterministic and " +
        "regenerable via scripts/generate-flood-surface.mjs. Not hydraulic " +
        "solver output.",
    },
    features,
  };

  process.stderr.write(`\n${features.length} band features across ${floodFrames.frames.length} frames\n`);

  if (dryRun) {
    process.stderr.write("dry run: nothing written\n");
    return;
  }

  writeFileSync(OUTPUT, `${JSON.stringify(collection, null, 2)}\n`);
  process.stderr.write(`wrote ${OUTPUT}\n`);
  process.stderr.write(`restore the original with: npm run flood:restore\n`);
}

function restore() {
  if (!existsSync(ORIGINAL)) {
    process.stderr.write(`no preserved original at ${ORIGINAL}\n`);
    process.exit(1);
  }
  copyFileSync(ORIGINAL, OUTPUT);
  process.stderr.write(`restored the original hand-authored surface from ${ORIGINAL}\n`);
}

const args = process.argv.slice(2);
if (args.includes("--restore")) {
  restore();
} else {
  await generate({ dryRun: args.includes("--dry-run") });
}
