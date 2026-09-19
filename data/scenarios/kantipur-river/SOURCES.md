# Kantipur River scenario data sources

## Curated flood depth surface

`flood-polygons.geojson` is generated, not hand-authored. Regenerate it with:

```bash
npm run flood:generate
```

It is not copied from an observed flood, remote-sensing product, or hydraulic
model, and remains explicitly marked `modeled_synthetic_demo`,
`curated_synthetic_surface`, and `operational_use: false`.

### How it is derived

`scripts/generate-flood-surface.mjs` builds the bands from public elevation
data rather than drawing them:

1. AWS Terrarium DEM tiles covering the scenario extent are decoded to ground
   elevation, pooled to roughly 30 m cells and lightly smoothed.
2. Depressions are filled (priority-flood with an epsilon gradient) so every
   cell drains, and D8 flow accumulation locates the river channel.
3. Height above nearest drainage (HAND) gives each cell its height over that
   channel, so a given river stage inundates the valley floor rather than
   everything under an absolute elevation.
4. Each frame's river stage is scaled from that frame's canonical peak depth in
   `flood-frames.json`, and the resulting depth field is rescaled so its
   deepest water equals that canonical peak exactly.
5. `d3-contour` cuts the field into the same four depth bands the API contract
   and the map legend already define.

The terrain supplies the *shape*; `flood-frames.json` supplies the *depths* and
the growth curve. Nothing here invents a depth value.

One number is tuned rather than derived: `PEAK_STAGE_M` (default 4.0 m) sets
how far the water spreads at full flood. The canonical depths are road-surface
depths in centimetres, which on real terrain would inundate almost nothing, so
the stage is scaled to the scenario's own progression. Override `PEAK_STAGE_M`
or `CHANNEL_THRESHOLD` to retune without editing the script.

### Reverting

The original hand-authored surface is preserved at
`flood-polygons.curated-v1.geojson` and can be restored at any time:

```bash
npm run flood:restore
```

Both surfaces satisfy the fixture contract and the scenario test suite.

### Boundaries

The polygons are not inputs to road closure, routing, isolation, or response
plan scoring. Those results continue to use the asset-level depths in
`flood-frames.json`.

The DEM is [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/)
(public domain / open data, no key required), used here only to shape a
synthetic demonstration surface.

## Road network geometry

`road-network.geojson` is authored as twelve straight lines between abstract
nodes. Over a satellite basemap that reads as a rectangle drawn on a city, so
the drawn geometry is reshaped to follow real streets:

```bash
npm run network:snap
```

`scripts/snap-network-to-streets.mjs` reads the OpenStreetMap `roads` layer out
of the basemap PMTiles archive the app already ships, builds a graph of street
segments, snaps each scenario node to the nearest real street vertex (13–58 m
in practice), and routes each edge along that graph. Bridge assets take only
the stretch of their route that crosses the modeled flood corridor, trimmed to
a ~200 m span, so a bridge is drawn as a bridge rather than as the whole drive.

**Topology is unchanged.** Same edge IDs, same from/to nodes, same
`baseline_travel_minutes`, closure thresholds and criticality. Routing scores
edges from those fixture values and never reads geometry, so no domain result
moves. Edges whose street route would be an implausible detour keep their
straight line.

The authored straight-line network and matching asset positions are preserved
at `road-network.straight-v1.geojson` and `assets.straight-v1.geojson`:

```bash
npm run network:restore
```

Street geometry is © OpenStreetMap contributors (ODbL), read from the same
archive documented under the basemap in the project README.

## Administrative context boundaries

`context-boundaries.geojson` contains two administrative polygons used only to place the synthetic Kantipur River scenario in a recognizable geographic context:

- Kathmandu Metropolitan City
- Lalitpur Metropolitan City

The polygons do not define the scenario river, communities, roads, bridges, hospital, shelters, flood state, routing graph, or safety rules. They must not be read by the routing, physics, or scenario-scoring services as domain inputs.

### Provenance

- Repository: [Acesmndr/nepal-geojson](https://github.com/Acesmndr/nepal-geojson)
- Pinned commit: [`0e084221686fba8a4a8c1590661367676e96e473`](https://github.com/Acesmndr/nepal-geojson/commit/0e084221686fba8a4a8c1590661367676e96e473)
- Retrieved: 2026-09-18
- Source files:
  - `highres-geojson/Kathmandu-District.geojson`
  - `highres-geojson/Lalitpur-District.geojson`
- Selected source features: `FIRST_GaPa == "Kathmandu"` and `FIRST_GaPa == "Lalitpur"`
- Upstream data note: the source repository states that its high-resolution files were scraped from `https://sthaniya.gov.np/`.

### Transformations

- Retained the source polygon coordinates without manual geometry edits.
- Removed unrelated municipalities and source-specific attributes.
- Added stable context IDs and explicit flags excluding the features from routing and flood calculations.
- Added collection-level provenance, classification, and operational-use metadata.
- Added a bounding box covering both retained features.

These boundaries are a pinned visual reference, not a live administrative feed. Their current accuracy has not been independently verified.

## Upstream license notice

The source repository distributes its content under the MIT License:

> MIT License
>
> Copyright (c) 2018 Aashish Manandhar
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

Before public redistribution, confirm that use of the underlying government-sourced geometry is compatible with the project's intended distribution.
