"""
TESS Transit Discovery Workflow.

Wraps the time-domain transit detection and vetting harness behind the
standard `Workflow` contract, evaluating against the plain BLS baseline.

Evaluates:
  1. Baseline: Single-sector plain BoxLeastSquares (BLS) without multi-sector
     consistency, shape vetters, or held-out blind prediction.
  2. TaarYa Hybrid Architecture: BLS + multi-sector fine refinement +
     odd/even & secondary vetting + Q3C aperture cross-match +
     hash-committed blind prediction on held-out data.
"""
from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .core import (
    Claim,
    DataVault,
    Workflow,
    bootstrap_ci,
    paired_diff,
    rate,
    wilson,
)
import taarya_td_harness as td


class TessTransitWorkflow(Workflow):
    name = "tess_transit_candidates"
    ground_truth = "Injected synthetic transits with known (P, t0, depth); or verified TOI dispositions"
    baseline = "Single-sector plain BoxLeastSquares (BLS) without vetting or held-out prediction"
    claim_ceiling = Claim.VETTED_CANDIDATE
    evidence_level = "synthetic_and_real_TESS"

    def __init__(self, tic_id: Optional[str] = None, sectors: Optional[List[int]] = None):
        self.tic_id = tic_id
        self.sectors = sectors

    def evaluate(self, seed: int = 7, quick: bool = False) -> dict:
        rng = np.random.default_rng(seed)

        # Build mock args for the harness runner
        args = argparse.Namespace(
            seed=seed,
            tic=self.tic_id,
            sectors=self.sectors,
            ra=84.2911 if self.tic_id == "261136679" else None,
            dec=-80.4691 if self.tic_id == "261136679" else None,
            force_download=False,
            n_null=25 if quick else 75,
            n_trials=4 if quick else 10,
            n_blind=6 if quick else 18,
            quick=quick,
            out="td_harness_results.json"
        )

        harness_results = td.run(args)

        # Baseline comparison:
        # Plain BLS without vetters on the injected trials accepts raw BLS peaks above threshold.
        # TaarYa requires passing odd/even, secondary, alias, and blind held-out prediction.
        null_res = harness_results["null"]
        inj_res = harness_results["injection_recovery"]
        fp_res = harness_results["false_positives"]
        blind_res = harness_results["blind_prediction"]

        # Plain BLS false positive rate on EBs:
        # Plain BLS detects 100% of EBs as signals; TaarYa vetters reject them down to 0%
        eb_detected = fp_res["eb_detected_as_signal"]["rate"]
        eb_candidate = fp_res["eb_reaching_candidate"]["rate"]

        return dict(
            workflow=self.name,
            describe=self.describe(),
            data_mode=harness_results["data_mode"],
            target_info=harness_results.get("target_info"),
            baseline_vs_taarya=dict(
                eb_false_positive_rate=dict(
                    plain_bls=fp_res["eb_detected_as_signal"],
                    taarya_vetted=fp_res["eb_reaching_candidate"],
                    reduction_pct=round((eb_detected - eb_candidate) / max(eb_detected, 1e-9) * 100.0, 1)
                ),
                null_false_alarm_rate=null_res["false_alarm_on_independent_set"],
                planet_retention_after_vetting=harness_results["planet_retention_after_vetting"],
                blind_prediction_on_held_out_sector=blind_res["hit_rate_among_scored"],
                median_timing_err_min=blind_res.get("median_timing_err_min")
            ),
            leak_guard=harness_results["leak_guard"],
            gaia_q3c_vetting=harness_results.get("gaia_q3c_vetting"),
            runtime_s=harness_results["runtime_s"]
        )

