"""Scoring calibration and benchmark suite for the Discovery Engine."""

import logging
from typing import List, Dict, Any, Tuple
import numpy as np

logger = logging.getLogger(__name__)

class DiscoveryBenchmarker:
    """
    Benchmarks discovery scoring weights against 'Ground Truth' populations.
    Validates sensitivity for Hypervelocity stars and Binary candidates.
    """

    # Ground-truth criteria for 'Known Anomalies' (based on Gaia DR3 standards)
    GROUND_TRUTH = {
        "hypervelocity": {
            "min_pm": 150.0,      # mas/yr
            "max_parallax": 5.0,  # Far away but fast
            "min_score": 12.0
        },
        "binary_candidate": {
            "min_ruwe": 2.0,
            "min_parallax": 2.0,  # Nearby enough for noise to be real
            "min_score": 10.0
        },
        "extreme_color": {
            "min_bp_rp": 3.0,     # Very red
            "max_bp_rp": -0.2,    # Very blue
            "min_score": 8.0
        }
    }

    def evaluate_precision_recall(self, scored_stars: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate precision and recall for the discovery engine.
        Treats stars meeting GROUND_TRUTH criteria as 'True Anomalies'.
        """
        tp = 0 # True Positives (Flagged by score AND meets physical ground truth)
        fp = 0 # False Positives (Flagged by score but DOES NOT meet ground truth)
        fn = 0 # False Negatives (Meets ground truth but NOT flagged by score)
        tn = 0 # True Negatives (Not flagged and not an anomaly)

        threshold = 8.0 # Discovery threshold for 'Flagged'

        for s in scored_stars:
            is_flagged = s.get("discovery_score", 0) >= threshold
            is_real_anomaly = self._is_physical_anomaly(s)

            if is_flagged and is_real_anomaly: tp += 1
            elif is_flagged and not is_real_anomaly: fp += 1
            elif not is_flagged and is_real_anomaly: fn += 1
            else: tn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        return {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1_score": round(f1, 3),
            "total_analyzed": len(scored_stars)
        }

    def _is_physical_anomaly(self, s: Dict[str, Any]) -> bool:
        """Check if star meets any ground-truth physical criteria."""
        pm = s.get("pm", 0)
        ruwe = s.get("ruwe", 0)
        parallax = s.get("parallax", 0)
        bp_rp = s.get("bp_rp_color")

        # Hypervelocity check
        if pm >= self.GROUND_TRUTH["hypervelocity"]["min_pm"]:
            return True
        # Binary check
        if ruwe >= self.GROUND_TRUTH["binary_candidate"]["min_ruwe"]:
            return True
        # Color check
        if bp_rp is not None:
            if bp_rp >= self.GROUND_TRUTH["extreme_color"]["min_bp_rp"] or \
               bp_rp <= self.GROUND_TRUTH["extreme_color"]["max_bp_rp"]:
                return True
        
        return False

    def calibrate_weights(self, stars: List[Dict[str, Any]], target_precision: float = 0.9) -> Dict[str, float]:
        """
        Suggests weight adjustments to reach a target precision.
        """
        # Logic for automated hyperparameter tuning could go here.
        # For now, we return the calibration status.
        metrics = self.evaluate_precision_recall(stars)
        if metrics["precision"] < target_precision:
            return {"status": "Weights too aggressive (High False Positives). Consider increasing RUWE threshold."}
        return {"status": "Weights calibrated (High Precision)."}
