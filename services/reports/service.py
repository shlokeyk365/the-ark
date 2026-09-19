"""Orchestrate frozen scenario runs, deterministic reports, and persistence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from services.reports.builder import build_report, export_report
from services.reports.repository import ReportRepository
from services.scenarios import ScenarioService

JsonObject = Dict[str, Any]

FIXTURE_FILES = (
    "scenario.json",
    "assets.geojson",
    "road-network.geojson",
    "flood-frames.json",
    "response-plans.json",
    "event-stream.json",
    "context-boundaries.geojson",
)

OPTIONAL_FIXTURE_FILES = ("flood-polygons.geojson",)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_files(directory: Path, filenames: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for filename in sorted(filenames):
        digest.update(filename.encode("utf-8"))
        digest.update((directory / filename).read_bytes())
    return digest.hexdigest()


class SimulationReportService:
    """Create one durable report for every explicit full-horizon run."""

    def __init__(
        self,
        scenario_service: ScenarioService,
        repository: ReportRepository,
    ) -> None:
        self.scenario_service = scenario_service
        self.repository = repository

    def create_run(self, event_ids: Iterable[str] = ()) -> JsonObject:
        started_at = _utc_now()
        events = self.scenario_service._events(event_ids)
        canonical_event_ids = [event["event_id"] for event in events]
        fixture_files = list(FIXTURE_FILES)
        fixture_files.extend(
            filename
            for filename in OPTIONAL_FIXTURE_FILES
            if (self.scenario_service.fixture_directory / filename).exists()
        )
        fixture_sha256 = _sha256_files(
            self.scenario_service.fixture_directory, fixture_files
        )
        impact_prior_path = (
            self.scenario_service.fixture_directory / "model-impact-prior.json"
        )
        impact_prior_sha256: Optional[str] = None
        if impact_prior_path.exists():
            impact_prior_sha256 = hashlib.sha256(
                impact_prior_path.read_bytes()
            ).hexdigest()

        run_input = {
            "scenario_id": self.scenario_service.manifest["scenario_id"],
            "event_ids": canonical_event_ids,
            "evaluation_horizon_hours": self.scenario_service.manifest[
                "evaluation_horizon_hours"
            ],
            "fixture_sha256": fixture_sha256,
            "impact_prior_sha256": impact_prior_sha256,
            "impact_prior_used": False,
        }
        fingerprint_source = {
            "scenario_id": run_input["scenario_id"],
            "event_ids": run_input["event_ids"],
            "evaluation_horizon_hours": run_input["evaluation_horizon_hours"],
            "fixture_sha256": fixture_sha256,
            "engine_version": "reports-1.0.0",
        }
        input_fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_source, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        ).hexdigest()

        snapshots: List[JsonObject] = []
        reference_snapshots: List[JsonObject] = []
        for frame in self.scenario_service.flood_frames["frames"]:
            active_event_ids = [
                event["event_id"]
                for event in events
                if event["effective_at_hours"] <= frame["simulation_time_hours"]
            ]
            snapshots.append(
                self.scenario_service.build_world_state(
                    frame["frame_id"], active_event_ids
                )
            )
            reference_snapshots.append(
                self.scenario_service.build_world_state(frame["frame_id"])
            )

        run_id = f"run-{uuid4()}"
        report_id = f"report-{uuid4()}"
        completed_at = _utc_now()
        report = build_report(
            run_id=run_id,
            report_id=report_id,
            generated_at=completed_at,
            input_fingerprint=input_fingerprint,
            fixture_sha256=fixture_sha256,
            impact_prior_sha256=impact_prior_sha256,
            scenario=self.scenario_service.manifest,
            assets=self.scenario_service.assets,
            plans=self.scenario_service.response_plans["plans"],
            events=events,
            snapshots=snapshots,
            reference_snapshots=reference_snapshots,
        )
        run = {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "report_id": report_id,
            "scenario_id": self.scenario_service.manifest["scenario_id"],
            "status": "completed",
            "started_at": started_at,
            "completed_at": completed_at,
            "input": run_input,
            "input_fingerprint": input_fingerprint,
            "snapshots": snapshots,
            "report": report,
        }
        self.repository.save_run(run)
        return run

    def list_runs(self, limit: int = 50) -> List[JsonObject]:
        return [self._summary(run) for run in self.repository.list_runs(limit)]

    def get_run(self, run_id: str) -> Optional[JsonObject]:
        return self.repository.get_run(run_id)

    def get_report(self, report_id: str) -> Optional[JsonObject]:
        return self.repository.get_report(report_id)

    def export(self, report_id: str, export_format: str) -> Optional[Tuple[str, str, str]]:
        report = self.get_report(report_id)
        return export_report(report, export_format) if report else None

    @staticmethod
    def _summary(run: JsonObject) -> JsonObject:
        report = run["report"]
        return {
            "run_id": run["run_id"],
            "report_id": run["report_id"],
            "scenario_id": run["scenario_id"],
            "status": run["status"],
            "completed_at": run["completed_at"],
            "title": report["title"],
            "event_ids": run["input"]["event_ids"],
            "input_fingerprint": run["input_fingerprint"],
            "summary": report["summary"],
        }
