"""
Single driver to regenerate all real-data evaluation results for TaarYa.

Executes:
  1. Cluster Membership Audit (Step 0 Jaccard + published gold comparison)
  2. Cluster Member Retrieval Benchmark (TOPCAT box vs Mahalanobis vs Graph PPR)
  3. TOI Exoplanet Candidate Vetting Benchmark (baseline covariates + |b| vs neighbour vetting)

Outputs:
  eval/real_benchmarks_summary.json
"""
from __future__ import annotations
import json, os, time, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from taarya_workflows.real import membership as M
from taarya_workflows.real import cluster_retrieval as CR
from taarya_workflows.real import exofop as X


ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
EVAL_DIR.mkdir(exist_ok=True)


def run_membership_audit(stars_path: Path, edges_path: Path, gold_path: Path) -> dict:
    print("[1/3] Running cluster membership audit...")
    stars = pd.read_csv(stars_path, dtype={"source_id": str})
    edges = pd.read_csv(edges_path, dtype={"source_id": str})
    gold, rep = M.load_gold(str(gold_path), id_system="dr3")
    res = M.evaluate_membership(stars, edges, gold)
    return {
        "median_jaccard_edges_vs_cone": res.get("median_jaccard_edges_vs_cone"),
        "verdict": res.get("verdict"),
        "per_cluster": res.get("per_cluster"),
        "gold_report": rep,
    }


def run_cluster_retrieval(stars_path: Path, gold_path: Path, n_seeds: int = 10, repeats: int = 5) -> dict:
    print(f"[2/3] Running cluster member retrieval benchmark (seeds={n_seeds}, repeats={repeats})...")
    stars = pd.read_csv(stars_path, dtype={"source_id": str})
    gold = pd.read_csv(gold_path, dtype={"source_id": str})
    return CR.evaluate_retrieval(stars, gold, n_seeds=n_seeds, repeats=repeats)


def run_toi_vetting(tois_path: Path, nb_path: Path, B: int = 500, seed: int = 42) -> dict:
    print(f"[3/3] Running TOI exoplanet vetting benchmark (B={B})...")
    raw = pd.read_csv(tois_path)
    df = X.normalise(raw)
    with open(nb_path, "r", encoding="utf-8") as f:
        nb_dict = json.load(f)
    tbl = X.build_table(df, nb_dict)
    res = X.evaluate(tbl, B=B, seed=seed)
    return res


def main():
    start_time = time.time()
    stars_path = ROOT / "cluster_cones" / "stars.csv"
    edges_path = ROOT / "cluster_cones" / "edges_cone.csv"
    gold_path = ROOT / "cluster_cones" / "gold.csv"
    tois_path = ROOT / "data" / "tess_cache" / "nasa_tois.csv"
    nb_path = ROOT / "toi_nb.json"

    # 1. Membership Audit
    mem_res = run_membership_audit(stars_path, edges_path, gold_path)

    # 2. Cluster Retrieval Benchmark
    ret_res = run_cluster_retrieval(stars_path, gold_path, n_seeds=10, repeats=5)

    # 3. TOI Vetting Benchmark
    toi_res = run_toi_vetting(tois_path, nb_path, B=500, seed=42)

    summary = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runtime_seconds": round(time.time() - start_time, 2),
        "membership_audit": mem_res,
        "cluster_retrieval": ret_res,
        "toi_vetting": toi_res,
    }

    out_file = EVAL_DIR / "real_benchmarks_summary.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\nSaved real benchmarks summary to {out_file} (elapsed: {summary['runtime_seconds']}s)")


if __name__ == "__main__":
    main()
