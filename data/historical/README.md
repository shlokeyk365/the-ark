# Historical flood learning data

The model-ready dataset is `nepal_flood_episodes_enriched.csv`. It contains
4,869 municipality/location flood episodes from 1971 through 2023. The episode
builder consolidates 5,349 administrative reports that share the same source,
date, district, municipality, and cause so one flood cannot receive many times
the training weight simply because it produced multiple report rows.

The source reports comprise:

- 3,953 UNDRR DesInventar records from 1971–2013; and
- 1,396 verified or approved BIPAD incidents from 2014–2023.

The enriched episode table includes NASA POWER rainfall, official 2011 census
exposure, district geography, local elevation/relief, HydroBASINS catchments,
and nearest HydroRIVERS reach characteristics. The source-level and intermediate
tables remain committed for provenance and reproducibility.

`nepal_hydrology_index.json` is a compact Nepal-only derivative of official
HydroBASINS level 6 and HydroRIVERS Asia shapefiles. It contains 54 intersecting
basin polygons and 18,242 Nepal river reaches. The original Asia archives are
not committed.

## Label harmonization

Each target has a `*_known` field. Unknown labels are excluded from that
target's loss and metrics rather than silently becoming negative examples.
BIPAD transport values were uniformly zero, so all BIPAD transport labels are
unknown.

The severe-impact label uses deaths/missing people or at least 10 damaged
homes. `people_affected` is intentionally excluded because every imported BIPAD
record reported zero for that field while DesInventar frequently populated it.
This reduces an avoidable source-definition mismatch.

## Leakage controls

- The September 2024 Nakkhu event is excluded from training and selection.
- All 2024-or-later BIPAD records are rejected by the importer.
- Validation separately holds out complete years, districts, level-6 basins,
  and four-day nationwide storm windows.
- City, district, and basin identity are not predictors.
- Historical/current district aliases share the same validation group.
- The Nakkhu classification threshold remains fixed at 0.5 and is not tuned
  after viewing the holdout.

The dataset is event-level, not a street-level inundation dataset. It does not
contain flood-depth rasters, river-stage histories, road arrival times, or
satellite flood/non-flood pixels.

## Rebuild sequence

Run from the repository root after installing the physics service. Hydrology
construction requires the official HydroBASINS level-6 Asia and HydroRIVERS
Asia shapefiles.

```bash
PYTHONPATH=services/physics/src .venv/bin/python -m the_arc_physics.cli \
  merge-events \
  --inputs data/historical/nepal_flood_events.csv \
           data/historical/nepal_bipad_flood_events_2014_2023.csv \
  --output data/historical/nepal_flood_events_1971_2023.csv

PYTHONPATH=services/physics/src .venv/bin/python -m the_arc_physics.cli \
  consolidate-events \
  --data data/historical/nepal_flood_events_1971_2023.csv \
  --output data/historical/nepal_flood_episodes_1971_2023.csv

PYTHONPATH=services/physics/src .venv/bin/python -m the_arc_physics.cli \
  build-hydrology \
  --basins /path/to/hybas_as_lev06_v1c.shp \
  --rivers /path/to/HydroRIVERS_v10_as.shp \
  --boundaries data/historical/nepal_district_boundaries.geojson \
  --output data/historical/nepal_hydrology_index.json

PYTHONPATH=services/physics/src .venv/bin/python -m the_arc_physics.cli \
  enrich-events \
  --data data/historical/nepal_flood_episodes_1971_2023.csv \
  --geography data/historical/nepal_district_geography.csv \
  --population data/historical/nepal_district_population_2011.csv \
  --weather-cache data/raw/nasa_power \
  --hydrology data/historical/nepal_hydrology_index.json \
  --terrain-cache data/raw/local_terrain.json \
  --output data/historical/nepal_flood_episodes_enriched.csv
```
