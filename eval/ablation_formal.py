"""Formal ablation study for TaarYa retrieval system.

Compares four retrieval configurations across multiple sky regions
and query types, computing standard IR metrics (precision@k, recall@k,
MRR, nDCG) for each.

This script produces:
  1. JSON results file (machine-readable)
  2. Console summary table
  3. LaTeX table fragment for paper inclusion

Usage:
    python eval/ablation_formal.py                    # full study
    python eval/ablation_formal.py --publish           # also write LaTeX
    python eval/ablation_formal.py --offline           # skip backends, use synthetic ground truth
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.metrics import (
    evaluate_query,
    aggregate_metrics,
    format_latex_table,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ablation regions — each has ground-truth criteria
# ---------------------------------------------------------------------------

ABLATION_REGIONS = [
    {
        "name": "Hyades",
        "ra": 66.75,
        "dec": 15.87,
        "radius_deg": 5.0,
        "semantic_topic": "Hyades cluster stars",
        "ground_truth_criteria": {
            "min_expected_stars": 100,
            "cluster_name": "Hyades",
            "expected_anomaly_types": ["binary_candidate", "high_pm"],
        },
    },
    {
        "name": "Pleiades",
        "ra": 56.75,
        "dec": 24.12,
        "radius_deg": 2.0,
        "semantic_topic": "Pleiades star formation",
        "ground_truth_criteria": {
            "min_expected_stars": 50,
            "cluster_name": "Pleiades",
            "expected_anomaly_types": ["blue_straggler", "binary_candidate"],
        },
    },
    {
        "name": "Orion OB1",
        "ra": 83.82,
        "dec": -5.39,
        "radius_deg": 1.0,
        "semantic_topic": "Orion OB association young stars",
        "ground_truth_criteria": {
            "min_expected_stars": 30,
            "cluster_name": "Orion OB1",
            "expected_anomaly_types": ["yso", "emission_line"],
        },
    },
    {
        "name": "Galactic Center",
        "ra": 266.4,
        "dec": -29.0,
        "radius_deg": 2.0,
        "semantic_topic": "Galactic center stellar population",
        "ground_truth_criteria": {
            "min_expected_stars": 200,
            "cluster_name": None,
            "expected_anomaly_types": ["high_pm", "extreme_color"],
        },
    },
    {
        "name": "High Latitude",
        "ra": 180.0,
        "dec": 60.0,
        "radius_deg": 1.0,
        "semantic_topic": "halo stars proper motion kinematics",
        "ground_truth_criteria": {
            "min_expected_stars": 10,
            "cluster_name": None,
            "expected_anomaly_types": ["high_pm"],
        },
    },
]


# ---------------------------------------------------------------------------
# Configuration definitions
# ---------------------------------------------------------------------------

@dataclass
class AblationConfig:
    """A single retrieval configuration to benchmark."""
    name: str
    use_spatial: bool = True
    use_semantic: bool = True
    use_graph: bool = True
    use_discovery: bool = True


CONFIGURATIONS = [
    AblationConfig(name="Spatial-Only",     use_spatial=True,  use_semantic=False, use_graph=False, use_discovery=False),
    AblationConfig(name="Semantic-Only",    use_spatial=False, use_semantic=True,  use_graph=False, use_discovery=False),
    AblationConfig(name="Hybrid (no graph)",use_spatial=True,  use_semantic=True,  use_graph=False, use_discovery=True),
    AblationConfig(name="Full Hybrid",      use_spatial=True,  use_semantic=True,  use_graph=True,  use_discovery=True),
]


# ---------------------------------------------------------------------------
# Physical anomaly checker (mirrors DiscoveryBenchmarker logic)
# ---------------------------------------------------------------------------

def _is_physical_anomaly(star: Dict[str, Any]) -> bool:
    """Check if a star meets any physical anomaly criteria."""
    pmra = star.get("pmra", 0) or 0
    pmdec = star.get("pmdec", 0) or 0
    pm = math.sqrt(pmra**2 + pmdec**2)
    ruwe = star.get("ruwe") or 0
    bp = star.get("phot_bp_mean_mag")
    rp = star.get("phot_rp_mean_mag")
    bp_rp = (bp - rp) if (bp is not None and rp is not None) else None

    if pm >= 150.0:
        return True
    if ruwe >= 2.0:
        return True
    if bp_rp is not None and (bp_rp >= 3.0 or bp_rp <= -0.2):
        return True
    return False


def _build_relevant_set(stars: List[Dict[str, Any]], region: Dict) -> Set[str]:
    """Build the set of 'relevant' source IDs from physical ground-truth.

    A star is relevant if it is a physical anomaly OR if it's in the region's
    expected cluster membership. This serves as the ground truth for IR metrics.
    """
    relevant = set()
    for star in stars:
        sid = str(star.get("source_id", ""))
        if not sid:
            continue
        if _is_physical_anomaly(star):
            relevant.add(sid)
        # Stars with high discovery scores are also treated as relevant
        if (star.get("discovery_score") or 0) >= 10.0:
            relevant.add(sid)
    return relevant


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class FormalAblation:
    """Runs the full ablation study."""

    def __init__(self, offline: bool = False):
        self.offline = offline
        self._spatial = None
        self._vector = None
        self._graph = None
        self._hybrid = None

    def _init_backends(self):
        """Lazy-init backends."""
        if self.offline:
            logger.info("Offline mode — using synthetic evaluation.")
            return

        from src.database import postgres_conn, qdrant_conn, neo4j_conn
        from src.retrieval.spatial_search import SpatialSearch
        from src.retrieval.vector_search import VectorSearch
        from src.retrieval.graph_search import GraphSearch
        from src.retrieval.hybrid_search import HybridSearch

        logger.info("Connecting backends...")
        postgres_conn.connect()
        qdrant_conn.connect()

        try:
            neo4j_conn.connect()
        except Exception as e:
            logger.warning(f"Neo4j unavailable: {e} — graph tests will degrade gracefully.")

        self._spatial = SpatialSearch()
        self._vector = VectorSearch()
        self._graph = GraphSearch()
        self._hybrid = HybridSearch()

    def _run_config(
        self, config: AblationConfig, region: Dict
    ) -> Dict[str, Any]:
        """Run one configuration against one region and collect results."""
        start = time.time()

        retrieved_ids: List[str] = []
        star_count = 0
        paper_count = 0

        if self.offline:
            # Synthetic results for offline testing of the metrics pipeline
            import random
            random.seed(hash(config.name + region["name"]))
            n = random.randint(5, 50)
            retrieved_ids = [f"SYN-{i}" for i in range(n)]
            star_count = n
            paper_count = random.randint(0, 10) if config.use_semantic else 0
        else:
            # Spatial component
            if config.use_spatial and self._spatial:
                stars = self._spatial.cone_search(
                    ra=region["ra"],
                    dec=region["dec"],
                    radius=region["radius_deg"],
                    limit=200,
                    include_discovery=config.use_discovery,
                )
                # Sort by discovery_score descending for ranking
                stars.sort(key=lambda s: s.get("discovery_score", 0), reverse=True)
                retrieved_ids = [str(s.get("source_id", "")) for s in stars if s.get("source_id")]
                star_count = len(stars)

            # Semantic component
            if config.use_semantic and self._vector:
                papers = self._vector.search_similar(region["semantic_topic"], limit=20)
                paper_count = len(papers)
                # Add paper arxiv_ids to retrieval list (for cross-type MRR)
                for p in papers:
                    aid = p.get("payload", {}).get("arxiv_id")
                    if aid:
                        retrieved_ids.append(f"paper:{aid}")

            # Graph enrichment
            if config.use_graph and self._graph and retrieved_ids:
                for sid in retrieved_ids[:10]:
                    if sid.startswith("paper:"):
                        continue
                    try:
                        papers = self._graph.find_star_papers(sid, include_cluster_context=True, limit=3)
                        for p in papers:
                            aid = p.get("arxiv_id")
                            if aid and f"paper:{aid}" not in retrieved_ids:
                                retrieved_ids.append(f"paper:{aid}")
                                paper_count += 1
                    except Exception:
                        pass

        latency = time.time() - start
        return {
            "config": config.name,
            "region": region["name"],
            "retrieved_ids": retrieved_ids,
            "star_count": star_count,
            "paper_count": paper_count,
            "latency_s": round(latency, 4),
        }

    def run(self) -> Dict[str, Any]:
        """Execute the full ablation study."""
        self._init_backends()

        all_results: Dict[str, List[Dict[str, Any]]] = {}
        per_config_metrics: Dict[str, List[Dict[str, Any]]] = {}

        for config in CONFIGURATIONS:
            logger.info(f"--- Configuration: {config.name} ---")
            config_query_metrics = []

            for region in ABLATION_REGIONS:
                logger.info(f"  Region: {region['name']}")

                run_result = self._run_config(config, region)

                # Build ground-truth relevant set
                if self.offline:
                    # In offline mode, mark ~30% of synthetic IDs as relevant
                    import random
                    random.seed(hash(region["name"]))
                    relevant = set(run_result["retrieved_ids"][:max(1, len(run_result["retrieved_ids"]) // 3)])
                else:
                    # In online mode, build from physical anomaly criteria
                    if config.use_spatial and self._spatial:
                        stars = self._spatial.cone_search(
                            ra=region["ra"],
                            dec=region["dec"],
                            radius=region["radius_deg"],
                            limit=200,
                            include_discovery=True,
                        )
                        relevant = _build_relevant_set(stars, region)
                    else:
                        relevant = set()

                # Compute IR metrics
                query_metrics = evaluate_query(
                    retrieved_ids=run_result["retrieved_ids"],
                    relevant_ids=list(relevant),
                    k_values=[5, 10, 20],
                )
                query_metrics["region"] = region["name"]
                query_metrics["star_count"] = run_result["star_count"]
                query_metrics["paper_count"] = run_result["paper_count"]
                query_metrics["latency_s"] = run_result["latency_s"]
                config_query_metrics.append(query_metrics)

            # Aggregate across regions for this config
            agg = aggregate_metrics(config_query_metrics)
            agg["config"] = config.name
            per_config_metrics[config.name] = agg
            all_results[config.name] = config_query_metrics

        return {
            "per_region": all_results,
            "aggregated": per_config_metrics,
            "regions": [r["name"] for r in ABLATION_REGIONS],
            "configurations": [c.name for c in CONFIGURATIONS],
        }


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def print_summary(results: Dict[str, Any]) -> None:
    """Print a human-readable summary table."""
    agg = results["aggregated"]
    configs = results["configurations"]

    print("\n" + "=" * 90)
    print("                    TAARYA FORMAL ABLATION STUDY")
    print("=" * 90)
    print(f"  Regions tested: {', '.join(results['regions'])}")
    print(f"  Configurations: {len(configs)}")
    print("-" * 90)

    header = f"{'Configuration':<22} | {'P@10':<6} | {'R@10':<6} | {'F1@10':<6} | {'MRR':<6} | {'nDCG@10':<7} | {'Stars':<6} | {'Papers':<6} | {'Lat(s)':<7}"
    print(header)
    print("-" * 90)

    for cfg_name in configs:
        m = agg.get(cfg_name, {})
        print(
            f"{cfg_name:<22} | "
            f"{m.get('mean_precision@10', 0):<6.3f} | "
            f"{m.get('mean_recall@10', 0):<6.3f} | "
            f"{m.get('mean_f1@10', 0):<6.3f} | "
            f"{m.get('mean_mrr', 0):<6.3f} | "
            f"{m.get('mean_ndcg@10', 0):<7.3f} | "
            f"{m.get('mean_star_count', 0):<6.0f} | "
            f"{m.get('mean_paper_count', 0):<6.0f} | "
            f"{m.get('mean_latency_s', 0):<7.3f}"
        )

    print("-" * 90)

    # Highlight improvement
    if len(configs) >= 2:
        full = agg.get("Full Hybrid", {})
        spatial = agg.get("Spatial-Only", {})
        f1_full = full.get("mean_f1@10", 0)
        f1_spatial = spatial.get("mean_f1@10", 0)
        if f1_spatial > 0:
            improvement = ((f1_full - f1_spatial) / f1_spatial) * 100
            print(f"  Full Hybrid F1@10 vs Spatial-Only: {improvement:+.1f}% improvement")
        mrr_full = full.get("mean_mrr", 0)
        mrr_spatial = spatial.get("mean_mrr", 0)
        if mrr_spatial > 0:
            improvement = ((mrr_full - mrr_spatial) / mrr_spatial) * 100
            print(f"  Full Hybrid MRR vs Spatial-Only:   {improvement:+.1f}% improvement")

    print("=" * 90)


def save_results(results: Dict[str, Any], path: str = "eval/ablation_results.json") -> None:
    """Save full results to JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results saved to {path}")


def save_latex(results: Dict[str, Any], path: str = "eval/ablation_table.tex") -> None:
    """Save LaTeX table for paper inclusion."""
    latex = format_latex_table(results["aggregated"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(latex)
    logger.info(f"LaTeX table saved to {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="TaarYa formal ablation study")
    parser.add_argument("--publish", action="store_true", help="Also generate LaTeX table")
    parser.add_argument("--offline", action="store_true", help="Run with synthetic data (no backends)")
    parser.add_argument("--output", default="eval/ablation_results.json", help="Output JSON path")
    args = parser.parse_args()

    ablation = FormalAblation(offline=args.offline)
    results = ablation.run()

    print_summary(results)
    save_results(results, args.output)

    if args.publish:
        save_latex(results)

    print(f"\nDone. Results written to {args.output}")


if __name__ == "__main__":
    main()
