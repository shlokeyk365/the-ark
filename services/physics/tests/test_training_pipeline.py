import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from the_arc_physics.bipad import read_bipad_floods
from the_arc_physics.desinventar import read_desinventar_floods
from the_arc_physics.episodes import consolidate_event_reports
from the_arc_physics.features import EventInput, FeatureEncoder
from the_arc_physics.integration import simulation_impact_prior
from the_arc_physics.hydrography import BasinFeature, HydrologyIndex, RiverFeature
from the_arc_physics.metrics import binary_metrics, grouped_roc_auc_interval, roc_auc
from the_arc_physics.model import MultiLabelFloodImpactModel
from the_arc_physics.pipeline import evaluate_locked_holdout, grouped_cross_validation
from the_arc_physics.records import (
    FloodEventRecord,
    read_records,
    validate_training_records,
    write_records,
)


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
    def test_bipad_import_cannot_cross_locked_holdout_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "must end before"):
                list(
                    read_bipad_floods(
                        Path(directory), sample_records(), end_year=2024
                    )
                )

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

    def test_feature_encoder_excludes_city_and_district_identity(self):
        rows = [
            EventInput(2001, 7, 1, "Central", "Lalitpur", "HEAVY RAINS"),
            EventInput(2002, 8, 2, "Eastern", "Jhapa", "RAIN"),
        ]
        encoder = FeatureEncoder.fit(rows)
        names = " ".join(encoder.feature_names).lower()
        self.assertNotIn("lalitpur", names)
        self.assertNotIn("jhapa", names)
        self.assertNotIn("district=", names)
        self.assertNotIn("basin_id", names)

    def test_hydrology_index_returns_basin_and_nearest_river_features(self):
        basin = BasinFeature(
            basin_id="test-basin",
            sub_basin_area_sq_km=100.0,
            upstream_area_sq_km=250.0,
            distance_to_outlet_km=15.0,
            basin_order=3.0,
            geometry={
                "type": "Polygon",
                "coordinates": [[
                    [85.0, 27.0],
                    [86.0, 27.0],
                    [86.0, 28.0],
                    [85.0, 28.0],
                    [85.0, 27.0],
                ]],
            },
        )
        river = RiverFeature(
            river_id="test-river",
            average_discharge_cms=12.0,
            upstream_area_sq_km=75.0,
            strahler_order=2.0,
            lines=(((85.4, 27.0), (85.4, 28.0)),),
        )
        features = HydrologyIndex([basin], [river]).features_at(27.5, 85.5)
        self.assertEqual(features.basin_id, "test-basin")
        self.assertEqual(features.river_average_discharge_cms, 12.0)
        self.assertGreater(features.nearest_river_distance_km, 0.0)

    def test_people_affected_alone_does_not_define_severe_impact(self):
        record = FloodEventRecord(
            **{
                **sample_records(1)[0].__dict__,
                "people_affected": 10_000,
                "deaths": 0,
                "missing": 0,
                "houses_destroyed": 0,
                "houses_affected": 0,
            }
        )
        self.assertEqual(record.targets["severe_impact"], 0)

    def test_district_grouped_folds_hold_out_complete_districts(self):
        records = sample_records(150)
        districts = [
            "Achham",
            "Bara",
            "Chitwan",
            "Dhading",
            "Ilam",
            "Jhapa",
            "Kaski",
            "Lalitpur",
            "Morang",
            "Sunsari",
        ]
        records = [
            FloodEventRecord(
                **{**record.__dict__, "district": districts[index % len(districts)]}
            )
            for index, record in enumerate(records)
        ]
        report = grouped_cross_validation(records, folds=5, grouping="district")
        seen = []
        for fold in report["folds"]:
            seen.extend(fold["validation_districts"])
        self.assertEqual(sorted(seen), sorted(districts))

    def test_basin_and_storm_groups_are_held_out_together(self):
        records = sample_records(150)
        records = [
            FloodEventRecord(
                **{
                    **record.__dict__,
                    "basin_id": f"basin-{index % 10}",
                    "year": 2000 + index // 30,
                    "month": 7,
                    "day": 1 + index % 20,
                }
            )
            for index, record in enumerate(records)
        ]
        basin_report = grouped_cross_validation(records, folds=5, grouping="basin")
        basin_groups = [
            group
            for fold in basin_report["folds"]
            for group in fold["validation_groups"]
        ]
        self.assertEqual(len(basin_groups), len(set(basin_groups)))
        storm_report = grouped_cross_validation(records, folds=5, grouping="storm")
        storm_groups = [
            group
            for fold in storm_report["folds"]
            for group in fold["validation_groups"]
        ]
        self.assertEqual(len(storm_groups), len(set(storm_groups)))

    def test_repeated_reports_are_consolidated_into_one_episode(self):
        records = sample_records(2)
        records[1] = FloodEventRecord(
            **{
                **records[0].__dict__,
                "event_id": "second-report",
                "deaths": 2,
                "houses_affected": 3,
            }
        )
        episodes = consolidate_event_reports(records)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0].deaths, records[0].deaths + 2)
        self.assertEqual(
            episodes[0].houses_affected,
            records[0].houses_affected + 3,
        )

    def test_enriched_fields_round_trip_through_csv(self):
        record = FloodEventRecord(
            **{
                **sample_records(1)[0].__dict__,
                "latitude": 27.5,
                "rainfall_7d_mm": 123.4,
                "population_density_2011": 456.7,
                "basin_id": "4060901970",
                "nearest_river_distance_km": 1.25,
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            write_records(path, [record])
            restored = read_records(path)[0]
        self.assertEqual(restored.latitude, 27.5)
        self.assertEqual(restored.rainfall_7d_mm, 123.4)
        self.assertEqual(restored.population_density_2011, 456.7)
        self.assertEqual(restored.basin_id, "4060901970")
        self.assertEqual(restored.nearest_river_distance_km, 1.25)

    def test_unknown_target_labels_are_excluded_from_metrics(self):
        records = sample_records(120)
        records = [
            FloodEventRecord(
                **{
                    **record.__dict__,
                    "transport_label_known": index >= 20,
                }
            )
            for index, record in enumerate(records)
        ]
        report = grouped_cross_validation(records, folds=5)
        self.assertEqual(report["overall"]["transport_disruption"]["support"], 100)
        self.assertEqual(report["overall"]["housing_damage"]["support"], 120)

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
