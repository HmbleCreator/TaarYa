#!/usr/bin/env python3
"""Local regression harness for TaarYa.

Mirrors the GitHub Actions workflow locally — runs unit tests first,
then the offline evaluation suite.  Intended for pre-push validation.

Usage:
    python scripts/run_regression.py              # full suite
    python scripts/run_regression.py --fast        # skip eval
    python scripts/run_regression.py --live        # include live backends
"""

import argparse
import subprocess
import sys
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def _run(label: str, cmd: list[str]) -> bool:
    """Run a command, return True on success."""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}\n")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=ROOT)
    elapsed = time.time() - t0
    ok = result.returncode == 0
    status = "✅ PASSED" if ok else "❌ FAILED"
    print(f"\n  {status} ({elapsed:.1f}s)\n")
    return ok


def main():
    parser = argparse.ArgumentParser(description="TaarYa local regression harness")
    parser.add_argument("--fast", action="store_true", help="Skip offline evaluation")
    parser.add_argument("--live", action="store_true", help="Include live backend tests")
    args = parser.parse_args()

    results: dict[str, bool] = {}

    # ── Stage 1: Unit & integration tests ──────────────────────────────
    test_cmd = [
        sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-x",
    ]
    if not args.live:
        test_cmd += ["--ignore=tests/test_backends.py"]

    results["Unit Tests"] = _run("Stage 1: Unit & Integration Tests", test_cmd)

    if not results["Unit Tests"]:
        print("\n⛔ Unit tests failed — aborting regression.\n")
        sys.exit(1)

    # ── Stage 2: Offline evaluation ────────────────────────────────────
    if not args.fast:
        results["Ablation (offline)"] = _run(
            "Stage 2a: Offline Ablation Study",
            [sys.executable, "eval/ablation_formal.py", "--offline", "--publish"],
        )
        results["Discovery (offline)"] = _run(
            "Stage 2b: Discovery Precision Validation",
            [sys.executable, "eval/validate_discovery.py", "--offline"],
        )

    # ── Summary ────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  REGRESSION SUMMARY")
    print("=" * 70)
    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {name}")
    print("=" * 70)

    all_ok = all(results.values())
    print(f"\n  {'✅ ALL PASSED' if all_ok else '❌ SOME FAILED'}\n")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
