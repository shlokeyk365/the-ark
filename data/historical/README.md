# Historical flood learning data

The model-ready dataset is `nepal_flood_events_enriched.csv`. It contains 5,349
Nepal flood records from 1971 through 2023:

- 3,953 UNDRR DesInventar event records from 1971–2013;
- 1,396 verified or approved BIPAD flood incidents from 2014–2023;
- NASA POWER antecedent rainfall where available from 1981 onward;
- 2011 census population, household, and density features; and
- district area, elevation, and terrain-relief features.

`nepal_flood_events_1971_2023.csv` is the combined event table before physical
and exposure enrichment. The smaller geography, population, and boundary files
are committed inputs used to reproduce enrichment. API response caches live in
ignored `data/raw/` directories.

The dataset is event-level, not a street-level inundation dataset. It does not
contain flood-depth rasters, river-stage time series, road-network arrival
times, or satellite flood/non-flood pixels. Those require separate spatial
models and separate evaluation metrics.

## Label handling

Each target has a `*_known` field. Unknown labels are excluded from that
target's loss and metrics instead of silently becoming negative examples. This
matters for BIPAD transport loss, whose imported road values were all zero and
therefore could not support a reliable negative label.

## Leakage controls

- The September 2024 Nakkhu event is excluded from all training and selection.
- All 2024-or-later BIPAD records are rejected by the importer.
- Validation holds out complete years and, separately, complete normalized
  districts.
- City and district identity are retained only for audit and validation groups;
  they are not model predictors.
- Historical/current district aliases are assigned to the same validation
  group.

See `sources.json` for provenance and limitations.

## Rebuild sequence

Run commands from the repository root after installing the physics service.
The BIPAD, elevation, and weather steps use public APIs.

```bash
PYTHONPATH=services/physics/src python3 -m the_arc_physics.cli ingest-desinventar \
  --source /path/to/DI_export_npl.zip \
  --output data/historical/nepal_flood_events.csv

PYTHONPATH=services/physics/src python3 -m the_arc_physics.cli ingest-bipad \
  --historical-data data/historical/nepal_flood_events.csv \
  --cache data/raw/bipad \
  --output data/historical/nepal_bipad_flood_events_2014_2023.csv

PYTHONPATH=services/physics/src python3 -m the_arc_physics.cli merge-events \
  --inputs data/historical/nepal_flood_events.csv \
           data/historical/nepal_bipad_flood_events_2014_2023.csv \
  --output data/historical/nepal_flood_events_1971_2023.csv

PYTHONPATH=services/physics/src python3 -m the_arc_physics.cli enrich-events \
  --data data/historical/nepal_flood_events_1971_2023.csv \
  --geography data/historical/nepal_district_geography.csv \
  --population data/historical/nepal_district_population_2011.csv \
  --weather-cache data/raw/nasa_power \
  --output data/historical/nepal_flood_events_enriched.csv
```
