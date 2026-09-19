from pathlib import Path

from fastapi.testclient import TestClient

import apps.api.main as api_main
from apps.api.models import SimulationReport, SimulationRun, SimulationRunSummary
from services.reports import ReportRepository, SimulationReportService
from services.scenarios import ScenarioService


FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scenarios"
    / "kantipur-river"
)


def _report_service(database_path: Path) -> SimulationReportService:
    return SimulationReportService(
        ScenarioService(FIXTURE_DIRECTORY), ReportRepository(database_path)
    )


def test_baseline_run_creates_a_durable_deterministic_report(tmp_path: Path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    service = _report_service(database_path)

    run = service.create_run([])
    SimulationRun.model_validate(run)
    report = run["report"]
    SimulationReport.model_validate(report)

    assert len(run["snapshots"]) == 4
    assert report["summary"] == {
        "peak_flood_depth_m": 0.39,
        "peak_isolated_people": 620,
        "peak_isolated_communities": 1,
        "peak_critical_routes_lost": 2,
        "first_isolation_hours": 24.0,
        "viable_plans_at_horizon": 0,
    }
    assert report["provenance"]["impact_prior_used"] is False
    assert len(report["provenance"]["input_fingerprint"]) == 64

    reopened = _report_service(database_path)
    persisted = reopened.get_report(run["report_id"])
    assert persisted == report
    assert reopened.get_run(run["run_id"]) == run


def test_event_report_explains_accelerated_isolation(tmp_path: Path) -> None:
    service = _report_service(tmp_path / "reports.sqlite3")
    run = service.create_run(["ktp-event-bridge-02-failure"])
    report = run["report"]

    riverbend = next(
        item
        for item in report["community_impacts"]
        if item["community_id"] == "ktp-com-05"
    )
    assert riverbend["first_isolated_at_hours"] == 12.0
    assert any(
        change["comparison"] == "baseline_counterfactual"
        and change["subject_id"] == "ktp-com-05"
        and "earlier" in change["description"]
        for change in report["changes"]
    )
    assert len({change["change_id"] for change in report["changes"]}) == len(
        report["changes"]
    )
    assert any(
        "from +24h in the baseline to +12h" in item
        for item in report["narrative"]
    )
    assert all(
        not plan["horizon_metrics"]["plan_viable"]
        for plan in report["plan_analysis"]
    )


def test_report_exports_use_stored_findings(tmp_path: Path) -> None:
    service = _report_service(tmp_path / "reports.sqlite3")
    run = service.create_run([])

    json_export = service.export(run["report_id"], "json")
    csv_export = service.export(run["report_id"], "csv")
    html_export = service.export(run["report_id"], "html")

    assert json_export and run["report_id"] in json_export[0]
    assert csv_export and "section,subject_id,metric" in csv_export[0]
    assert html_export and "Print or save as PDF" in html_export[0]


def test_report_api_creates_lists_reads_and_exports_runs(
    tmp_path: Path, monkeypatch
) -> None:
    service = _report_service(tmp_path / "api-reports.sqlite3")
    monkeypatch.setattr(api_main, "simulation_report_service", service)
    client = TestClient(api_main.app)

    created = client.post(
        "/scenarios/kantipur-river/runs",
        json={"event_ids": ["ktp-event-bridge-02-failure"]},
    )
    assert created.status_code == 200
    run = created.json()
    SimulationRun.model_validate(run)

    listed = client.get("/scenarios/kantipur-river/runs")
    assert listed.status_code == 200
    summaries = [SimulationRunSummary.model_validate(item) for item in listed.json()]
    assert [item.run_id for item in summaries] == [run["run_id"]]

    detail = client.get(f"/reports/{run['report_id']}")
    assert detail.status_code == 200
    SimulationReport.model_validate(detail.json())

    exported = client.get(
        f"/reports/{run['report_id']}/export", params={"format": "csv"}
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "attachment" in exported.headers["content-disposition"]

    assert client.get("/reports/report-missing").status_code == 404
    assert client.post(
        "/scenarios/kantipur-river/runs", json={"event_ids": ["missing-event"]}
    ).status_code == 404
