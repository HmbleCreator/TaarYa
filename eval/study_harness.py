"""Validate and score frozen, paired astronomy workflow studies.

Task prompts and dataset manifests are public inputs. Relevance labels are
provided separately so they can be withheld from evaluated systems.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
from pathlib import Path
from typing import Any

MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024 * 1024
MAX_SCENARIOS = 10_000
MAX_RUNS = 500_000


class StudyValidationError(ValueError):
    """Raised when a study artifact is incomplete or inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StudyValidationError(message)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise StudyValidationError(f"JSON artifact exceeds {MAX_JSON_BYTES} bytes: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StudyValidationError(f"Cannot read JSON artifact {path}: {exc}") from exc
    _require(isinstance(value, dict), f"Expected a JSON object in {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_study(path: Path) -> dict[str, Any]:
    study = _read_json(path)
    _require(bool(study.get("study_id")), "study_id is required")
    _require(bool(study.get("protocol_version")), "protocol_version is required")
    dataset = study.get("dataset")
    _require(isinstance(dataset, dict), "dataset must be an object")
    for field in ("dataset_id", "release", "source", "retrieved_at", "path", "sha256"):
        _require(bool(dataset.get(field)), f"dataset.{field} is required")
    _require(isinstance(dataset["path"], str), "dataset.path must be a string")
    expected_hash = str(dataset["sha256"]).lower()
    _require(len(expected_hash) == 64 and all(c in "0123456789abcdef" for c in expected_hash),
             "dataset.sha256 must be a 64-character SHA-256 hex digest")
    study_root = path.parent.resolve()
    dataset_path = (study_root / dataset["path"]).resolve()
    _require(dataset_path.is_relative_to(study_root), "Dataset snapshot path must stay inside the study directory")
    _require(dataset_path.is_file(), f"Dataset snapshot does not exist: {dataset_path}")
    _require(dataset_path.stat().st_size <= MAX_SNAPSHOT_BYTES,
             f"Dataset snapshot exceeds {MAX_SNAPSHOT_BYTES} bytes")
    actual_hash = _sha256(dataset_path)
    _require(actual_hash == expected_hash, "Dataset snapshot SHA-256 does not match the study manifest")

    scenarios = study.get("scenarios")
    _require(isinstance(scenarios, list) and scenarios, "scenarios must be a non-empty list")
    _require(len(scenarios) <= MAX_SCENARIOS, f"scenarios may contain at most {MAX_SCENARIOS} entries")
    scenario_ids: set[str] = set()
    for scenario in scenarios:
        _require(isinstance(scenario, dict), "Each scenario must be an object")
        for field in ("scenario_id", "task", "objective", "data_release", "evidence_sources"):
            _require(field in scenario and scenario[field] not in (None, "", []),
                     f"Each scenario requires {field}")
        sid = scenario["scenario_id"]
        _require(isinstance(sid, str) and sid, "scenario_id must be a non-empty string")
        _require(isinstance(scenario["evidence_sources"], list)
                 and all(isinstance(source, str) and source for source in scenario["evidence_sources"]),
                 f"Scenario {sid} evidence_sources must be a non-empty list of strings")
        _require(sid not in scenario_ids, f"Duplicate scenario_id: {sid}")
        scenario_ids.add(sid)
        _require(scenario["data_release"] == dataset["release"],
                 f"Scenario {sid} data_release does not match the dataset manifest")
    return study


def load_labels(path: Path, study: dict[str, Any]) -> dict[str, dict[str, Any]]:
    labels_artifact = _read_json(path)
    _require(labels_artifact.get("study_id") == study["study_id"],
             "Label artifact study_id does not match")
    labels = labels_artifact.get("labels")
    _require(isinstance(labels, list), "labels must be a list")
    scenario_ids = {s["scenario_id"] for s in study["scenarios"]}
    by_id: dict[str, dict[str, Any]] = {}
    for label in labels:
        _require(isinstance(label, dict), "Each label record must be an object")
        sid = label.get("scenario_id")
        _require(isinstance(sid, str) and sid, "label.scenario_id must be a non-empty string")
        _require(sid in scenario_ids, f"Labels reference unknown scenario: {sid}")
        _require(sid not in by_id, f"Duplicate labels for scenario: {sid}")
        relevant = label.get("relevant_ids")
        required = label.get("required_provenance")
        sources = label.get("label_sources")
        method = label.get("label_method")
        _require(isinstance(relevant, list) and relevant,
                 f"Scenario {sid} requires a non-empty relevant_ids list")
        _require(all(isinstance(x, str) and x for x in relevant),
                 f"Scenario {sid} relevant_ids must contain non-empty strings")
        _require(len(set(relevant)) == len(relevant), f"Scenario {sid} has duplicate relevant IDs")
        _require(isinstance(required, list) and all(isinstance(x, str) and x for x in required),
                 f"Scenario {sid} required_provenance must be a list of strings")
        _require(isinstance(sources, list) and sources and all(isinstance(x, str) and x for x in sources),
                 f"Scenario {sid} requires label_sources")
        _require(isinstance(method, str) and method.strip(), f"Scenario {sid} requires label_method")
        by_id[sid] = label
    _require(set(by_id) == scenario_ids, "Labels must cover every study scenario exactly once")
    return by_id


def load_runs(path: Path, study: dict[str, Any]) -> list[dict[str, Any]]:
    artifact = _read_json(path)
    _require(artifact.get("study_id") == study["study_id"], "Run artifact study_id does not match")
    runs = artifact.get("runs")
    _require(isinstance(runs, list) and runs, "runs must be a non-empty list")
    _require(len(runs) <= MAX_RUNS, f"runs may contain at most {MAX_RUNS} entries")
    scenario_ids = {s["scenario_id"] for s in study["scenarios"]}
    seen: set[tuple[str, str, str]] = set()
    trial_orders: set[tuple[str, int]] = set()
    orders_by_participant: dict[str, list[int]] = {}
    for run in runs:
        _require(isinstance(run, dict), "Each run record must be an object")
        for field in ("participant_id", "trial_order", "scenario_id", "system", "system_version", "returned_ids", "provenance",
                      "dataset_sha256", "task_time_s", "tool_latency_s"):
            _require(field in run, f"Each run requires {field}")
        sid = run["scenario_id"]
        system = run["system"]
        participant = run["participant_id"]
        trial_order = run["trial_order"]
        _require(isinstance(sid, str) and sid, "run.scenario_id must be a non-empty string")
        _require(sid in scenario_ids, f"Run references unknown scenario: {sid}")
        _require(isinstance(participant, str) and participant.strip(), "run.participant_id must be a non-empty string")
        _require(isinstance(trial_order, int) and not isinstance(trial_order, bool) and trial_order >= 1,
                 "run.trial_order must be a positive integer")
        _require(isinstance(system, str) and system, "run.system must be a non-empty string")
        key = (participant, sid, system)
        _require(key not in seen, f"Duplicate run for scenario {sid} and system {system}")
        seen.add(key)
        order_key = (participant, trial_order)
        _require(order_key not in trial_orders, f"Participant {participant} has duplicate trial_order {trial_order}")
        trial_orders.add(order_key)
        orders_by_participant.setdefault(participant, []).append(trial_order)
        ids = run["returned_ids"]
        _require(isinstance(ids, list) and all(isinstance(x, str) and x for x in ids),
                 f"Run {key} returned_ids must be a list of strings")
        _require(len(ids) == len(set(ids)), f"Run {key} contains duplicate result IDs")
        _require(isinstance(run["provenance"], dict), f"Run {key} provenance must be an object")
        _require(isinstance(run["system_version"], str) and run["system_version"].strip(),
                 f"Run {key} system_version must not be empty")
        for field in ("task_time_s", "tool_latency_s"):
            value = run[field]
            _require(isinstance(value, int | float) and math.isfinite(value) and value >= 0,
                     f"Run {key} {field} must be a finite non-negative number")
        digest = run["dataset_sha256"]
        _require(isinstance(digest, str) and len(digest) == 64
                 and all(c in "0123456789abcdefABCDEF" for c in digest),
                 f"Run {key} dataset_sha256 must be a SHA-256 hex digest")
    participants = {run["participant_id"] for run in runs}
    systems = {run["system"] for run in runs}
    expected_pairs = {(participant, sid, system) for participant in participants
                      for sid in scenario_ids for system in systems}
    _require(seen == expected_pairs, "Every evaluated system must have exactly one run for every scenario")
    for participant, orders in orders_by_participant.items():
        _require(sorted(orders) == list(range(1, len(orders) + 1)),
                 f"Participant {participant} trial_order values must be contiguous from 1")
    return runs


def _dcg(retrieved: list[str], relevant: set[str], k: int) -> float:
    return sum((1.0 / math.log2(rank + 1)) for rank, item in enumerate(retrieved[:k], 1)
               if item in relevant)


def score_run(run: dict[str, Any], label: dict[str, Any], dataset_sha256: str,
              k: int = 10) -> dict[str, Any]:
    _require(k >= 1, "k must be at least 1")
    relevant = set(label["relevant_ids"])
    retrieved = run["returned_ids"][:k]
    hits = [item for item in retrieved if item in relevant]
    precision = len(hits) / k
    recall = len(hits) / len(relevant)
    first_rank = next((i for i, item in enumerate(retrieved, 1) if item in relevant), None)
    ideal_count = min(k, len(relevant))
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    ndcg = _dcg(retrieved, relevant, k) / ideal_dcg if ideal_dcg else 0.0
    required = set(label["required_provenance"])
    observed = {key for key, value in run["provenance"].items() if value not in (None, "", [], {})}
    provenance_completeness = len(required & observed) / len(required) if required else 1.0
    return {
        "participant_id": run["participant_id"],
        "trial_order": run["trial_order"],
        "scenario_id": run["scenario_id"],
        "system": run["system"],
        "precision_at_k": precision,
        "recall_at_k": recall,
        "reciprocal_rank": 1.0 / first_rank if first_rank else 0.0,
        "ndcg_at_k": ndcg,
        "provenance_completeness": provenance_completeness,
        "dataset_match": run["dataset_sha256"].lower() == dataset_sha256.lower(),
        "task_time_s": float(run["task_time_s"]),
        "tool_latency_s": float(run["tool_latency_s"]),
    }


def _bootstrap_mean_interval(values: list[float], seed: int, samples: int = 4000) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "lower_95": None, "upper_95": None}
    mean = sum(values) / len(values)
    if len(values) < 2:
        return {"mean": mean, "lower_95": None, "upper_95": None}
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(samples))
    return {
        "mean": mean,
        "lower_95": means[int(0.025 * (samples - 1))],
        "upper_95": means[int(0.975 * (samples - 1))],
    }


def evaluate(study: dict[str, Any], labels: dict[str, dict[str, Any]],
             runs: list[dict[str, Any]], k: int = 10, seed: int = 20261028) -> dict[str, Any]:
    _require(k >= 1, "k must be at least 1")
    dataset_sha256 = study["dataset"]["sha256"]
    scenario_by_id = {s["scenario_id"]: s for s in study["scenarios"]}
    scored = [score_run(run, labels[run["scenario_id"]], dataset_sha256, k) for run in runs]
    systems = sorted({r["system"] for r in scored})
    participants = sorted({r["participant_id"] for r in runs})
    metrics = ("precision_at_k", "recall_at_k", "reciprocal_rank", "ndcg_at_k",
               "provenance_completeness", "dataset_match", "task_time_s", "tool_latency_s")
    summary: dict[str, Any] = {}
    for system in systems:
        rows = [r for r in scored if r["system"] == system]
        per_participant = {
            participant: [r for r in rows if r["participant_id"] == participant]
            for participant in participants
        }
        summary[system] = {
            "n_scenarios": len(scenario_by_id),
            "n_participants": len(participants),
            "metrics": {metric: _bootstrap_mean_interval(
                [sum(float(row[metric]) for row in person_rows) / len(person_rows)
                 for person_rows in per_participant.values()], seed + i)
                for i, metric in enumerate(metrics)},
        }

    comparisons = []
    for left, right in itertools.combinations(systems, 2):
        left_rows = {(r["participant_id"], r["scenario_id"]): r for r in scored if r["system"] == left}
        right_rows = {(r["participant_id"], r["scenario_id"]): r for r in scored if r["system"] == right}
        deltas = {}
        for index, metric in enumerate(("precision_at_k", "recall_at_k", "reciprocal_rank", "ndcg_at_k",
                                        "provenance_completeness", "task_time_s", "tool_latency_s")):
            by_participant = {
                participant: [float(left_rows[(participant, sid)][metric]) -
                              float(right_rows[(participant, sid)][metric])
                              for sid in scenario_by_id if (participant, sid) in left_rows and
                              (participant, sid) in right_rows]
                for participant in participants
            }
            values = [sum(person_values) / len(person_values)
                      for person_values in by_participant.values() if person_values]
            deltas[metric] = _bootstrap_mean_interval(values, seed + 100 + index)
        comparisons.append({"left_system": left, "right_system": right,
                            "paired_scenarios": len(scenario_by_id),
                            "paired_participants": len(participants), "left_minus_right": deltas})

    return {
        "study_id": study["study_id"],
        "protocol_version": study["protocol_version"],
        "dataset": study["dataset"],
        "k": k,
        "bootstrap_seed": seed,
        "scenario_count": len(scenario_by_id),
        "participant_count": len(participants),
        "bootstrap_unit": "participant; metrics are averaged across scenarios within each participant",
        "systems": summary,
        "paired_comparisons": comparisons,
        "scenario_results": sorted(scored, key=lambda r: (r["participant_id"], r["scenario_id"], r["system"])),
        "interpretation_note": (
            "Tool latency is not human task time. Dataset mismatches are reported, not hidden. "
            "Intervals are not estimable with fewer than two participants. "
            "This report does not establish general superiority beyond these scenarios."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and score a paired astronomy workflow study")
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True,
                        help="Private relevance labels, not supplied to evaluated systems")
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261028)
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be at least 1")
    try:
        study = load_study(args.study)
        labels = load_labels(args.labels, study)
        runs = load_runs(args.runs, study)
        report = evaluate(study, labels, runs, k=args.k, seed=args.seed)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except StudyValidationError as exc:
        parser.error(str(exc))
    print(f"Scored {report['scenario_count']} scenarios across {len(report['systems'])} systems.")
    print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
