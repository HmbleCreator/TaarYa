"""Formal ablation study for TaarYa retrieval system.

Compares four retrieval configurations across multiple sky regions
and query types, computing standard IR metrics (precision@k, recall@k,
MRR, nDCG, MAP) for each.

FIXES (v2):
  - Ground truth pre-computed ONCE, independently of any config (no data leakage)
  - Physical-anomaly ground truth is the default; discovery_score labels are opt-in only
  - Anomaly thresholds aligned with discovery.py (RUWE 1.4, PM 40 mas/yr)
  - Semantic results mapped to star source_ids via graph, or evaluated separately
  - Empty regions flagged and excluded from aggregation
  - Reciprocal Rank Fusion (RRF) for hybrid ranking
  - Per-region metrics + bootstrap CIs reported

Usage:
    python eval/ablation_formal.py                    # full study
    python eval/ablation_formal.py --publish           # also write LaTeX
    python eval/ablation_formal.py --offline           # skip backends, use synthetic ground truth
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.metrics import (
    evaluate_query,
    aggregate_metrics,
    format_latex_table,
    average_precision,
    bootstrap_confidence_interval,
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
    AblationConfig(name="Spatial-Only",      use_spatial=True,  use_semantic=False, use_graph=False, use_discovery=False),
    AblationConfig(name="Semantic-Only",     use_spatial=False, use_semantic=True,  use_graph=False, use_discovery=False),
    AblationConfig(name="Hybrid (no graph)", use_spatial=True,  use_semantic=True,  use_graph=False, use_discovery=True),
    AblationConfig(name="Full Hybrid",       use_spatial=True,  use_semantic=True,  use_graph=True,  use_discovery=True),
]


def _stable_seed(value: str) -> int:
    """Return a process-independent seed for reproducible offline fixtures."""
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big")


# ---------------------------------------------------------------------------
# Physical anomaly checker — ALIGNED with discovery.py thresholds
# ---------------------------------------------------------------------------

def _is_physical_anomaly(star: Dict[str, Any]) -> bool:
    """Check if a star meets physical anomaly criteria.

    Thresholds are aligned with src/retrieval/discovery.py:
    - RUWE >= 1.4: Gaia DR3 astrometric quality flag (poor single-star fit)
    - PM >= 40 mas/yr: high proper motion (nearby or kinematically unusual)
    - BP-RP >= 2.8 or <= -0.1: extreme color (very red/blue)
    """
    pmra = star.get("pmra", 0) or 0
    pmdec = star.get("pmdec", 0) or 0
    pm = math.sqrt(pmra ** 2 + pmdec ** 2)
    ruwe = star.get("ruwe") or 0
    bp = star.get("phot_bp_mean_mag")
    rp = star.get("phot_rp_mean_mag")
    bp_rp = (bp - rp) if (bp is not None and rp is not None) else None

    # Aligned with discovery.py SCIENTIFIC_THRESHOLDS
    if pm >= 40.0:
        return True
    if ruwe >= 1.4:
        return True
    if bp_rp is not None and (bp_rp >= 2.8 or bp_rp <= -0.1):
        return True
    return False


def _build_relevant_set(
    stars: List[Dict[str, Any]],
    region: Dict,
    include_discovery_score: bool = False,
) -> Set[str]:
    """Build the set of 'relevant' source IDs from physical ground-truth.

    By default, relevance is defined only by physical anomaly criteria.
    Discovery scores come from the retrieval-side ranking logic, so they
    are opt-in only for diagnostic runs.
    """
    relevant = set()
    for star in stars:
        sid = str(star.get("source_id", ""))
        if not sid:
            continue
        if _is_physical_anomaly(star):
            relevant.add(sid)
        if include_discovery_score and (star.get("discovery_score") or 0) >= 10.0:
            relevant.add(sid)
    return relevant


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion (RRF) — proper score fusion for hybrid
# ---------------------------------------------------------------------------

def rrf_merge(
    *ranked_lists: List[str],
    k: int = 60,
    weights: Optional[List[float]] = None,
) -> List[str]:
    """Merge multiple ranked lists using Reciprocal Rank Fusion.

    RRF(d) = Σ  1 / (k + rank_i(d))

    This is the standard score-free fusion method from Cormack et al. (2009).
    It outperforms simple concatenation and doesn't require score normalization.

    Args:
        *ranked_lists: Variable number of ranked ID lists.
        k: Smoothing constant (default 60 per the original paper).

    Returns:
        Merged ranked list, highest RRF score first.
    """
    if weights is None:
        weights = [1.0] * len(ranked_lists)
    if len(weights) != len(ranked_lists):
        raise ValueError("weights length must match ranked_lists length")

    scores: Dict[str, float] = {}
    for weight, rlist in zip(weights, ranked_lists):
        for rank, item_id in enumerate(rlist):
            scores[item_id] = scores.get(item_id, 0.0) + weight / (k + rank)
    return sorted(scores.keys(), key=lambda x: scores[x], reverse=True)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class FormalAblation:
    """Runs the full ablation study."""

    def __init__(
        self,
        offline: bool = False,
        include_discovery_ground_truth: bool = False,
    ):
        self.offline = offline
        self.include_discovery_ground_truth = include_discovery_ground_truth
        self._spatial = None
        self._vector = None
        self._graph = None
        self._hybrid = None
        self._ground_truths: Dict[str, Set[str]] = {}  # region_name -> relevant set
        self._region_star_counts: Dict[str, int] = {}

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

    def _precompute_ground_truth(self):
        """Build ground truth ONCE, independently of any retrieval config.

        This is the key fix for data leakage: the relevant set is computed
        from a single comprehensive spatial query that is NOT used as any
        config's retrieval result.
        """
        logger.info("=== Pre-computing ground truth (independent of configs) ===")

        for region in ABLATION_REGIONS:
            name = region["name"]

            if self.offline:
                # Synthetic ground truth for offline testing
                random.seed(_stable_seed(name + "_gt"))
                n_gt = random.randint(5, 30)
                self._ground_truths[name] = {f"GT-{name}-{i}" for i in range(n_gt)}
                self._region_star_counts[name] = random.randint(50, 200)
                logger.info(f"  {name}: {n_gt} synthetic relevant items")
                continue

            if self._spatial is None:
                self._ground_truths[name] = set()
                self._region_star_counts[name] = 0
                continue

            gt_limit = max(1000, region["ground_truth_criteria"]["min_expected_stars"] * 10)

            # Fetch a large pool for ground truth independent of config ranking.
            gt_stars = self._spatial.cone_search(
                ra=region["ra"],
                dec=region["dec"],
                radius=region["radius_deg"],
                limit=gt_limit,
                include_discovery=self.include_discovery_ground_truth,
            )

            self._region_star_counts[name] = len(gt_stars)

            if not gt_stars:
                logger.warning(f"  {name}: 0 stars in DB — will be excluded from aggregation")
                self._ground_truths[name] = set()
                continue

            relevant = _build_relevant_set(
                gt_stars,
                region,
                include_discovery_score=self.include_discovery_ground_truth,
            )
            self._ground_truths[name] = relevant
            logger.info(
                f"  {name}: {len(gt_stars)} total stars, "
                f"{len(relevant)} relevant ({len(relevant)/len(gt_stars)*100:.1f}%)"
            )

    def _run_config(
        self, config: AblationConfig, region: Dict
    ) -> Dict[str, Any]:
        """Run one configuration against one region and collect results."""
        start = time.time()

        spatial_ids: List[str] = []
        semantic_star_ids: List[str] = []  # stars found via semantic→graph path
        graph_star_ids: List[str] = []
        star_count = 0
        paper_count = 0

        if self.offline:
            # Synthetic results for offline testing
            random.seed(_stable_seed(config.name + region["name"]))
            gt = self._ground_truths[region["name"]]
            n = random.randint(5, 50)

            if config.use_spatial:
                # Some synthetic IDs that overlap with GT
                gt_list = sorted(gt)
                n_overlap = min(len(gt_list), n // 3)
                spatial_ids = gt_list[:n_overlap] + [f"SYN-{config.name}-{i}" for i in range(n - n_overlap)]
                star_count = len(spatial_ids)

            if config.use_semantic:
                paper_count = random.randint(2, 15)
                # In synthetic mode, semantic path finds some GT stars too
                gt_list = sorted(gt)
                n_sem = min(len(gt_list), random.randint(0, 5))
                semantic_star_ids = gt_list[:n_sem]

            if config.use_graph:
                gt_list = sorted(gt)
                n_graph = min(len(gt_list), random.randint(0, 3))
                graph_star_ids = gt_list[:n_graph]

        else:
            # ── Spatial component ──
            if config.use_spatial and self._spatial:
                stars = self._spatial.cone_search(
                    ra=region["ra"],
                    dec=region["dec"],
                    radius=region["radius_deg"],
                    limit=200,
                    include_discovery=config.use_discovery,
                )
                # Sort by discovery_score when available for ranking
                if config.use_discovery:
                    stars.sort(key=lambda s: s.get("discovery_score", 0), reverse=True)
                spatial_ids = [str(s.get("source_id", "")) for s in stars if s.get("source_id")]
                star_count = len(stars)

            # ── Semantic component ──
            if config.use_semantic and self._vector:
                papers = self._vector.search_similar(region["semantic_topic"], limit=20)
                paper_count = len(papers)

                # Map papers back to stars via graph (if available)
                # This fixes the namespace mismatch: instead of comparing paper:arxiv_id
                # against star source_ids, we resolve papers → mentioned stars
                if self._graph and papers:
                    for p in papers:
                        arxiv_id = p.get("payload", {}).get("arxiv_id")
                        if not arxiv_id:
                            continue
                        try:
                            mentioned_stars = self._graph.find_paper_stars(
                                arxiv_id,
                                limit=25,
                                include_cluster_context=config.use_graph,
                            )
                            for ms in mentioned_stars:
                                sid = str(ms.get("source_id", ""))
                                if not sid:
                                    continue
                                if ms.get("link_type") == "cluster_context":
                                    graph_star_ids.append(sid)
                                else:
                                    semantic_star_ids.append(sid)
                        except Exception:
                            pass  # graph may not have this paper

            # ── Graph enrichment ──
            if config.use_graph and self._graph:
                # Find related stars through cluster membership and co-citation
                source_pool = spatial_ids[:20] if spatial_ids else []
                for sid in source_pool:
                    try:
                        related = self._graph.find_related_stars(sid, max_hops=1)
                        for r in related:
                            rid = str(r.get("source_id", ""))
                            if rid and rid not in spatial_ids:
                                graph_star_ids.append(rid)
                    except Exception:
                        pass

        # ── Merge using RRF ──
        # Each component contributes a ranked list; RRF fuses them
        ranked_lists = []
        weights = []
        if spatial_ids:
            ranked_lists.append(spatial_ids)
            weights.append(1.0)
        if semantic_star_ids:
            ranked_lists.append(semantic_star_ids)
            weights.append(0.7 if spatial_ids else 1.0)
        if graph_star_ids:
            ranked_lists.append(graph_star_ids)
            weights.append(0.2)

        if ranked_lists:
            merged_ids = rrf_merge(*ranked_lists, k=60, weights=weights)
        else:
            merged_ids = []

        latency = time.time() - start
        return {
            "config": config.name,
            "region": region["name"],
            "retrieved_ids": merged_ids,
            "star_count": star_count,
            "paper_count": paper_count,
            "spatial_ids_count": len(spatial_ids),
            "semantic_star_ids_count": len(semantic_star_ids),
            "graph_star_ids_count": len(graph_star_ids),
            "latency_s": round(latency, 4),
        }

    def run(self) -> Dict[str, Any]:
        """Execute the full ablation study."""
        self._init_backends()
        self._precompute_ground_truth()

        all_results: Dict[str, List[Dict[str, Any]]] = {}
        per_config_metrics: Dict[str, Dict[str, Any]] = {}
        per_region_detail: Dict[str, Dict[str, Dict[str, Any]]] = {}
        skipped_regions: List[str] = []

        # Identify regions with no data (to exclude from aggregation)
        for region in ABLATION_REGIONS:
            name = region["name"]
            if self._region_star_counts.get(name, 0) == 0 and not self.offline:
                skipped_regions.append(name)
                logger.warning(f"Region '{name}' has 0 stars — excluding from aggregation")

        for config in CONFIGURATIONS:
            logger.info(f"--- Configuration: {config.name} ---")
            config_query_metrics = []

            for region in ABLATION_REGIONS:
                rname = region["name"]
                logger.info(f"  Region: {rname}")

                run_result = self._run_config(config, region)

                # Use pre-computed ground truth (no leakage)
                relevant = self._ground_truths.get(rname, set())

                # Compute IR metrics
                query_metrics = evaluate_query(
                    retrieved_ids=run_result["retrieved_ids"],
                    relevant_ids=list(relevant),
                    k_values=[5, 10, 20],
                )
                query_metrics["region"] = rname
                query_metrics["star_count"] = run_result["star_count"]
                query_metrics["paper_count"] = run_result["paper_count"]
                query_metrics["spatial_ids"] = run_result["spatial_ids_count"]
                query_metrics["semantic_star_ids"] = run_result["semantic_star_ids_count"]
                query_metrics["graph_star_ids"] = run_result["graph_star_ids_count"]
                query_metrics["latency_s"] = run_result["latency_s"]
                query_metrics["skipped"] = rname in skipped_regions

                # Store per-region detail
                if config.name not in per_region_detail:
                    per_region_detail[config.name] = {}
                per_region_detail[config.name][rname] = query_metrics

                # Only include non-skipped regions in aggregation
                if rname not in skipped_regions:
                    config_query_metrics.append(query_metrics)

            # Aggregate across valid regions for this config
            agg = aggregate_metrics(config_query_metrics)
            agg["config"] = config.name
            agg["num_valid_regions"] = len(config_query_metrics)
            agg["skipped_regions"] = [r for r in skipped_regions]

            # Add bootstrap CIs for key metrics
            for metric_key in ["precision@10", "recall@10", "ndcg@10", "mrr", "ap@10"]:
                values = [q.get(metric_key, 0.0) for q in config_query_metrics]
                ci = bootstrap_confidence_interval(values)
                agg[f"ci_{metric_key}"] = ci

            per_config_metrics[config.name] = agg
            all_results[config.name] = config_query_metrics

        return {
            "evaluation_mode": "synthetic_offline" if self.offline else "backend",
            "per_region": per_region_detail,
            "aggregated": per_config_metrics,
            "regions": [r["name"] for r in ABLATION_REGIONS],
            "valid_regions": [r["name"] for r in ABLATION_REGIONS if r["name"] not in skipped_regions],
            "skipped_regions": skipped_regions,
            "configurations": [c.name for c in CONFIGURATIONS],
            "ground_truth_sizes": {r["name"]: len(self._ground_truths.get(r["name"], set())) for r in ABLATION_REGIONS},
        }


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def print_summary(results: Dict[str, Any]) -> None:
    """Print a human-readable summary table."""
    agg = results["aggregated"]
    configs = results["configurations"]

    print("\n" + "=" * 100)
    print("                    TAARYA FORMAL ABLATION STUDY (v2 - leak-free)")
    print("=" * 100)
    print(f"  Regions tested: {', '.join(results['regions'])}")
    print(f"  Valid regions:  {', '.join(results['valid_regions'])}")
    if results["skipped_regions"]:
        print(f"  Skipped (no data): {', '.join(results['skipped_regions'])}")
    print(f"  Ground truth sizes: {results['ground_truth_sizes']}")
    print(f"  Configurations: {len(configs)}")
    print("-" * 100)

    header = (
        f"{'Configuration':<22} | {'P@10':>6} | {'R@10':>6} | {'F1@10':>6} | "
        f"{'MRR':>6} | {'nDCG@10':>7} | {'MAP@10':>7} | "
        f"{'Stars':>5} | {'Papers':>6} | {'Lat(s)':>7}"
    )
    print(header)
    print("-" * 100)

    for cfg_name in configs:
        m = agg.get(cfg_name, {})
        print(
            f"{cfg_name:<22} | "
            f"{m.get('mean_precision@10', 0):>6.3f} | "
            f"{m.get('mean_recall@10', 0):>6.3f} | "
            f"{m.get('mean_f1@10', 0):>6.3f} | "
            f"{m.get('mean_mrr', 0):>6.3f} | "
            f"{m.get('mean_ndcg@10', 0):>7.3f} | "
            f"{m.get('mean_ap@10', 0):>7.3f} | "
            f"{m.get('mean_star_count', 0):>5.0f} | "
            f"{m.get('mean_paper_count', 0):>6.0f} | "
            f"{m.get('mean_latency_s', 0):>7.3f}"
        )

    print("-" * 100)

    # Per-region breakdown
    print("\n[PER-REGION BREAKDOWN]")
    for cfg_name in configs:
        print(f"\n  {cfg_name}:")
        detail = results.get("per_region", {}).get(cfg_name, {})
        for rname, metrics in detail.items():
            skip_mark = " SKIPPED" if metrics.get("skipped") else ""
            print(
                f"    {rname:<18} | P@10={metrics.get('precision@10', 0):.3f} "
                f"R@10={metrics.get('recall@10', 0):.3f} "
                f"MRR={metrics.get('mrr', 0):.3f} "
                f"nDCG={metrics.get('ndcg@10', 0):.3f} "
                f"GT={metrics.get('total_relevant', 0)} "
                f"Ret={metrics.get('total_retrieved', 0)}"
                f"{skip_mark}"
            )

    # Bootstrap CIs
    print("\n[95% BOOTSTRAP CONFIDENCE INTERVALS]")
    for cfg_name in configs:
        m = agg.get(cfg_name, {})
        ci_p = m.get("ci_precision@10", {})
        ci_mrr = m.get("ci_mrr", {})
        ci_ndcg = m.get("ci_ndcg@10", {})
        print(
            f"  {cfg_name:<22} | "
            f"P@10: {ci_p.get('mean', 0):.3f} [{ci_p.get('lower', 0):.3f}, {ci_p.get('upper', 0):.3f}] | "
            f"MRR: {ci_mrr.get('mean', 0):.3f} [{ci_mrr.get('lower', 0):.3f}, {ci_mrr.get('upper', 0):.3f}] | "
            f"nDCG: {ci_ndcg.get('mean', 0):.3f} [{ci_ndcg.get('lower', 0):.3f}, {ci_ndcg.get('upper', 0):.3f}]"
        )

    # Improvement summary
    if len(configs) >= 2:
        full = agg.get("Full Hybrid", {})
        spatial = agg.get("Spatial-Only", {})
        print("\n[IMPROVEMENT SUMMARY]")
        for metric in ["mean_f1@10", "mean_mrr", "mean_ndcg@10", "mean_ap@10"]:
            v_full = full.get(metric, 0)
            v_spatial = spatial.get(metric, 0)
            if v_spatial > 0:
                improvement = ((v_full - v_spatial) / v_spatial) * 100
                print(f"  Full Hybrid {metric} vs Spatial-Only: {improvement:+.1f}%")
            else:
                print(f"  Full Hybrid {metric} vs Spatial-Only: {v_full:.3f} vs 0 (unbounded improvement)")

    print("=" * 100)


def save_results(results: Dict[str, Any], path: str = "eval/ablation_results.json") -> None:
    """Save full results to JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results saved to {path}")


def save_latex(results: Dict[str, Any], path: str = "eval/ablation_table.tex") -> None:
    """Save LaTeX table for paper inclusion."""
    # Build the dict expected by format_latex_table
    latex_data = {}
    for cfg_name, metrics in results["aggregated"].items():
        latex_data[cfg_name] = metrics

    latex = format_latex_table(latex_data)
    with open(path, "w", encoding="utf-8") as f:
        f.write(latex)
    logger.info(f"LaTeX table saved to {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="TaarYa formal ablation study (v2 - leak-free)")
    parser.add_argument("--publish", action="store_true", help="Also generate LaTeX table")
    parser.add_argument("--offline", action="store_true", help="Run with synthetic data (no backends)")
    parser.add_argument(
        "--include-discovery-ground-truth",
        action="store_true",
        help="Also count high discovery_score objects as relevant (diagnostic only).",
    )
    parser.add_argument("--output", default="eval/ablation_results.json", help="Output JSON path")
    args = parser.parse_args()

    ablation = FormalAblation(
        offline=args.offline,
        include_discovery_ground_truth=args.include_discovery_ground_truth,
    )
    results = ablation.run()

    print_summary(results)
    save_results(results, args.output)

    if args.publish:
        save_latex(results)

    print(f"\nDone. Results written to {args.output}")


if __name__ == "__main__":
    main()
