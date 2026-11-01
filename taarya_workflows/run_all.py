"""
Master Orchestrator for TaarYa Discovery Workflows.

Runs all core workflows, evaluates against their respective astronomical baselines,
and outputs a unified provenance-stamped benchmark artifact.

Workflows executed:
  1. TESS Transit Discovery (vs Plain BLS baseline)
  2. Gaia Binary Triage (vs TOPCAT sort by RUWE baseline)
  3. Gaia Kinematic Outliers (vs TOPCAT sort by PM baseline)
  4. Blended Eclipsing Binary Ablation (demonstrating why Q3C/RUWE is necessary)
  5. Agent Routing & Claim Verification (evaluating agent composure and refusal to overclaim)

Usage:
  python -m taarya_workflows.run_all --quick
  python -m taarya_workflows.run_all --tic 261136679
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from .agent_routing import AgentRoutingWorkflow
from .blended_eb import BlendedEBAblation
from .core import stamp
from .gaia_triage import GaiaBinaryTriage, GaiaKinematicOutliers
from .tess import TessTransitWorkflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("taarya.benchmark")


def run_benchmark(args: argparse.Namespace) -> dict:
    t_start = time.time()
    results = {}

    print("\n=======================================================")
    print("      TaarYa Multi-Workflow Discovery Benchmark        ")
    print("=======================================================\n")

    # 1. TESS Transit Discovery
    print("--> 1/5: Running TESS Transit Candidate Workflow...")
    tess_wf = TessTransitWorkflow(tic_id=args.tic, sectors=args.sectors)
    results["tess_transit_candidates"] = tess_wf.evaluate(seed=args.seed, quick=args.quick)

    # 2. Gaia Binary Triage
    print("--> 2/5: Running Gaia Binary Triage Workflow...")
    bin_wf = GaiaBinaryTriage()
    results["gaia_binary_triage"] = bin_wf.evaluate(seed=args.seed, quick=args.quick)

    # 3. Gaia Kinematic Outliers
    print("--> 3/5: Running Gaia Kinematic Outliers Workflow...")
    kin_wf = GaiaKinematicOutliers()
    results["gaia_kinematic_outliers"] = kin_wf.evaluate(seed=args.seed, quick=args.quick)

    # 4. Blended EB Ablation
    print("--> 4/5: Running Blended-EB Q3C/RUWE Ablation...")
    beb_wf = BlendedEBAblation()
    results["blended_eb_ablation"] = beb_wf.evaluate(seed=args.seed, quick=args.quick)

    # 5. Agent Routing & Claim Verification
    print("--> 5/5: Running Agent Routing & Claim Verification...")
    agent_wf = AgentRoutingWorkflow()
    results["agent_routing"] = agent_wf.evaluate(seed=args.seed, quick=args.quick)

    results["total_runtime_s"] = round(time.time() - t_start, 1)

    # Stamp provenance
    workflow_files = tuple(
        str(p) for p in Path(__file__).parent.glob("*.py")
    )
    results = stamp(results, seed=args.seed, files=workflow_files)
    return results


def main():
    ap = argparse.ArgumentParser(description="TaarYa Multi-Workflow Discovery Benchmark")
    ap.add_argument("--seed", type=int, default=7, help="Random seed")
    ap.add_argument("--tic", type=str, default=None, help="TESS TIC ID for real data run (e.g. 261136679)")
    ap.add_argument("--sectors", nargs="+", type=int, default=None, help="TESS sectors")
    ap.add_argument("--quick", action="store_true", help="Quick mode for rapid verification")
    ap.add_argument("--out", default="unified_benchmark_results.json", help="Output path for benchmark results")

    args = ap.parse_args()
    results = run_benchmark(args)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n=======================================================")
    print("               BENCHMARK SUITE COMPLETE                ")
    print("=======================================================")
    print(f"Results written to: {args.out}")
    print(f"Total Runtime: {results['total_runtime_s']}s")
    print(f"Code Hash: {results['provenance']['code_hash']}")
    print("=======================================================\n")


if __name__ == "__main__":
    main()

