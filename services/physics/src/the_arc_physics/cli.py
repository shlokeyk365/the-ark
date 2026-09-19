"""CLI for historical flood ingestion, training, and holdout evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from .desinventar import read_desinventar_floods
from .features import EventInput
from .integration import simulation_impact_prior
from .model import MultiLabelFloodImpactModel
from .pipeline import evaluate_locked_holdout, train_and_evaluate
from .records import read_records, write_records


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="the-arc-flood-model")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest-desinventar")
    ingest.add_argument("--source", type=Path, required=True)
    ingest.add_argument("--output", type=Path, required=True)

    train = subparsers.add_parser("train")
    train.add_argument("--data", type=Path, required=True)
    train.add_argument("--model", type=Path, required=True)
    train.add_argument("--report", type=Path, required=True)

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
    if args.command == "train":
        report = train_and_evaluate(
            read_records(args.data), args.model, args.report
        )
        print(json.dumps(report["cross_validation"]["overall"], indent=2))
        return 0

    if args.command == "evaluate-holdout":
        result = evaluate_locked_holdout(
            MultiLabelFloodImpactModel.load(args.model), args.holdout
        )
    else:
        event_payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = simulation_impact_prior(
            MultiLabelFloodImpactModel.load(args.model),
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
