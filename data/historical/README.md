# Historical flood learning data

`nepal_flood_events.csv` is generated from the UNDRR DesInventar Nepal export.
It contains normalized historical FLOOD datacards from 1971 through 2013.

The raw archive is not committed. Recreate the dataset with:

```bash
PYTHONPATH=services/physics/src python3 -m the_arc_physics.cli \
  ingest-desinventar \
  --source /path/to/DI_export_npl.zip \
  --output data/historical/nepal_flood_events.csv
```

This dataset trains an event-level impact prior. It does not contain flood-depth
rasters or street-level inundation labels. Satellite-derived flood extents must
be added as a separate dataset and evaluated with spatial metrics such as IoU.

