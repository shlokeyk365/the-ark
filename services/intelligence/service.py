"""Turn field messages into auditable, deterministic scenario changes."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Optional

JsonObject = Dict[str, Any]

_BLOCKED = re.compile(
    r"\b(blocked|closed|impassable|unusable|cannot pass|can't pass|turning around)\b",
    re.IGNORECASE,
)
_FLOOD = re.compile(
    r"\b(flood(?:ed|ing)?|underwater|water|inundat(?:ed|ion))\b",
    re.IGNORECASE,
)
_RISING = re.compile(r"\b(rising|getting higher|increasing)\b", re.IGNORECASE)
_OPEN = re.compile(r"\b(open|reopened|clear|cleared|passable)\b", re.IGNORECASE)
_QUESTION = re.compile(r"^(is|are|was|were|why|what|which|how|can|could|would|should|do|does|will|tell|explain|show|list|compare|describe|summarize)\b", re.IGNORECASE)
_DEPTH = re.compile(
    r"(?P<value>\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s*(?P<unit>feet|foot|ft|meters?|metres?|m)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
}
_SOURCE_RELIABILITY = {
    "official": 0.95,
    "field_responder": 0.85,
    "operator": 0.85,
    "public": 0.45,
    "unknown": 0.30,
}


class ReportNotFoundError(KeyError):
    pass


@dataclass(frozen=True)
class StoredReport:
    report_id: str
    scenario_id: str
    message: str
    source_type: str
    source_name: str
    frame_id: str
    status: str
    edge_id: Optional[str]
    edge_label: Optional[str]
    change_type: str
    water_depth_m: Optional[float]
    trend: Optional[str]
    scores: JsonObject
    verification_priority: float
    summary: str
    note: Optional[str] = None

    def as_dict(self) -> JsonObject:
        return {
            "report_id": self.report_id,
            "scenario_id": self.scenario_id,
            "message": self.message,
            "source": {
                "type": self.source_type,
                "name": self.source_name,
            },
            "frame_id": self.frame_id,
            "status": self.status,
            "asset_match": (
                {
                    "asset_type": "edge",
                    "asset_id": self.edge_id,
                    "display_name": self.edge_label,
                    "confidence": self.scores["location_confidence"],
                }
                if self.edge_id
                else None
            ),
            "claim": {
                "summary": self.summary,
                "water_depth_m": self.water_depth_m,
                "trend": self.trend,
            },
            "scores": self.scores,
            "verification_priority": self.verification_priority,
            "proposed_change": {
                "change_type": self.change_type,
                "edge_id": self.edge_id,
                "reason": self.summary,
            },
            "requires_operator_confirmation": True,
            "note": self.note,
        }


class FieldIntelligenceService:
    """Process-local MVP store with explicit confirmation before application."""

    def __init__(self, scenario_service) -> None:
        self.scenario_service = scenario_service
        self._reports: Dict[str, StoredReport] = {}

    def clear(self) -> None:
        self._reports.clear()

    def get(self, report_id: str) -> StoredReport:
        try:
            return self._reports[report_id]
        except KeyError as error:
            raise ReportNotFoundError(report_id) from error

    def list(self) -> List[JsonObject]:
        return [
            report.as_dict()
            for report in sorted(
                self._reports.values(),
                key=lambda report: report.report_id,
                reverse=True,
            )
        ]

    def _edge_labels(self) -> Dict[str, str]:
        assets_by_edge = {
            feature["properties"].get("edge_id"): feature["properties"]["name"]
            for feature in self.scenario_service.assets["features"]
            if feature["properties"].get("edge_id")
        }
        labels = {}
        for feature in self.scenario_service.network["features"]:
            edge = feature["properties"]
            labels[edge["id"]] = assets_by_edge.get(edge["id"], edge.get("name", edge["id"]))
        return labels

    def _match_edge(self, message: str) -> tuple[Optional[str], Optional[str], float]:
        lowered = message.lower()
        candidates = []
        for edge_id, label in self._edge_labels().items():
            if re.search(r"(?<![\w-])" + re.escape(edge_id.lower()) + r"(?![\w-])", lowered):
                candidates.append((1.0, edge_id, label))
            elif label.lower() in lowered:
                candidates.append((0.96, edge_id, label))
        if not candidates:
            return None, None, 0.0
        candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
        best = candidates[0]
        confidence = best[0] if len(candidates) == 1 else 0.55
        return best[1], best[2], confidence

    def classify(self, message: str) -> str:
        """Questions never become reports; ambiguous/negated commands need clarification."""
        message = message.strip()
        if "?" in message or _QUESTION.search(message):
            return "question"
        if not (_BLOCKED.search(message) or _FLOOD.search(message) or _OPEN.search(message)):
            return "question"
        edge_id, _, confidence = self._match_edge(message)
        if (not edge_id or confidence < 0.7
                or re.search(r"\b(not|never|maybe|might|if|unless|possibly|don't|do not|no longer|isn't|isnt|wasn't|wasnt)\b", message, re.I)
                or (_BLOCKED.search(message) and _OPEN.search(message))):
            return "clarify"
        return "report"

    @staticmethod
    def _depth(message: str) -> Optional[float]:
        match = _DEPTH.search(message)
        if not match:
            return None
        raw = match.group("value").lower()
        value = float(raw) if raw[0].isdigit() else _NUMBER_WORDS[raw]
        if match.group("unit").lower() in {"feet", "foot", "ft"}:
            value *= 0.3048
        return round(value, 3)

    def ingest(
        self,
        message: str,
        source_type: str,
        source_name: str,
        frame_id: str,
    ) -> StoredReport:
        edge_id, edge_label, location_confidence = self._match_edge(message)
        blocked = bool(_BLOCKED.search(message))
        flooded = bool(_FLOOD.search(message))
        intent = self.classify(message)
        if intent != "report":
            change_type = "none"
            extraction_confidence = 0.0
            summary = "Specify one road or bridge by its map name or ID and an unambiguous status. Questions do not change the map."
            operational_impact = 0.0
        elif edge_id and blocked:
            change_type = "close_edge"
            extraction_confidence = 0.94
            summary = f"Reported blockage at {edge_label}."
            operational_impact = 0.90
        elif edge_id and flooded:
            change_type = "restrict_edge"
            extraction_confidence = 0.86
            summary = f"Reported flooding at {edge_label}."
            operational_impact = 0.70
        elif edge_id and _OPEN.search(message):
            change_type = "open_edge"
            extraction_confidence = 0.94
            summary = f"Reported reopening at {edge_label}; only prior field restrictions can be cleared. Flood and infrastructure constraints still apply."
            operational_impact = 0.7
        else:
            change_type = "none"
            extraction_confidence = 0.35
            summary = "The message could not be matched to a supported map change."
            operational_impact = 0.20
        source_reliability = _SOURCE_RELIABILITY[source_type]
        physical_plausibility = 0.80 if flooded else 0.60
        scores = {
            "source_reliability": source_reliability,
            "extraction_confidence": extraction_confidence,
            "location_confidence": location_confidence,
            "corroboration": 0.0,
            "freshness": 1.0,
            "physical_plausibility": physical_plausibility,
            "operational_impact": operational_impact,
        }
        credibility = (
            source_reliability * extraction_confidence * max(location_confidence, 0.01)
        ) ** (1 / 3)
        verification_priority = round(
            min(1.0, credibility * operational_impact * 1.35), 3
        )
        if change_type == "none":
            status = "unresolved"
        elif (
            source_reliability >= 0.70
            and extraction_confidence >= 0.80
            and location_confidence >= 0.70
        ):
            status = "probable"
        else:
            status = "possible"
        material = "|".join(
            [
                self.scenario_service.manifest["scenario_id"],
                frame_id,
                source_name,
                message,
            ]
        )
        report = StoredReport(
            report_id="intel-" + hashlib.sha256(material.encode()).hexdigest()[:12],
            scenario_id=self.scenario_service.manifest["scenario_id"],
            message=message,
            source_type=source_type,
            source_name=source_name,
            frame_id=frame_id,
            status=status,
            edge_id=edge_id,
            edge_label=edge_label,
            change_type=change_type,
            water_depth_m=self._depth(message),
            trend="rising" if _RISING.search(message) else None,
            scores=scores,
            verification_priority=verification_priority,
            summary=summary,
        )
        self._reports[report.report_id] = report
        return report

    def decide(
        self, report_id: str, decision: str, note: Optional[str]
    ) -> StoredReport:
        report = self.get(report_id)
        if decision == "confirm" and (report.change_type == "none" or report.scores["location_confidence"] < 0.7):
            raise ValueError("Resolve the asset and proposed change before confirmation.")
        status = {
            "confirm": "confirmed",
            "reject": "rejected",
            "keep_tentative": report.status,
        }[decision]
        updated = replace(report, status=status, note=note)
        self._reports[report_id] = updated
        return updated

    def events_for(
        self,
        report_ids: Iterable[str],
        include_probable: bool = False,
    ) -> List[JsonObject]:
        events = []
        for report_id in report_ids:
            report = self.get(report_id)
            allowed = report.status == "confirmed" or (
                include_probable and report.status == "probable"
            )
            if not allowed or report.edge_id is None or report.change_type == "none":
                continue
            events.append(
                {
                    "event_id": report.report_id,
                    "event_type": "field_intelligence",
                    "effective_at_hours": 0.0,
                    "occurred_at": report.frame_id,
                    "source_type": "operator_injected",
                    "reliability": report.status,
                    "description": report.summary,
                    "changes": [
                        {
                            "change_type": {
                                "close_edge": "force_close_edge",
                                "restrict_edge": "force_restrict_edge",
                                "open_edge": "clear_field_restriction",
                            }[report.change_type],
                            "edge_id": report.edge_id,
                            "reason": report.summary,
                        }
                    ],
                }
            )
        return events
