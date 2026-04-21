"""Multi-seed discovery scoring and statistical interpretability."""

import math
import logging
import random
from typing import List, Dict, Any, Optional
import numpy as np
from src.retrieval.discovery import rank_discovery_candidates, discovery_profile

logger = logging.getLogger(__name__)

class MultiSeedDiscovery:
    """
    Quantifies the statistical robustness of discovery scores by running
    multiple trials with perturbed weights (Monte Carlo approach).
    """

    def __init__(self, seeds: List[int] = [42, 43, 44, 45, 46]):
        self.seeds = seeds

    def _perturb_profile(self, profile: Dict[str, float], seed: int) -> Dict[str, float]:
        """Perturb profile weights by +/- 10% based on seed."""
        random.seed(seed)
        perturbed = {}
        for k, v in profile.items():
            # Add Gaussian noise (std=0.05) to simulate uncertainty in priors
            noise = random.gauss(0, 0.05)
            perturbed[k] = v * (1.0 + noise)
        return perturbed

    def compute_robust_scores(self, rows: List[Dict[str, Any]], mode: str = "balanced") -> List[Dict[str, Any]]:
        """
        Run discovery ranking across multiple seeds and calculate mean/std.
        """
        base_profile = discovery_profile(mode)
        all_results = []
        
        # 1. Collect scores across seeds
        for seed in self.seeds:
            perturbed_profile = self._perturb_profile(base_profile, seed)
            
            # Use the base ranker with the perturbed profile to ensure consistency
            ranking_result = rank_discovery_candidates(
                rows, 
                mode=mode, 
                override_profile=perturbed_profile,
                limit=len(rows) # Get all scores
            )
            
            trial_scores = {
                item["source_id"]: item["score"] 
                for item in ranking_result["top_candidates"]
            }
            all_results.append(trial_scores)

        # 2. Aggregate results
        robust_results = []
        for row in rows:
            sid = row["source_id"]
            scores = [res[sid] for res in all_results if sid in res]
            
            if not scores:
                continue
                
            mean_score = np.mean(scores)
            std_score = np.std(scores)
            
            # Feature importance (SHAP-like)
            importance = self._calculate_feature_importance(row, base_profile)
            
            robust_results.append({
                "source_id": sid,
                "mean_score": round(float(mean_score), 2),
                "std_dev": round(float(std_score), 3),
                "confidence": "High" if std_score < 1.0 else "Medium" if std_score < 3.0 else "Low",
                "feature_importance": importance
            })
            
        return sorted(robust_results, key=lambda x: x["mean_score"], reverse=True)

    def _calculate_feature_importance(self, row: Dict[str, Any], profile: Dict[str, float]) -> Dict[str, float]:
        """Simple SHAP-like feature importance based on contribution to total score."""
        contributions = {}
        
        ruwe = row.get("ruwe")
        if ruwe:
            if ruwe >= 2.0: contributions["Astrometry (RUWE)"] = profile["ruwe_high"]
            elif ruwe >= 1.4: contributions["Astrometry (RUWE)"] = profile["ruwe_elevated"]
        
        bp = row.get("phot_bp_mean_mag")
        rp = row.get("phot_rp_mean_mag")
        if bp and rp:
            bp_rp = bp - rp
            if bp_rp <= -0.1 or bp_rp >= 2.8:
                contributions["Photometry (Color)"] = profile["color_extreme"]

        pmra = row.get("pmra")
        pmdec = row.get("pmdec")
        if pmra is not None and pmdec is not None:
            motion = math.sqrt(pmra**2 + pmdec**2)
            if motion >= 80: contributions["Kinematics (Motion)"] = profile["motion_high"]
            elif motion >= 40: contributions["Kinematics (Motion)"] = profile["motion_mid"]

        total = sum(contributions.values()) or 1.0
        return {k: round(v/total, 2) for k, v in contributions.items()}
