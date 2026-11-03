import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eval.prepare_study import main, prepare_assignments
from eval.study_harness import StudyValidationError, load_study


class PrepareStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.root = Path(self.temp_dir.name)
        snapshot = self.root / "catalog.csv"
        snapshot.write_text("source_id\n1\n", encoding="utf-8")
        digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        self.study_path = self.root / "study.json"
        self.study_path.write_text(json.dumps({
            "study_id": "prep-fixture",
            "protocol_version": "1",
            "dataset": {"dataset_id": "fixture", "release": "r1", "source": "local",
                        "retrieved_at": "2026-01-01", "path": "catalog.csv", "sha256": digest},
            "scenarios": [
                {"scenario_id": f"S{i}", "task": f"Task {i}", "objective": "Return IDs",
                 "data_release": "r1", "evidence_sources": ["fixture"]}
                for i in range(1, 4)
            ],
        }), encoding="utf-8")
        self.study = load_study(self.study_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_assignments_are_deterministic_complete_and_label_free(self):
        participants = ["P01", "P02", "P03"]
        systems = ["TaarYa", "TOPCAT", "PyVO"]
        first = prepare_assignments(self.study, participants, systems, seed=44)
        second = prepare_assignments(self.study, participants, systems, seed=44)
        self.assertEqual(first, second)
        self.assertNotIn("relevant_ids", json.dumps(first).lower())
        for participant in first["assignments"]:
            tasks = participant["tasks"]
            self.assertEqual(len(tasks), 9)
            self.assertEqual([task["trial_order"] for task in tasks], list(range(1, 10)))
            for scenario in self.study["scenarios"]:
                systems_for_scenario = [task["system"] for task in tasks
                                        if task["scenario_id"] == scenario["scenario_id"]]
                self.assertEqual(set(systems_for_scenario), set(systems))

    def test_assignment_validation_rejects_duplicate_systems_and_unsafe_participant_ids(self):
        with self.assertRaisesRegex(StudyValidationError, "distinct"):
            prepare_assignments(self.study, ["P1"], ["PyVO", "PyVO"], 1)
        with self.assertRaisesRegex(StudyValidationError, "anonymous"):
            prepare_assignments(self.study, ["../P1"], ["PyVO", "TOPCAT"], 1)

    def test_cli_refuses_to_overwrite_existing_assignments(self):
        output = self.root / "assignments.json"
        output.write_text("keep", encoding="utf-8")
        argv = ["prepare_study", "--study", str(self.study_path), "--participants", "P1",
                "--systems", "TaarYa,TOPCAT", "--seed", "7", "--output", str(output)]
        with patch("sys.argv", argv), self.assertRaises(SystemExit):
            main()
        self.assertEqual(output.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
