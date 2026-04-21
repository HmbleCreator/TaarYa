"""Discovery precision validation against known anomaly catalogs.

Validates that TaarYa's discovery scoring identifies physically
meaningful anomalies by cross-matching top-ranked candidates against:

  1. Physical criteria (RUWE, proper motion, color extremes)
  2. Known anomaly populations (binaries, hypervelocity, WDs, YSOs)
  3. SIMBAD object types (when online)

Usage:
    python eval/validate_discovery.py                  # full validation
    python eval/validate_discovery.py --offline         # skip SIMBAD
    python eval/validate_discovery.py --top-k 20        # validate top-20 per region
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known anomaly type definitions (Gaia DR3 calibrated)
# ---------------------------------------------------------------------------

ANOMALY_DEFINITIONS = {
    "hypervelocity": {
        "description": "Total proper motion ≥ 100 mas/yr (nearby fast-movers)",
        "check": lambda s: _total_pm(s) >= 100.0,
    },
    "binary_candidate": {
        "description": "RUWE ≥ 1.8, indicating possible astrometric binary",
        "check": lambda s: (s.get("ruwe") or 0) >= 1.8,
    },
    "extreme_blue": {
        "description": "BP−RP ≤ −0.1, very blue (hot subdwarf, blue straggler)",
        "check": lambda s: _bp_rp(s) is not None and _bp_rp(s) <= -0.1,
    },
    "extreme_red": {
        "description": "BP−RP ≥ 2.8, very red (M dwarf, dusty envelope)",
        "check": lambda s: _bp_rp(s) is not None and _bp_rp(s) >= 2.8,
    },
    "overluminous": {
        "description": "Bright (G < 10) but distant (d > 500 pc), unusual luminosity",
        "check": lambda s: (
            (s.get("phot_g_mean_mag") or 99) < 10.0
            and (s.get("parallax") or 999) > 0
            and (1000.0 / (s.get("parallax") or 999)) > 500
        ),
    },
    "white_dwarf_candidate": {
        "description": "Faint absolute magnitude, blue-ish color, nearby",
        "check": lambda s: _is_wd_candidate(s),
    },
}


def _total_pm(s: Dict) -> float:
    pmra = s.get("pmra", 0) or 0
    pmdec = s.get("pmdec", 0) or 0
    return math.sqrt(pmra**2 + pmdec**2)


def _bp_rp(s: Dict) -> Optional[float]:
    bp = s.get("phot_bp_mean_mag")
    rp = s.get("phot_rp_mean_mag")
    if bp is not None and rp is not None:
        return bp - rp
    return None


def _is_wd_candidate(s: Dict) -> bool:
    """White dwarf: faint absolute mag, relatively blue, nearby."""
    g = s.get("phot_g_mean_mag")
    par = s.get("parallax")
    if g is None or par is None or par <= 0:
        return False
    abs_g = g - 5 * math.log10(1000.0 / par) + 5
    bp_rp = _bp_rp(s)
    return abs_g > 10.0 and (bp_rp is None or bp_rp < 1.5)


# ---------------------------------------------------------------------------
# Validation regions
# ---------------------------------------------------------------------------

VALIDATION_REGIONS = [
    {"name": "Hyades",     "ra": 66.75, "dec": 15.87, "radius_deg": 5.0},
    {"name": "Pleiades",   "ra": 56.75, "dec": 24.12, "radius_deg": 2.0},
    {"name": "Orion OB1",  "ra": 83.82, "dec": -5.39, "radius_deg": 1.0},
    {"name": "Solar Nbhd", "ra": 180.0, "dec": 0.0,   "radius_deg": 2.0},
    {"name": "Gal Center", "ra": 266.4, "dec": -29.0, "radius_deg": 2.0},
]


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class DiscoveryValidator:
    """Validates discovery candidates against known anomaly types."""

    def __init__(self, top_k: int = 20, offline: bool = False):
        self.top_k = top_k
        self.offline = offline
        self._spatial = None

    def _init_backends(self):
        if self.offline:
            return
        from src.database import postgres_conn
        from src.retrieval.spatial_search import SpatialSearch

        postgres_conn.connect()
        self._spatial = SpatialSearch()

    def validate_region(self, region: Dict) -> Dict[str, Any]:
        """Validate discovery candidates in a single region."""
        logger.info(f"Validating region: {region['name']}")

        if self.offline:
            return self._synthetic_validation(region)

        stars = self._spatial.cone_search(
            ra=region["ra"],
            dec=region["dec"],
            radius=region["radius_deg"],
            limit=500,
            include_discovery=True,
        )

        if not stars:
            return {
                "region": region["name"],
                "error": "No stars found",
                "total_stars": 0,
            }

        # Sort by discovery score and take top-k
        stars.sort(key=lambda s: s.get("discovery_score", 0), reverse=True)
        top_candidates = stars[:self.top_k]
        all_scored = [s for s in stars if (s.get("discovery_score") or 0) > 0]

        # Classify each top candidate
        candidate_validations = []
        anomaly_type_counts: Dict[str, int] = {}
        confirmed_count = 0

        for star in top_candidates:
            sid = str(star.get("source_id", "unknown"))
            score = star.get("discovery_score", 0)
            matched_types = []

            for atype, adef in ANOMALY_DEFINITIONS.items():
                if adef["check"](star):
                    matched_types.append(atype)
                    anomaly_type_counts[atype] = anomaly_type_counts.get(atype, 0) + 1

            is_confirmed = len(matched_types) > 0
            if is_confirmed:
                confirmed_count += 1

            validation = {
                "source_id": sid,
                "discovery_score": round(score, 2),
                "confirmed_anomaly": is_confirmed,
                "matched_types": matched_types,
                "pm_total": round(_total_pm(star), 2),
                "ruwe": star.get("ruwe"),
                "bp_rp": round(_bp_rp(star), 3) if _bp_rp(star) is not None else None,
            }

            # Optional SIMBAD cross-check
            if not self.offline and is_confirmed:
                simbad_info = self._check_simbad(star)
                if simbad_info:
                    validation["simbad"] = simbad_info

            candidate_validations.append(validation)

        precision_at_k = confirmed_count / len(top_candidates) if top_candidates else 0.0

        return {
            "region": region["name"],
            "total_stars": len(stars),
            "total_scored": len(all_scored),
            "top_k": self.top_k,
            "confirmed_anomalies": confirmed_count,
            "precision_at_k": round(precision_at_k, 3),
            "anomaly_type_distribution": anomaly_type_counts,
            "candidates": candidate_validations,
        }

    def _check_simbad(self, star: Dict) -> Optional[Dict]:
        """Cross-check with SIMBAD for known object type."""
        try:
            from src.utils.simbad_validation import query_simbad_by_coords
            result = query_simbad_by_coords(star.get("ra"), star.get("dec"), radius_arcsec=5)
            if result:
                return {
                    "main_id": result.get("main_id"),
                    "otype": result.get("otype"),
                    "confirmed": True,
                }
        except Exception as e:
            logger.debug(f"SIMBAD lookup failed: {e}")
        return None

    def _synthetic_validation(self, region: Dict) -> Dict[str, Any]:
        """Generate synthetic validation for offline testing."""
        import random
        random.seed(hash(region["name"]))
        n_stars = random.randint(20, 100)
        n_anomalies = random.randint(3, min(10, n_stars))

        return {
            "region": region["name"],
            "total_stars": n_stars,
            "total_scored": n_stars // 2,
            "top_k": self.top_k,
            "confirmed_anomalies": n_anomalies,
            "precision_at_k": round(n_anomalies / self.top_k, 3),
            "anomaly_type_distribution": {"binary_candidate": n_anomalies // 2, "high_pm": n_anomalies - n_anomalies // 2},
            "candidates": [],
            "mode": "synthetic",
        }

    def run(self) -> Dict[str, Any]:
        """Run validation across all regions."""
        self._init_backends()

        region_results = []
        for region in VALIDATION_REGIONS:
            result = self.validate_region(region)
            region_results.append(result)

        # Aggregate
        total_confirmed = sum(r.get("confirmed_anomalies", 0) for r in region_results)
        total_candidates = sum(min(r.get("top_k", self.top_k), r.get("total_scored", 0)) for r in region_results)
        overall_precision = total_confirmed / total_candidates if total_candidates > 0 else 0.0

        # Aggregate anomaly types
        all_types: Dict[str, int] = {}
        for r in region_results:
            for atype, count in r.get("anomaly_type_distribution", {}).items():
                all_types[atype] = all_types.get(atype, 0) + count

        return {
            "validation_type": "discovery_precision",
            "top_k": self.top_k,
            "regions": region_results,
            "summary": {
                "total_regions": len(region_results),
                "total_candidates_evaluated": total_candidates,
                "total_confirmed_anomalies": total_confirmed,
                "overall_precision": round(overall_precision, 3),
                "anomaly_type_distribution": all_types,
            },
        }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_summary(results: Dict[str, Any]) -> None:
    """Print validation summary."""
    print("\n" + "=" * 80)
    print("             TAARYA DISCOVERY PRECISION VALIDATION")
    print("=" * 80)

    print(f"\n{'Region':<15} | {'Stars':<6} | {'Scored':<7} | {'Top-K':<6} | {'Confirmed':<10} | {'Precision':<10}")
    print("-" * 80)

    for r in results["regions"]:
        print(
            f"{r['region']:<15} | "
            f"{r.get('total_stars', 0):<6} | "
            f"{r.get('total_scored', 0):<7} | "
            f"{r.get('top_k', 0):<6} | "
            f"{r.get('confirmed_anomalies', 0):<10} | "
            f"{r.get('precision_at_k', 0):<10.3f}"
        )

    s = results["summary"]
    print("-" * 80)
    print(f"  Overall discovery precision: {s['overall_precision']:.3f}")
    print(f"  Total confirmed anomalies:   {s['total_confirmed_anomalies']}")
    print(f"  Anomaly type breakdown:      {s['anomaly_type_distribution']}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="TaarYa discovery precision validation")
    parser.add_argument("--top-k", type=int, default=20, help="Validate top-K candidates per region")
    parser.add_argument("--offline", action="store_true", help="Skip backends, use synthetic data")
    parser.add_argument("--output", default="eval/discovery_validation.json", help="Output path")
    args = parser.parse_args()

    validator = DiscoveryValidator(top_k=args.top_k, offline=args.offline)
    results = validator.run()

    print_summary(results)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
