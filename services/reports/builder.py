"""Deterministic analysis and export rendering for completed simulation runs."""

from __future__ import annotations

import csv
import html
import io
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

JsonObject = Dict[str, Any]


def _asset_indexes(assets: Mapping[str, Any]) -> Tuple[Dict[str, str], Dict[str, int]]:
    names: Dict[str, str] = {}
    populations: Dict[str, int] = {}
    for feature in assets["features"]:
        properties = feature["properties"]
        asset_id = properties["id"]
        names[asset_id] = properties["name"]
        if properties["asset_type"] == "community":
            populations[asset_id] = int(properties["population"])
        if properties["asset_type"] == "bridge":
            names[properties["edge_id"]] = properties["name"]
    return names, populations


def _subject_name(names: Mapping[str, str], subject_id: str) -> str:
    if subject_id in names:
        return names[subject_id]
    if subject_id.startswith("ktp-road-"):
        return f"Road {subject_id.removeprefix('ktp-road-')}"
    if subject_id.startswith("ktp-bridge-"):
        return f"Bridge {subject_id.removeprefix('ktp-bridge-')}"
    return subject_id


def _by_id(items: Iterable[Mapping[str, Any]], key: str) -> Dict[str, Mapping[str, Any]]:
    return {str(item[key]): item for item in items}


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "not available"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _change(
    changes: List[JsonObject],
    *,
    at_hours: float,
    category: str,
    subject_id: str,
    subject_name: str,
    description: str,
    before: Any,
    after: Any,
    comparison: str,
    source_event_id: Optional[str] = None,
) -> None:
    changes.append(
        {
            "change_id": f"change-{len(changes) + 1:04d}",
            "at_hours": at_hours,
            "category": category,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "description": description,
            "before_value": _value(before),
            "after_value": _value(after),
            "comparison": comparison,
            "source_event_id": source_event_id,
        }
    )


def _timeline_changes(
    snapshots: Sequence[Mapping[str, Any]], names: Mapping[str, str]
) -> List[JsonObject]:
    changes: List[JsonObject] = []
    for previous, current in zip(snapshots, snapshots[1:]):
        hours = float(current["simulation_time_hours"])
        previous_edges = _by_id(previous["edge_states"], "edge_id")
        for edge in current["edge_states"]:
            before = previous_edges[edge["edge_id"]]
            if before["status"] != edge["status"]:
                subject_name = _subject_name(names, edge["edge_id"])
                _change(
                    changes,
                    at_hours=hours,
                    category="infrastructure",
                    subject_id=edge["edge_id"],
                    subject_name=subject_name,
                    description=(
                        f"{subject_name} changed from {before['status']} to {edge['status']}."
                    ),
                    before=before["status"],
                    after=edge["status"],
                    comparison="timeline",
                    source_event_id=edge["originating_event_id"],
                )

        previous_access = _by_id(previous["community_access"], "community_id")
        for access in current["community_access"]:
            before = previous_access[access["community_id"]]
            community_name = _subject_name(names, access["community_id"])
            if before["isolated"] != access["isolated"]:
                _change(
                    changes,
                    at_hours=hours,
                    category="community",
                    subject_id=access["community_id"],
                    subject_name=community_name,
                    description=(
                        f"{community_name} became isolated from every open shelter and the hospital."
                        if access["isolated"]
                        else f"{community_name} regained a safe route."
                    ),
                    before=before["isolated"],
                    after=access["isolated"],
                    comparison="timeline",
                    source_event_id=(current["active_event_ids"] or [None])[0],
                )
            if before["hospital_accessible"] != access["hospital_accessible"]:
                _change(
                    changes,
                    at_hours=hours,
                    category="community",
                    subject_id=access["community_id"],
                    subject_name=community_name,
                    description=(
                        f"{community_name} lost hospital access."
                        if not access["hospital_accessible"]
                        else f"{community_name} regained hospital access."
                    ),
                    before=before["hospital_accessible"],
                    after=access["hospital_accessible"],
                    comparison="timeline",
                    source_event_id=(current["active_event_ids"] or [None])[0],
                )

        previous_plans = _by_id(previous["plan_results"], "plan_id")
        for plan in current["plan_results"]:
            before_metrics = previous_plans[plan["plan_id"]]["metrics"]
            metrics = plan["metrics"]
            if (
                before_metrics["people_evacuated_by_deadline"]
                != metrics["people_evacuated_by_deadline"]
            ):
                _change(
                    changes,
                    at_hours=hours,
                    category="plan",
                    subject_id=plan["plan_id"],
                    subject_name=plan["plan_name"],
                    description=(
                        f"{plan['plan_name']} changed its evacuation-by-deadline outcome."
                    ),
                    before=before_metrics["people_evacuated_by_deadline"],
                    after=metrics["people_evacuated_by_deadline"],
                    comparison="timeline",
                    source_event_id=(current["active_event_ids"] or [None])[0],
                )
            if before_metrics["plan_viable"] != metrics["plan_viable"]:
                _change(
                    changes,
                    at_hours=hours,
                    category="plan",
                    subject_id=plan["plan_id"],
                    subject_name=plan["plan_name"],
                    description=(
                        f"{plan['plan_name']} no longer satisfies every hard route and capacity constraint."
                        if not metrics["plan_viable"]
                        else f"{plan['plan_name']} became viable."
                    ),
                    before=before_metrics["plan_viable"],
                    after=metrics["plan_viable"],
                    comparison="timeline",
                    source_event_id=(current["active_event_ids"] or [None])[0],
                )
    return changes


def _event_effect_changes(
    snapshots: Sequence[Mapping[str, Any]],
    reference_snapshots: Sequence[Mapping[str, Any]],
    names: Mapping[str, str],
) -> List[JsonObject]:
    changes: List[JsonObject] = []
    references = {state["frame_id"]: state for state in reference_snapshots}
    for current in snapshots:
        if not current["active_event_ids"]:
            continue
        reference = references[current["frame_id"]]
        hours = float(current["simulation_time_hours"])
        event_id = current["active_event_ids"][0]
        baseline_edges = _by_id(reference["edge_states"], "edge_id")
        for edge in current["edge_states"]:
            baseline = baseline_edges[edge["edge_id"]]
            if baseline["status"] != edge["status"]:
                subject_name = _subject_name(names, edge["edge_id"])
                _change(
                    changes,
                    at_hours=hours,
                    category="event",
                    subject_id=edge["edge_id"],
                    subject_name=subject_name,
                    description=(
                        f"Injected event changed {subject_name} from its baseline "
                        f"{baseline['status']} state to {edge['status']}."
                    ),
                    before=baseline["status"],
                    after=edge["status"],
                    comparison="baseline_counterfactual",
                    source_event_id=event_id,
                )

        baseline_access = _by_id(reference["community_access"], "community_id")
        for access in current["community_access"]:
            baseline = baseline_access[access["community_id"]]
            if not baseline["isolated"] and access["isolated"]:
                community_name = _subject_name(names, access["community_id"])
                _change(
                    changes,
                    at_hours=hours,
                    category="event",
                    subject_id=access["community_id"],
                    subject_name=community_name,
                    description=(
                        f"Injected event isolated {community_name} earlier than the baseline projection."
                    ),
                    before=False,
                    after=True,
                    comparison="baseline_counterfactual",
                    source_event_id=event_id,
                )
    return changes


def build_report(
    *,
    run_id: str,
    report_id: str,
    generated_at: str,
    input_fingerprint: str,
    fixture_sha256: str,
    impact_prior_sha256: Optional[str],
    scenario: Mapping[str, Any],
    assets: Mapping[str, Any],
    plans: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    snapshots: Sequence[Mapping[str, Any]],
    reference_snapshots: Sequence[Mapping[str, Any]],
) -> JsonObject:
    """Build report prose and deltas entirely from frozen derived results."""

    names, populations = _asset_indexes(assets)
    first = snapshots[0]
    horizon = snapshots[-1]
    event_ids = [event["event_id"] for event in events]
    peak_depth = max(
        float(edge["flood_depth_m"])
        for state in snapshots
        for edge in state["edge_states"]
    )
    peak_isolated_communities = max(
        sum(1 for access in state["community_access"] if access["isolated"])
        for state in snapshots
    )
    peak_isolated_people = max(
        sum(
            populations[access["community_id"]]
            for access in state["community_access"]
            if access["isolated"]
        )
        for state in snapshots
    )
    peak_critical_routes = max(
        sum(
            1
            for edge in state["edge_states"]
            if edge["critical"] and edge["status"] == "closed"
        )
        for state in snapshots
    )
    isolation_hours = [
        float(state["simulation_time_hours"])
        for state in snapshots
        if any(access["isolated"] for access in state["community_access"])
    ]
    first_isolation = min(isolation_hours) if isolation_hours else None
    viable_at_horizon = sum(
        1 for result in horizon["plan_results"] if result["metrics"]["plan_viable"]
    )

    changes = _timeline_changes(snapshots, names)
    changes.extend(_event_effect_changes(snapshots, reference_snapshots, names))
    changes.sort(
        key=lambda item: (
            item["at_hours"],
            0 if item["comparison"] == "baseline_counterfactual" else 1,
            item["change_id"],
        )
    )
    for index, change in enumerate(changes, start=1):
        change["change_id"] = f"change-{index:04d}"

    community_impacts: List[JsonObject] = []
    for access in first["community_access"]:
        community_id = access["community_id"]
        states = [
            _by_id(state["community_access"], "community_id")[community_id]
            for state in snapshots
        ]
        isolated_points = [
            float(state["simulation_time_hours"])
            for state, community in zip(snapshots, states)
            if community["isolated"]
        ]
        hospital_points = [
            float(state["simulation_time_hours"])
            for state, community in zip(snapshots, states)
            if not community["hospital_accessible"]
        ]
        final = states[-1]
        community_name = names[community_id]
        if isolated_points:
            analysis = (
                f"{community_name} first becomes isolated at +{min(isolated_points):g}h; "
                f"its modeled population is {populations[community_id]:,}."
            )
        elif hospital_points:
            analysis = (
                f"{community_name} retains shelter access but loses hospital access at "
                f"+{min(hospital_points):g}h."
            )
        else:
            analysis = (
                f"{community_name} retains access to an open shelter and the hospital "
                "through the modeled horizon."
            )
        community_impacts.append(
            {
                "community_id": community_id,
                "community_name": community_name,
                "population": populations[community_id],
                "first_isolated_at_hours": min(isolated_points) if isolated_points else None,
                "hospital_access_lost_at_hours": min(hospital_points) if hospital_points else None,
                "horizon_isolated": final["isolated"],
                "horizon_hospital_accessible": final["hospital_accessible"],
                "horizon_reachable_shelter_ids": final["reachable_shelter_ids"],
                "analysis": analysis,
            }
        )

    first_plans = _by_id(first["plan_results"], "plan_id")
    horizon_plans = _by_id(horizon["plan_results"], "plan_id")
    plan_analysis: List[JsonObject] = []
    for plan in plans:
        baseline_metrics = dict(first_plans[plan["plan_id"]]["metrics"])
        horizon_metrics = dict(horizon_plans[plan["plan_id"]]["metrics"])
        evacuated_change = (
            horizon_metrics["people_evacuated_by_deadline"]
            - baseline_metrics["people_evacuated_by_deadline"]
        )
        analysis = (
            f"{plan['name']} evacuates "
            f"{horizon_metrics['people_evacuated_by_deadline']:,} people by the deadline "
            f"at +{float(horizon['simulation_time_hours']):g}h and is "
            f"{'viable' if horizon_metrics['plan_viable'] else 'not viable'} under the "
            "modeled route and shelter constraints."
        )
        plan_analysis.append(
            {
                "plan_id": plan["plan_id"],
                "plan_name": plan["name"],
                "baseline_metrics": baseline_metrics,
                "horizon_metrics": horizon_metrics,
                "people_evacuated_change": evacuated_change,
                "people_isolated_change": (
                    horizon_metrics["people_isolated"]
                    - baseline_metrics["people_isolated"]
                ),
                "critical_routes_lost_change": (
                    horizon_metrics["critical_routes_lost"]
                    - baseline_metrics["critical_routes_lost"]
                ),
                "shelter_overload_change": (
                    horizon_metrics["shelter_overload"]
                    - baseline_metrics["shelter_overload"]
                ),
                "viability_changed": (
                    horizon_metrics["plan_viable"] != baseline_metrics["plan_viable"]
                ),
                "analysis": analysis,
            }
        )

    best_evacuated = max(
        result["metrics"]["people_evacuated_by_deadline"]
        for result in horizon["plan_results"]
    )
    narrative = [
        (
            f"Across the {float(horizon['simulation_time_hours']):g}-hour horizon, "
            f"modeled flood depth reaches {peak_depth:.2f} m on the routed network."
        ),
        (
            f"Peak isolation affects {peak_isolated_people:,} people across "
            f"{peak_isolated_communities} "
            f"{'communities' if peak_isolated_communities != 1 else 'community'}."
            if peak_isolated_communities
            else "No community becomes isolated during this run."
        ),
        (
            f"At the horizon, the strongest evacuation result moves {best_evacuated:,} "
            f"people by the deadline; {viable_at_horizon} of {len(plan_analysis)} plans "
            "satisfy every hard route and capacity constraint."
        ),
    ]
    if events:
        event_effects = [
            change
            for change in changes
            if change["comparison"] == "baseline_counterfactual"
        ]
        narrative.insert(
            1,
            (
                f"{len(events)} operator-injected event"
                f"{'s were' if len(events) != 1 else ' was'} applied; "
                f"{len(event_effects)} material differences from the baseline were identified."
            ),
        )
        reference_isolation_hours = [
            float(state["simulation_time_hours"])
            for state in reference_snapshots
            if any(access["isolated"] for access in state["community_access"])
        ]
        if first_isolation is not None and reference_isolation_hours:
            baseline_first_isolation = min(reference_isolation_hours)
            if first_isolation < baseline_first_isolation:
                narrative.insert(
                    2,
                    (
                        f"The injected event advances first community isolation from "
                        f"+{baseline_first_isolation:g}h in the baseline to "
                        f"+{first_isolation:g}h."
                    ),
                )

    assumptions = list(
        dict.fromkeys(
            [state["rainfall_assumption"] for state in snapshots]
            + [assumption for plan in plans for assumption in plan["assumptions"]]
        )
    )
    if events:
        assumptions.extend(
            f"Operator event {event['event_id']}: {event['description']} "
            f"(reliability: {event['reliability']})."
            for event in events
        )

    return {
        "schema_version": "1.0.0",
        "report_id": report_id,
        "run_id": run_id,
        "scenario_id": scenario["scenario_id"],
        "status": "completed",
        "generated_at": generated_at,
        "title": f"{scenario['name']} simulation report",
        "event_ids": event_ids,
        "summary": {
            "peak_flood_depth_m": peak_depth,
            "peak_isolated_people": peak_isolated_people,
            "peak_isolated_communities": peak_isolated_communities,
            "peak_critical_routes_lost": peak_critical_routes,
            "first_isolation_hours": first_isolation,
            "viable_plans_at_horizon": viable_at_horizon,
        },
        "narrative": narrative,
        "changes": changes,
        "community_impacts": community_impacts,
        "plan_analysis": plan_analysis,
        "assumptions": assumptions,
        "limitations": [
            "This run uses modeled synthetic demonstration data and is not operational guidance.",
            "Flood polygons are visual context; route safety is derived from canonical edge-level flood conditions.",
            "The historical impact prior is research-only and was not used to calculate routes, isolation, or plan scores.",
            "External news is situational context only and is not an input to this report.",
        ],
        "provenance": {
            "input_fingerprint": input_fingerprint,
            "fixture_sha256": fixture_sha256,
            "impact_prior_sha256": impact_prior_sha256,
            "impact_prior_used": False,
            "world_state_versions": [
                state["world_state_version"] for state in snapshots
            ],
            "engine_version": "reports-1.0.0",
            "data_classification": scenario["data_classification"],
            "operational_use": scenario["operational_use"],
        },
    }


def export_report(report: Mapping[str, Any], export_format: str) -> Tuple[str, str, str]:
    """Render one stored report without recalculating its findings."""

    safe_id = str(report["report_id"])
    if export_format == "json":
        return (
            json.dumps(report, indent=2, sort_keys=True),
            "application/json",
            f"{safe_id}.json",
        )

    if export_format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["section", "subject_id", "metric", "before", "after", "detail"])
        for change in report["changes"]:
            writer.writerow(
                [
                    "change",
                    change["subject_id"],
                    change["category"],
                    change["before_value"],
                    change["after_value"],
                    change["description"],
                ]
            )
        for plan in report["plan_analysis"]:
            for metric, value in plan["horizon_metrics"].items():
                writer.writerow(
                    ["plan", plan["plan_id"], metric, "", value, plan["analysis"]]
                )
        for community in report["community_impacts"]:
            writer.writerow(
                [
                    "community",
                    community["community_id"],
                    "first_isolated_at_hours",
                    "",
                    community["first_isolated_at_hours"],
                    community["analysis"],
                ]
            )
        return output.getvalue(), "text/csv; charset=utf-8", f"{safe_id}.csv"

    if export_format != "html":
        raise ValueError(f"Unsupported report export format: {export_format}")

    def escaped_list(items: Iterable[str]) -> str:
        return "".join(f"<li>{html.escape(str(item))}</li>" for item in items)

    summary = report["summary"]
    change_rows = "".join(
        "<tr>"
        f"<td>+{change['at_hours']:g}h</td>"
        f"<td>{html.escape(change['subject_name'])}</td>"
        f"<td>{html.escape(change['before_value'])}</td>"
        f"<td>{html.escape(change['after_value'])}</td>"
        f"<td>{html.escape(change['description'])}</td>"
        "</tr>"
        for change in report["changes"]
    )
    plan_rows = "".join(
        "<tr>"
        f"<td>{html.escape(plan['plan_name'])}</td>"
        f"<td>{plan['horizon_metrics']['people_evacuated_by_deadline']:,}</td>"
        f"<td>{plan['horizon_metrics']['people_isolated']:,}</td>"
        f"<td>{plan['horizon_metrics']['critical_routes_lost']}</td>"
        f"<td>{'Yes' if plan['horizon_metrics']['plan_viable'] else 'No'}</td>"
        "</tr>"
        for plan in report["plan_analysis"]
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(report['title'])}</title>
<style>
body{{font:14px/1.5 Arial,sans-serif;color:#172033;max-width:1050px;margin:32px auto;padding:0 24px}}
h1,h2{{color:#0c2740}} .meta{{color:#5b6b7c}} .metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
.metric{{border:1px solid #ccd7e2;border-radius:8px;padding:12px}} .metric strong{{display:block;font-size:24px}}
table{{width:100%;border-collapse:collapse;margin:12px 0 24px}} th,td{{border:1px solid #d5dee8;padding:7px;text-align:left;vertical-align:top}}
th{{background:#edf3f8}} .warning{{border-left:4px solid #d47b00;padding:10px 14px;background:#fff7e8}}
@media print{{body{{margin:0;max-width:none}} .no-print{{display:none}}}}
</style></head><body>
<button class="no-print" onclick="window.print()">Print or save as PDF</button>
<h1>{html.escape(report['title'])}</h1>
<p class="meta">Report {html.escape(report['report_id'])} · Run {html.escape(report['run_id'])} · Generated {html.escape(report['generated_at'])}</p>
<p class="warning">Modeled synthetic demonstration data. Not operational guidance.</p>
<h2>Executive summary</h2><div class="metrics">
<div class="metric"><strong>{summary['peak_flood_depth_m']:.2f} m</strong>Peak routed-edge depth</div>
<div class="metric"><strong>{summary['peak_isolated_people']:,}</strong>People isolated</div>
<div class="metric"><strong>{summary['peak_critical_routes_lost']}</strong>Critical routes lost</div></div>
<ul>{escaped_list(report['narrative'])}</ul>
<h2>Plan outcomes at horizon</h2><table><thead><tr><th>Plan</th><th>Evacuated</th><th>Isolated</th><th>Routes lost</th><th>Viable</th></tr></thead><tbody>{plan_rows}</tbody></table>
<h2>Material changes</h2><table><thead><tr><th>Time</th><th>Subject</th><th>Before</th><th>After</th><th>Analysis</th></tr></thead><tbody>{change_rows}</tbody></table>
<h2>Assumptions</h2><ul>{escaped_list(report['assumptions'])}</ul>
<h2>Limitations</h2><ul>{escaped_list(report['limitations'])}</ul>
<h2>Provenance</h2><p class="meta">Input fingerprint: {html.escape(report['provenance']['input_fingerprint'])}<br>Fixture SHA-256: {html.escape(report['provenance']['fixture_sha256'])}<br>Engine: {html.escape(report['provenance']['engine_version'])}</p>
</body></html>"""
    return document, "text/html; charset=utf-8", f"{safe_id}.html"
