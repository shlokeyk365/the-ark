#!/usr/bin/env node
/**
 * Lay the Kantipur road network onto real streets.
 *
 * The scenario network is authored as twelve straight lines between abstract
 * nodes. Over a schematic that reads fine; over a satellite image of Kathmandu
 * it reads as a rectangle drawn on top of a city, because that is exactly what
 * it is. Nothing about the domain requires it: routing scores edges by
 * `baseline_travel_minutes` from the fixture and never looks at geometry, so
 * the shape of a road is free to be honest without changing a single result.
 *
 * This reshapes the edges to follow OpenStreetMap street centrelines taken from
 * the basemap archive the app already ships:
 *
 *   1. Read the `roads` layer out of the local PMTiles over the scenario
 *      extent and build a graph of real street segments.
 *   2. Snap each scenario node to the nearest real street vertex.
 *   3. Route each scenario edge between its snapped endpoints along that graph
 *      and adopt the resulting path as the edge's geometry.
 *
 * Topology is untouched: the same edge IDs, the same from/to nodes, the same
 * travel times, thresholds and criticality. Only the drawn line changes.
 *
 * Usage:
 *   node scripts/snap-network-to-streets.mjs            snap
 *   node scripts/snap-network-to-streets.mjs --restore  put the straight lines back
 *   node scripts/snap-network-to-streets.mjs --dry-run  report, write nothing
 */

import { createRequire } from "node:module";
import { readFileSync, writeFileSync, copyFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { PMTiles } = require("pmtiles");
const { VectorTile } = require("@mapbox/vector-tile");
const { PbfReader } = require("pbf");

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURES = join(ROOT, "data", "scenarios", "kantipur-river");
const ARCHIVE =
  process.env.BASEMAP_PMTILES ??
  join(ROOT, "apps", "web", "public", "basemap", "kantipur.pmtiles");

const NETWORK = join(FIXTURES, "road-network.geojson");
const FLOOD = join(FIXTURES, "flood-polygons.geojson");
const ASSETS = join(FIXTURES, "assets.geojson");
const NETWORK_ORIGINAL = join(FIXTURES, "road-network.straight-v1.geojson");
const ASSETS_ORIGINAL = join(FIXTURES, "assets.straight-v1.geojson");

const TILE_ZOOM = Number(process.env.TILE_ZOOM ?? 14);
const BBOX_PADDING = 0.01;

/** Street classes worth routing along. Paths and rail are not roads. */
const ROAD_KINDS = new Set(["major_road", "minor_road", "other"]);

/** Vertex merge tolerance in degrees (~1 m), so tile seams join up. */
const QUANTIZE = Number(process.env.QUANTIZE ?? 8e-5);

/**
 * Reject a snapped path that wanders. A real street route is longer than the
 * straight line, but a path several times longer means the snap found the wrong
 * side of a river or a disconnected fragment, and the straight edge is the more
 * honest drawing.
 */
const MAX_DETOUR_RATIO = 4.0;

/** Half the drawn length of a bridge deck, in metres. */
const DECK_HALF_SPAN_M = Number(process.env.DECK_HALF_SPAN_M ?? 70);

const METRES_PER_DEGREE = 111_320;

/* ------------------------------------------------------------- web mercator */

const lonToTileX = (lon, z) => ((lon + 180) / 360) * 2 ** z;
function latToTileY(lat, z) {
  const radians = (lat * Math.PI) / 180;
  return (
    ((1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) / 2) * 2 ** z
  );
}

function distanceMetres(a, b) {
  const scale = Math.cos((a[1] * Math.PI) / 180);
  return Math.hypot((b[0] - a[0]) * scale, b[1] - a[1]) * METRES_PER_DEGREE;
}

/* -------------------------------------------------------------------- input */

const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));

class BufferSource {
  constructor(buffer, key) {
    this.buffer = buffer;
    this.key = key;
  }
  getKey() {
    return this.key;
  }
  async getBytes(offset, length) {
    return {
      data: this.buffer.buffer.slice(
        this.buffer.byteOffset + offset,
        this.buffer.byteOffset + offset + length,
      ),
    };
  }
}

/* ------------------------------------------------------------- street graph */

/** Minimal binary min-heap for Dijkstra. */
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

/** Build an undirected street graph from the basemap archive. */
async function loadStreetGraph(bbox) {
  if (!existsSync(ARCHIVE)) {
    throw new Error(
      `Basemap archive not found at ${ARCHIVE}. Run "npm run basemap" first.`,
    );
  }

  const archive = new PMTiles(new BufferSource(readFileSync(ARCHIVE), ARCHIVE));
  const [west, south, east, north] = bbox;
  const minX = Math.floor(lonToTileX(west, TILE_ZOOM));
  const maxX = Math.floor(lonToTileX(east, TILE_ZOOM));
  const minY = Math.floor(latToTileY(north, TILE_ZOOM));
  const maxY = Math.floor(latToTileY(south, TILE_ZOOM));

  const positions = [];
  const index = new Map();
  const adjacency = [];

  const key = (point) =>
    `${Math.round(point[0] / QUANTIZE)}:${Math.round(point[1] / QUANTIZE)}`;

  const vertexFor = (point) => {
    const id = key(point);
    const existing = index.get(id);
    if (existing !== undefined) return existing;
    const next = positions.length;
    positions.push(point);
    adjacency.push([]);
    index.set(id, next);
    return next;
  };

  let segments = 0;

  for (let y = minY; y <= maxY; y += 1) {
    for (let x = minX; x <= maxX; x += 1) {
      const tile = await archive.getZxy(TILE_ZOOM, x, y);
      if (!tile) continue;

      const layer = new VectorTile(new PbfReader(new Uint8Array(tile.data))).layers.roads;
      if (!layer) continue;

      for (let feature = 0; feature < layer.length; feature += 1) {
        const road = layer.feature(feature);
        if (!ROAD_KINDS.has(road.properties.kind)) continue;

        const geometry = road.toGeoJSON(x, y, TILE_ZOOM).geometry;
        const lines =
          geometry.type === "LineString" ? [geometry.coordinates] : geometry.coordinates;

        for (const line of lines) {
          for (let point = 1; point < line.length; point += 1) {
            const from = vertexFor(line[point - 1]);
            const to = vertexFor(line[point]);
            if (from === to) continue;
            const weight = distanceMetres(positions[from], positions[to]);
            adjacency[from].push([to, weight]);
            adjacency[to].push([from, weight]);
            segments += 1;
          }
        }
      }
    }
  }

  /*
   * Keep only the largest connected component.
   *
   * Vector tiles clip geometry at their edges, so a street graph rebuilt from
   * them is riddled with small orphan fragments. Snapping a scenario node onto
   * one of those strands an edge in an island of its own and the route fails.
   * Restricting the snap targets to the main component guarantees any two
   * scenario nodes can reach each other.
   */
  const component = new Int32Array(positions.length).fill(-1);
  let largest = -1;
  let largestSize = 0;

  for (let seed = 0; seed < positions.length; seed += 1) {
    if (component[seed] >= 0) continue;
    const stack = [seed];
    component[seed] = seed;
    let size = 0;
    while (stack.length > 0) {
      const current = stack.pop();
      size += 1;
      for (const [next] of adjacency[current]) {
        if (component[next] >= 0) continue;
        component[next] = seed;
        stack.push(next);
      }
    }
    if (size > largestSize) {
      largestSize = size;
      largest = seed;
    }
  }

  return { positions, adjacency, segments, component, largest, largestSize };
}

/** Nearest street vertex to a point, within the routable component. */
function nearestVertex(graph, point) {
  let best = -1;
  let bestDistance = Infinity;
  for (let index = 0; index < graph.positions.length; index += 1) {
    if (graph.component[index] !== graph.largest) continue;
    const candidate = graph.positions[index];
    const squared =
      (candidate[0] - point[0]) * (candidate[0] - point[0]) +
      (candidate[1] - point[1]) * (candidate[1] - point[1]);
    if (squared < bestDistance) {
      bestDistance = squared;
      best = index;
    }
  }
  return best;
}

/** Shortest street path between two vertices, or null when disconnected. */
function shortestPath(graph, start, goal) {
  const distances = new Float64Array(graph.positions.length).fill(Infinity);
  const previous = new Int32Array(graph.positions.length).fill(-1);
  const settled = new Uint8Array(graph.positions.length);
  const heap = new MinHeap();

  distances[start] = 0;
  heap.push(0, start);

  while (heap.size > 0) {
    const current = heap.pop();
    if (settled[current]) continue;
    settled[current] = 1;
    if (current === goal) break;

    for (const [next, weight] of graph.adjacency[current]) {
      const candidate = distances[current] + weight;
      if (candidate < distances[next]) {
        distances[next] = candidate;
        previous[next] = current;
        heap.push(candidate, next);
      }
    }
  }

  if (!settled[goal]) return null;

  const path = [];
  for (let at = goal; at !== -1; at = previous[at]) path.push(graph.positions[at]);
  return { points: path.reverse(), length: distances[goal] };
}

/* ------------------------------------------------------------ bridge decks */

function pointInRing(point, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (
      yi > point[1] !== yj > point[1] &&
      point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi
    ) {
      inside = !inside;
    }
  }
  return inside;
}

/**
 * The widest modeled water surface, used as the river corridor.
 *
 * The shallowest band of the peak frame is the full inundated extent, which is
 * the best available stand-in for "where the water is" without adding a river
 * polygon to the fixture set.
 */
function floodCorridor() {
  if (!existsSync(FLOOD)) return [];
  const collection = readJson(FLOOD);
  const peak = Math.max(
    ...collection.features.map((feature) => feature.properties.simulation_time_hours),
  );
  return collection.features
    .filter(
      (feature) =>
        feature.properties.simulation_time_hours === peak &&
        feature.properties.depth_min_m === 0,
    )
    .map((feature) => feature.geometry.coordinates[0]);
}

/**
 * The stretch of a routed path that actually crosses water.
 *
 * A scenario "bridge" links two junctions kilometres apart, so its street route
 * is a long drive that happens to include a river crossing. Drawing the whole
 * route as bridge deck would be wrong — the span is only the part over the
 * water, and that is where the bridge marker and its failure belong.
 */
function crossingSegment(path, corridor) {
  const wet = path.map((point) => corridor.some((ring) => pointInRing(point, ring)));

  let bestStart = -1;
  let bestLength = 0;
  let start = -1;

  for (let index = 0; index <= wet.length; index += 1) {
    if (index < wet.length && wet[index]) {
      if (start < 0) start = index;
    } else if (start >= 0) {
      if (index - start > bestLength) {
        bestLength = index - start;
        bestStart = start;
      }
      start = -1;
    }
  }

  // No crossing found: fall back to the middle of the route so the bridge is at
  // least somewhere sensible rather than at an arbitrary endpoint.
  const centre =
    bestStart < 0 || bestLength < 2
      ? Math.floor(path.length / 2)
      : bestStart + Math.floor(bestLength / 2);

  /*
   * Trim to a span, not a riverside drive.
   *
   * The wet stretch of a route is usually far longer than the crossing itself,
   * because roads run along a floodplain as well as over it. Taking a fixed
   * length either side of the crossing's midpoint is what keeps the deck
   * reading as a bridge.
   */
  let first = centre;
  let last = centre;
  let before = 0;
  let after = 0;

  while (first > 0 && before < DECK_HALF_SPAN_M) {
    before += distanceMetres(path[first - 1], path[first]);
    first -= 1;
  }
  while (last < path.length - 1 && after < DECK_HALF_SPAN_M) {
    after += distanceMetres(path[last], path[last + 1]);
    last += 1;
  }

  return path.slice(first, last + 1);
}

/* ---------------------------------------------------------------- generator */

async function snap({ dryRun }) {
  const network = readJson(NETWORK);
  const assets = readJson(ASSETS);

  // Node positions come from the authored geometry: an edge starts at its
  // `from` node and ends at its `to` node.
  const nodePoints = new Map();
  for (const feature of network.features) {
    const line = feature.geometry.coordinates;
    nodePoints.set(feature.properties.from_node_id, line[0]);
    nodePoints.set(feature.properties.to_node_id, line[line.length - 1]);
  }

  const positions = [...nodePoints.values()];
  const bbox = [
    Math.min(...positions.map((p) => p[0])) - BBOX_PADDING,
    Math.min(...positions.map((p) => p[1])) - BBOX_PADDING,
    Math.max(...positions.map((p) => p[0])) + BBOX_PADDING,
    Math.max(...positions.map((p) => p[1])) + BBOX_PADDING,
  ];

  process.stderr.write(`reading streets from ${ARCHIVE}\n`);
  const graph = await loadStreetGraph(bbox);
  process.stderr.write(
    `  street graph: ${graph.positions.length} vertices, ${graph.segments} segments\n` +
      `  routable component: ${graph.largestSize} vertices ` +
      `(${((graph.largestSize / graph.positions.length) * 100).toFixed(0)}%)\n\n`,
  );

  const snapped = new Map();
  for (const [nodeId, point] of nodePoints) {
    const vertex = nearestVertex(graph, point);
    snapped.set(nodeId, vertex);
    process.stderr.write(
      `  ${nodeId.padEnd(26)} moved ${distanceMetres(point, graph.positions[vertex]).toFixed(0).padStart(4)} m onto a street\n`,
    );
  }
  process.stderr.write("\n");

  let routed = 0;
  let fallback = 0;

  for (const feature of network.features) {
    const line = feature.geometry.coordinates;
    const straight = distanceMetres(line[0], line[line.length - 1]);
    const path = shortestPath(
      graph,
      snapped.get(feature.properties.from_node_id),
      snapped.get(feature.properties.to_node_id),
    );

    const detour = path ? path.length / Math.max(straight, 1) : Infinity;
    if (!path || detour > MAX_DETOUR_RATIO) {
      // Keep the straight line but move its ends onto the snapped nodes, so
      // the network still joins up where a routed edge meets a fallback one.
      feature.geometry.coordinates = [
        graph.positions[snapped.get(feature.properties.from_node_id)],
        graph.positions[snapped.get(feature.properties.to_node_id)],
      ];
      fallback += 1;
      process.stderr.write(
        `  ${feature.id.padEnd(16)} straight (${path ? `detour x${detour.toFixed(1)}` : "no street route"})\n`,
      );
      continue;
    }

    feature.geometry.coordinates = path.points.map(([lon, lat]) => [
      Number(lon.toFixed(6)),
      Number(lat.toFixed(6)),
    ]);
    routed += 1;
    process.stderr.write(
      `  ${feature.id.padEnd(16)} routed ${path.points.length.toString().padStart(3)} pts, ` +
        `${path.length.toFixed(0)} m (x${detour.toFixed(2)} straight)\n`,
    );
  }

  // Assets sit on the network, so they move with their node. A bridge adopts
  // the geometry of the edge it represents.
  const corridor = floodCorridor();
  process.stderr.write(`\n  flood corridor rings: ${corridor.length}\n`);
  const edgeById = new Map(network.features.map((feature) => [feature.id, feature]));
  for (const feature of assets.features) {
    const { node_id: nodeId, edge_id: edgeId } = feature.properties;
    if (nodeId && snapped.has(nodeId)) {
      const [lon, lat] = graph.positions[snapped.get(nodeId)];
      feature.geometry = {
        type: "Point",
        coordinates: [Number(lon.toFixed(6)), Number(lat.toFixed(6))],
      };
    } else if (edgeId && edgeById.has(edgeId)) {
      const deck = crossingSegment(
        edgeById.get(edgeId).geometry.coordinates,
        corridor,
      );
      feature.geometry = { type: "LineString", coordinates: deck };
      process.stderr.write(
        `  ${feature.id.padEnd(16)} deck ${deck.length} pts, ` +
          `${distanceMetres(deck[0], deck[deck.length - 1]).toFixed(0)} m span\n`,
      );
    }
  }

  process.stderr.write(
    `\n${routed} edges routed along streets, ${fallback} left straight\n`,
  );

  if (dryRun) {
    process.stderr.write("dry run: nothing written\n");
    return;
  }

  if (!existsSync(NETWORK_ORIGINAL)) copyFileSync(NETWORK, NETWORK_ORIGINAL);
  if (!existsSync(ASSETS_ORIGINAL)) copyFileSync(ASSETS, ASSETS_ORIGINAL);

  writeFileSync(NETWORK, `${JSON.stringify(network, null, 2)}\n`);
  writeFileSync(ASSETS, `${JSON.stringify(assets, null, 2)}\n`);
  process.stderr.write(`wrote ${NETWORK}\nwrote ${ASSETS}\n`);
  process.stderr.write("restore the straight network with: npm run network:restore\n");
}

function restore() {
  if (!existsSync(NETWORK_ORIGINAL)) {
    process.stderr.write(`no preserved original at ${NETWORK_ORIGINAL}\n`);
    process.exit(1);
  }
  copyFileSync(NETWORK_ORIGINAL, NETWORK);
  copyFileSync(ASSETS_ORIGINAL, ASSETS);
  process.stderr.write("restored the authored straight-line network and assets\n");
}

const args = process.argv.slice(2);
if (args.includes("--restore")) restore();
else await snap({ dryRun: args.includes("--dry-run") });
