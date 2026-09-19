"""CLI for historical flood ingestion, training, and holdout evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from .desinventar import read_desinventar_floods
from .benchmark import benchmark_models
from .bipad import read_bipad_floods
from .enrichment import enrich_records
from .episodes import consolidate_event_reports
from .ensemble_model import EnsembleFloodImpactModel, load_flood_model
from .features import EventInput
from .geography import (
    add_elevation_samples,
    build_district_geography,
    read_district_geography,
    write_district_geography,
)
from .hydrography import HydrologyIndex, build_nepal_hydrology_index
from .integration import simulation_impact_prior
from .model import MultiLabelFloodImpactModel
from .pipeline import (
    combined_validation_gate,
    evaluate_locked_holdout,
    train_and_evaluate,
)
from .population import read_district_population
from .records import read_records, write_records


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="the-arc-flood-model")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest-desinventar")
    ingest.add_argument("--source", type=Path, required=True)
    ingest.add_argument("--output", type=Path, required=True)

    bipad = subparsers.add_parser("ingest-bipad")
    bipad.add_argument("--historical-data", type=Path, required=True)
    bipad.add_argument("--cache", type=Path, required=True)
    bipad.add_argument("--output", type=Path, required=True)
    bipad.add_argument("--start-year", type=int, default=2014)
    bipad.add_argument("--end-year", type=int, default=2023)

    merge = subparsers.add_parser("merge-events")
    merge.add_argument("--inputs", type=Path, nargs="+", required=True)
    merge.add_argument("--output", type=Path, required=True)

    consolidate = subparsers.add_parser("consolidate-events")
    consolidate.add_argument("--data", type=Path, required=True)
    consolidate.add_argument("--output", type=Path, required=True)

    geography = subparsers.add_parser("build-geography")
    geography.add_argument("--boundaries", type=Path, required=True)
    geography.add_argument("--output", type=Path, required=True)
    geography.add_argument("--fetch-elevation", action="store_true")

    hydrography = subparsers.add_parser("build-hydrology")
    hydrography.add_argument("--basins", type=Path, required=True)
    hydrography.add_argument("--rivers", type=Path, required=True)
    hydrography.add_argument("--boundaries", type=Path, required=True)
    hydrography.add_argument("--output", type=Path, required=True)

    enrich = subparsers.add_parser("enrich-events")
    enrich.add_argument("--data", type=Path, required=True)
    enrich.add_argument("--geography", type=Path, required=True)
    enrich.add_argument("--population", type=Path, required=True)
    enrich.add_argument("--weather-cache", type=Path, required=True)
    enrich.add_argument("--hydrology", type=Path)
    enrich.add_argument("--terrain-cache", type=Path)
    enrich.add_argument("--output", type=Path, required=True)
    enrich.add_argument("--weather-end-year", type=int, default=2024)

    train = subparsers.add_parser("train")
    train.add_argument("--data", type=Path, required=True)
    train.add_argument("--model", type=Path, required=True)
    train.add_argument("--report", type=Path, required=True)

    benchmark = subparsers.add_parser("benchmark")
    benchmark.add_argument("--data", type=Path, required=True)
    benchmark.add_argument("--output", type=Path, required=True)

    train_ensemble = subparsers.add_parser("train-ensemble")
    train_ensemble.add_argument("--data", type=Path, required=True)
    train_ensemble.add_argument("--benchmark", type=Path, required=True)
    train_ensemble.add_argument("--model", type=Path, required=True)

    train_selected = subparsers.add_parser("train-selected")
    train_selected.add_argument("--data", type=Path, required=True)
    train_selected.add_argument("--benchmark", type=Path, required=True)
    train_selected.add_argument("--model", type=Path, required=True)

    holdout = subparsers.add_parser("evaluate-holdout")
    holdout.add_argument("--model", type=Path, required=True)
    holdout.add_argument("--holdout", type=Path, required=True)
    holdout.add_argument("--output", type=Path)

    predict = subparsers.add_parser("predict-event")
    predict.add_argument("--model", type=Path, required=True)
    predict.add_argument("--input", type=Path, required=True)
    predict.add_argument("--output", type=Path)

    args = parser.parse_args(argv)
    if args.command == "ingest-desinventar":
        count = write_records(args.output, read_desinventar_floods(args.source))
        print(json.dumps({"records_written": count, "output": str(args.output)}))
        return 0
    if args.command == "ingest-bipad":
        historical = read_records(args.historical_data)
        count = write_records(
            args.output,
            read_bipad_floods(
                args.cache,
                historical,
                start_year=args.start_year,
                end_year=args.end_year,
            ),
        )
        print(json.dumps({"records_written": count, "output": str(args.output)}))
        return 0
    if args.command == "merge-events":
        records = [
            record
            for input_path in args.inputs
            for record in read_records(input_path)
        ]
        event_ids = [record.event_id for record in records]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("cannot merge datasets with duplicate event IDs")
        count = write_records(args.output, records)
        print(json.dumps({"records_written": count, "output": str(args.output)}))
        return 0
    if args.command == "consolidate-events":
        source_records = read_records(args.data)
        episodes = consolidate_event_reports(source_records)
        count = write_records(args.output, episodes)
        print(
            json.dumps(
                {
                    "source_records": len(source_records),
                    "episodes_written": count,
                    "reports_consolidated": len(source_records) - count,
                    "output": str(args.output),
                }
            )
        )
        return 0
    if args.command == "build-geography":
        rows = build_district_geography(args.boundaries)
        if args.fetch_elevation:
            rows = add_elevation_samples(rows)
        write_district_geography(args.output, rows)
        print(json.dumps({"districts_written": len(rows), "output": str(args.output)}))
        return 0
    if args.command == "build-hydrology":
        counts = build_nepal_hydrology_index(
            args.basins, args.rivers, args.boundaries, args.output
        )
        print(json.dumps({**counts, "output": str(args.output)}))
        return 0
    if args.command == "enrich-events":
        count = write_records(
            args.output,
            enrich_records(
                read_records(args.data),
                read_district_geography(args.geography),
                read_district_population(args.population),
                args.weather_cache,
                hydrology=(
                    HydrologyIndex.load(args.hydrology) if args.hydrology else None
                ),
                terrain_cache=args.terrain_cache,
                weather_end_year=args.weather_end_year,
            ),
        )
        print(json.dumps({"records_written": count, "output": str(args.output)}))
        return 0
    if args.command == "train":
        report = train_and_evaluate(
            read_records(args.data), args.model, args.report
        )
        print(json.dumps(report["cross_validation"]["overall"], indent=2))
        return 0
    if args.command == "benchmark":
        report = benchmark_models(read_records(args.data), args.output)
        summary = {
            name: value["selection_summary"]
            for name, value in report["candidates"].items()
        }
        print(json.dumps({"selected": report["selected_model"], **summary}, indent=2))
        return 0
    if args.command in {"train-ensemble", "train-selected"}:
        benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
        selected_name = benchmark["selected_model"]
        selected = benchmark["candidates"][selected_name]
        validation_gate = combined_validation_gate(
            selected["year_grouped"],
            selected["district_grouped"],
            selected.get("basin_grouped"),
            selected.get("storm_grouped"),
        )
        model = EnsembleFloodImpactModel.fit(
            read_records(args.data),
            validation_gate=validation_gate,
            model_name=selected_name,
        )
        model.save(args.model)
        print(json.dumps(dict(model.training_metadata), indent=2))
        return 0

    if args.command == "evaluate-holdout":
        result = evaluate_locked_holdout(
            load_flood_model(args.model), args.holdout
        )
    else:
        event_payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = simulation_impact_prior(
            load_flood_model(args.model),
            event_payload["eventId"],
            EventInput(**event_payload["modelInput"]),
        )
    serialized = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
