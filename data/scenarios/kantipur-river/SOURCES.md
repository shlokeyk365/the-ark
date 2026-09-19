# Nakkhu River scenario data sources

## Historical-event impact prior

`model-impact-prior.json` is the frozen Nakkhu 2024 input/output artifact from
the repository's CatBoost training pipeline. The model was trained on 4,869
historical Nepal flood events through 2023 with city, district, and basin
identity excluded from predictors. Its status is `research_only`; the artifact
records grouped ROC-AUC/RMSE evaluation and known limitations.

`prediction-pings.json` adds presentation coordinates, nearby network-edge
references, activation hours, and recommended actions for the four
probabilities. The edge references let the scenario service adjust displayed
risk using already-modeled local flood depth; they do not alter that depth or
routing. The coordinates are map anchors and are not evidence of parcel- or
building-level prediction.

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
