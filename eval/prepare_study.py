"""Create reproducible, counterbalanced task assignments without loading labels."""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any

from eval.study_harness import StudyValidationError, load_study


def prepare_assignments(study: dict[str, Any], participants: list[str],
                        systems: list[str], seed: int) -> dict[str, Any]:
    if not participants or len(participants) > 500:
        raise StudyValidationError("Provide between 1 and 500 participant IDs.")
    if len(set(participants)) != len(participants) or any(
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item) for item in participants):
        raise StudyValidationError("Participant IDs must be unique, anonymous, and 1-64 safe characters.")
    if len(systems) < 2 or len(systems) > 10 or len(set(systems)) != len(systems) or any(
            not isinstance(item, str) or not item.strip() for item in systems):
        raise StudyValidationError("Provide 2-10 distinct non-empty system names.")

    rng = random.Random(seed)
    base_order = list(systems)
    rng.shuffle(base_order)
    participant_order = list(participants)
    rng.shuffle(participant_order)
    scenarios = study["scenarios"]
    assignments = []
    for participant_index, participant_id in enumerate(participant_order):
        scenario_order = list(scenarios)
        rng.shuffle(scenario_order)
        tasks = []
        trial_order = 0
        for scenario_index, scenario in enumerate(scenario_order):
            rotation = (participant_index + scenario_index) % len(base_order)
            ordered_systems = base_order[rotation:] + base_order[:rotation]
            for system in ordered_systems:
                trial_order += 1
                tasks.append({
                    "trial_order": trial_order,
                    "scenario_id": scenario["scenario_id"],
                    "system": system,
                    "task": scenario["task"],
                    "objective": scenario["objective"],
                    "data_release": scenario["data_release"],
                })
        assignments.append({"participant_id": participant_id, "tasks": tasks})
    return {
        "format_version": "1",
        "study_id": study["study_id"],
        "seed": seed,
        "design": "within-participant; system order counterbalanced by cyclic Latin square",
        "assignments": assignments,
        "label_separation": "No relevance labels or label-derived fields are included.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare blinded-label, counterbalanced study tasks")
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--participants", required=True,
                        help="Comma-separated anonymous participant IDs")
    parser.add_argument("--systems", default="TaarYa,TOPCAT,PyVO",
                        help="Comma-separated system names (default: TaarYa,TOPCAT,PyVO)")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        study = load_study(args.study)
        assignments = prepare_assignments(
            study,
            [item.strip() for item in args.participants.split(",") if item.strip()],
            [item.strip() for item in args.systems.split(",") if item.strip()],
            args.seed,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(assignments, stream, indent=2)
            stream.write("\n")
    except StudyValidationError as exc:
        parser.error(str(exc))
    except FileExistsError:
        parser.error(f"Refusing to overwrite existing assignment file: {args.output}")
    print(f"Prepared {len(assignments['assignments'])} participants for {assignments['study_id']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
