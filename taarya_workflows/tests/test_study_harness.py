import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eval.study_harness import (
    StudyValidationError,
    evaluate,
    load_labels,
    load_runs,
    load_study,
    main,
    score_run,
)


class StudyHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.root = Path(self.temp_dir.name)
        snapshot = self.root / "gaia.csv"
        snapshot.write_bytes(b"source_id,ra,dec\n1,10,20\n2,11,21\n")
        self.dataset_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        self.study_path = self.root / "study.json"
        self.study_path.write_text(json.dumps({
            "study_id": "gaia-smoke",
            "protocol_version": "0.1",
            "dataset": {
                "dataset_id": "gaia-fixture",
                "release": "fixture-1",
                "source": "local test fixture",
                "retrieved_at": "2026-01-01T00:00:00Z",
                "path": "gaia.csv",
                "sha256": self.dataset_hash,
            },
            "scenarios": [
                {"scenario_id": "S1", "task": "cone search", "objective": "return members",
                 "data_release": "fixture-1", "evidence_sources": ["fixture catalog"]},
                {"scenario_id": "S2", "task": "cross-match", "objective": "return matched IDs",
                 "data_release": "fixture-1", "evidence_sources": ["fixture catalog"]},
            ],
        }), encoding="utf-8")
        self.study = load_study(self.study_path)
        self.labels_path = self.root / "labels.json"
        self.labels_path.write_text(json.dumps({
            "study_id": "gaia-smoke",
            "labels": [
                {"scenario_id": "S1", "relevant_ids": ["a", "b"],
                 "required_provenance": ["query", "dataset"],
                 "label_sources": ["fixture catalog v1"], "label_method": "fixed fixture IDs"},
                {"scenario_id": "S2", "relevant_ids": ["c"],
                 "required_provenance": ["query"],
                 "label_sources": ["fixture catalog v1"], "label_method": "fixed fixture IDs"},
            ],
        }), encoding="utf-8")
        self.labels = load_labels(self.labels_path, self.study)
        self.runs = [
            {"participant_id": "P1", "trial_order": order, "scenario_id": sid,
             "system": system, "system_version": "test",
             "returned_ids": ids, "provenance": provenance,
             "dataset_sha256": dataset_hash, "task_time_s": task_time,
             "tool_latency_s": latency}
            for order, (sid, system, ids, provenance, dataset_hash, task_time, latency) in enumerate([
                ("S1", "TaarYa", ["a", "x", "b"], {"query": "q", "dataset": "d"}, self.dataset_hash, 12, .2),
                ("S2", "TaarYa", ["c"], {"query": "q"}, self.dataset_hash, 10, .1),
                ("S1", "PyVO", ["x", "a"], {"query": "q"}, self.dataset_hash, 15, .4),
                ("S2", "PyVO", ["c"], {"query": "q"}, "0" * 64, 13, .3),
            ], 1)
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_study_rejects_snapshot_hash_mismatch(self):
        study = json.loads(self.study_path.read_text(encoding="utf-8"))
        study["dataset"]["sha256"] = "0" * 64
        self.study_path.write_text(json.dumps(study), encoding="utf-8")
        with self.assertRaisesRegex(StudyValidationError, "SHA-256"):
            load_study(self.study_path)

    def test_labels_are_loaded_separately_and_must_cover_scenarios(self):
        artifact = json.loads(self.labels_path.read_text(encoding="utf-8"))
        artifact["labels"].pop()
        self.labels_path.write_text(json.dumps(artifact), encoding="utf-8")
        with self.assertRaisesRegex(StudyValidationError, "cover every study scenario"):
            load_labels(self.labels_path, self.study)

    def test_run_set_must_be_paired_across_all_scenarios(self):
        with self.assertRaisesRegex(StudyValidationError, "every scenario"):
            load_runs_from_artifact(self.study, self.runs[:-1])

    def test_run_rejects_negative_task_time(self):
        invalid = [dict(run) for run in self.runs]
        invalid[0]["task_time_s"] = -1
        with self.assertRaisesRegex(StudyValidationError, "task_time_s"):
            load_runs_from_artifact(self.study, invalid)

    def test_metrics_score_order_provenance_and_dataset_identity(self):
        result = score_run(self.runs[0], self.labels["S1"], self.dataset_hash, k=3)
        self.assertAlmostEqual(result["precision_at_k"], 2 / 3)
        self.assertEqual(result["reciprocal_rank"], 1.0)
        self.assertLess(result["ndcg_at_k"], 1.0)
        self.assertEqual(result["provenance_completeness"], 1.0)
        self.assertTrue(result["dataset_match"])

    def test_report_has_paired_deltas_and_reports_wrong_dataset(self):
        report = evaluate(self.study, self.labels, self.runs, k=3, seed=17)
        self.assertEqual(report["scenario_count"], 2)
        self.assertEqual(report["paired_comparisons"][0]["paired_scenarios"], 2)
        self.assertEqual(report["systems"]["PyVO"]["metrics"]["dataset_match"]["mean"], .5)
        self.assertIsNone(report["systems"]["PyVO"]["metrics"]["dataset_match"]["lower_95"])
        self.assertEqual(report["participant_count"], 1)
        self.assertIn("does not establish general superiority", report["interpretation_note"])

    def test_bootstrap_uses_independent_participants_as_units(self):
        second_participant = [dict(run, participant_id="P2", trial_order=run["trial_order"])
                              for run in self.runs]
        report = evaluate(self.study, self.labels, self.runs + second_participant, k=3, seed=17)
        self.assertEqual(report["participant_count"], 2)
        self.assertEqual(report["bootstrap_unit"],
                         "participant; metrics are averaged across scenarios within each participant")
        self.assertEqual(report["paired_comparisons"][0]["paired_participants"], 2)
        self.assertIsNotNone(report["systems"]["TaarYa"]["metrics"]["precision_at_k"]["lower_95"])

    def test_dataset_manifest_cannot_hash_files_outside_study_directory(self):
        study = json.loads(self.study_path.read_text(encoding="utf-8"))
        study["dataset"]["path"] = "../outside.csv"
        self.study_path.write_text(json.dumps(study), encoding="utf-8")
        with self.assertRaisesRegex(StudyValidationError, "stay inside"):
            load_study(self.study_path)

    def test_cli_writes_machine_readable_report(self):
        runs_path = self.root / "runs.json"
        output_path = self.root / "report.json"
        runs_path.write_text(json.dumps({"study_id": "gaia-smoke", "runs": self.runs}), encoding="utf-8")
        argv = ["study_harness", "--study", str(self.study_path), "--labels", str(self.labels_path),
                "--runs", str(runs_path), "--output", str(output_path), "--k", "3", "--seed", "17"]
        with patch("sys.argv", argv):
            self.assertEqual(main(), 0)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(report["study_id"], "gaia-smoke")
        self.assertEqual(report["scenario_count"], 2)


def load_runs_from_artifact(study, runs):
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
        path = Path(tmp) / "runs.json"
        path.write_text(json.dumps({"study_id": study["study_id"], "runs": runs}), encoding="utf-8")
        return load_runs(path, study)


if __name__ == "__main__":
    unittest.main()
