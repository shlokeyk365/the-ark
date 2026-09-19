import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from the_arc_physics.desinventar import read_desinventar_floods
from the_arc_physics.features import EventInput
from the_arc_physics.integration import simulation_impact_prior
from the_arc_physics.metrics import binary_metrics, grouped_roc_auc_interval, roc_auc
from the_arc_physics.model import MultiLabelFloodImpactModel
from the_arc_physics.pipeline import evaluate_locked_holdout, grouped_cross_validation
from the_arc_physics.records import FloodEventRecord, validate_training_records


def sample_records(count=120):
    records = []
    for index in range(count):
        damaging = index % 3 != 0
        records.append(
            FloodEventRecord(
                event_id=f"event-{index}",
                source="test",
                year=1980 + index % 20,
                month=6 + index % 4,
                day=1 + index % 28,
                region="Central Region" if index % 2 else "Eastern Region",
                district="Lalitpur" if index % 2 else "Ilam",
                municipality="Test",
                cause="HEAVY RAINS" if damaging else "OTHER",
                deaths=int(damaging and index % 5 == 0),
                missing=0,
                injured=0,
                people_affected=100 if damaging else 2,
                houses_destroyed=10 if damaging else 0,
                houses_affected=5 if damaging else 0,
                evacuated=0,
                roads_damaged_km=1.0 if damaging else 0.0,
                transport_affected=damaging,
            )
        )
    return records


class TrainingPipelineTests(unittest.TestCase):
    def test_rejects_holdout_leakage(self):
        records = sample_records()
        records[-1] = FloodEventRecord(**{**records[-1].__dict__, "year": 2024})
        with self.assertRaisesRegex(ValueError, "holdout leakage"):
            validate_training_records(records)

    def test_model_round_trip(self):
        records = sample_records()
        model = MultiLabelFloodImpactModel.fit(records)
        event = EventInput(2024, 9, 28, "Central Region", "Lalitpur", "HEAVY RAINS")
        before = model.predict(event)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            model.save(path)
            after = MultiLabelFloodImpactModel.load(path).predict(event)
        self.assertEqual(before, after)

    def test_grouped_cross_validation_uses_all_records(self):
        report = grouped_cross_validation(sample_records(), folds=5)
        self.assertEqual(report["overall"]["casualty_or_missing"]["support"], 120)
        self.assertIn("macro_f1", report["overall"])
        self.assertIn("macro_roc_auc", report["overall"])
        self.assertIn("prevalence_baseline", report["overall"]["housing_damage"])
        self.assertIn("validation_gate", report)

    def test_roc_auc_distinguishes_signal_from_guessing(self):
        labels = np.asarray([0, 0, 1, 1], dtype=float)
        self.assertEqual(roc_auc(labels, np.asarray([0.1, 0.2, 0.8, 0.9])), 1.0)
        self.assertEqual(roc_auc(labels, np.asarray([0.9, 0.8, 0.2, 0.1])), 0.0)
        self.assertEqual(roc_auc(labels, np.asarray([0.5, 0.5, 0.5, 0.5])), 0.5)

    def test_probability_errors_are_reported(self):
        metrics = binary_metrics(
            np.asarray([0.0, 1.0]), np.asarray([0.25, 0.75])
        )
        self.assertEqual(metrics["mse"], 0.0625)
        self.assertEqual(metrics["rmse"], 0.25)
        self.assertEqual(metrics["brier"], metrics["mse"])

    def test_grouped_auc_interval_is_deterministic(self):
        labels = np.asarray([0, 1, 0, 1, 0, 1], dtype=float)
        probabilities = np.asarray([0.1, 0.9, 0.2, 0.8, 0.3, 0.7])
        groups = [2000, 2000, 2001, 2001, 2002, 2002]
        first = grouped_roc_auc_interval(
            labels, probabilities, groups, iterations=50
        )
        second = grouped_roc_auc_interval(
            labels, probabilities, groups, iterations=50
        )
        self.assertEqual(first, second)
        self.assertEqual(first["lower"], 1.0)

    def test_locked_holdout_returns_component_scores(self):
        model = MultiLabelFloodImpactModel.fit(sample_records())
        holdout = {
            "event_id": "nakkhu-2024",
            "locked": True,
            "model_input": {
                "year": 2024,
                "month": 9,
                "day": 28,
                "region": "Central Region",
                "district": "Lalitpur",
                "cause": "HEAVY RAINS"
            },
            "actual_labels": {
                "casualty_or_missing": True,
                "housing_damage": True,
                "transport_disruption": True,
                "severe_impact": True
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "holdout.json"
            path.write_text(json.dumps(holdout), encoding="utf-8")
            result = evaluate_locked_holdout(model, path)
        self.assertEqual(len(result["components"]), 4)
        self.assertGreaterEqual(result["classification_accuracy_percent"], 0)

    def test_desinventar_ingestion_uses_stable_uuid(self):
        xml = b"""<DESINVENTAR><fichas><TR>
        <serial>duplicate-serial</serial><uu_id>unique-event</uu_id>
        <evento>FLOOD</evento><fechano>2001</fechano><fechames>7</fechames>
        <fechadia>3</fechadia><name0>Central Region</name0>
        <name1>Lalitpur</name1><name2>Test</name2><causa>HEAVY RAINS</causa>
        <muertos>1</muertos><transporte>1</transporte>
        </TR></fichas></DESINVENTAR>"""
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "export.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("export.xml", xml)
            records = list(read_desinventar_floods(archive_path))
        self.assertEqual(records[0].event_id, "desinventar-unique-event")
        self.assertTrue(records[0].transport_affected)

    def test_simulation_contract_does_not_expose_holdout_labels(self):
        model = MultiLabelFloodImpactModel.fit(sample_records())
        event = EventInput(2024, 9, 28, "Central Region", "Lalitpur", "HEAVY RAINS")
        prior = simulation_impact_prior(model, "nakkhu-2024", event)
        self.assertIn("impactProbabilities", prior)
        self.assertNotIn("actual_labels", json.dumps(prior))



if __name__ == "__main__":
    unittest.main()
