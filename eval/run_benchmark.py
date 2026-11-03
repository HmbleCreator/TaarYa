"""Comprehensive evaluation with 35 expert-curated astronomical queries."""

import json
import math
import os
import sys
import time
import logging
import statistics
from datetime import datetime
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TaarYaBenchmark:
    def __init__(self):
        self.results = []
        self.spatial = None
        self.graph = None
        self.vector = None
        self.stats = {
            "spatial": {"total": 0, "passed": 0, "partial": 0, "failed": 0},
            "semantic": {"total": 0, "passed": 0, "partial": 0, "failed": 0},
            "discovery": {"total": 0, "passed": 0, "partial": 0, "failed": 0},
            "graph": {"total": 0, "passed": 0, "partial": 0, "failed": 0},
            "hybrid": {"total": 0, "passed": 0, "partial": 0, "failed": 0},
        }

    def _init_backends(self):
        if self.spatial is None:
            from src.retrieval.spatial_search import SpatialSearch
            self.spatial = SpatialSearch()
            logger.info("Spatial backend initialized")
        if self.graph is None:
            try:
                from src.database import neo4j_conn
                from src.retrieval.graph_search import GraphSearch
                neo4j_conn.connect()
                self.graph = GraphSearch()
                logger.info("Graph backend initialized")
            except Exception as e:
                logger.warning(f"Graph backend unavailable: {e}")
        if self.vector is None:
            try:
                from src.retrieval.vector_search import VectorSearch
                self.vector = VectorSearch()
                self.vector.ensure_collection("papers")
                logger.info("Vector backend initialized - warming up embedding model...")
                self.vector.embed_text("warmup query")
                logger.info("Embedding model ready")
            except Exception as e:
                logger.warning(f"Vector backend unavailable: {e}")

    @staticmethod
    def _query_type(item: Dict[str, Any]) -> str:
        """Support both legacy benchmark schema and v2 benchmark_queries.json."""
        return item.get("type") or item.get("family") or "unknown"

    @staticmethod
    def _query_text(item: Dict[str, Any]) -> str:
        return item.get("query") or item.get("prompt") or item.get("task") or item.get("id", "")

    @staticmethod
    def _category(item: Dict[str, Any]) -> str:
        return item.get("category") or item.get("task") or item.get("family") or "unknown"

    @staticmethod
    def _difficulty(item: Dict[str, Any]) -> str:
        return item.get("difficulty") or "medium"

    @staticmethod
    def _ground_truth(item: Dict[str, Any]) -> Dict[str, Any]:
        gt = item.get("ground_truth")
        return gt if isinstance(gt, dict) else {}

    def _expected_min(self, item: Dict[str, Any]) -> int:
        gt = self._ground_truth(item)
        return int(item.get("expected_min_results", gt.get("expected_count_min", 0)) or 0)

    def _expected_max(self, item: Dict[str, Any]) -> Optional[int]:
        gt = self._ground_truth(item)
        value = item.get("expected_max_results", gt.get("expected_count_max"))
        return int(value) if isinstance(value, (int, float)) else None

    @staticmethod
    def _score_count(count: int, expected_min: int, expected_max: Optional[int] = None) -> tuple:
        if expected_min <= 0 and (expected_max is None or count <= expected_max):
            return 1.0, "PASS"
        if count < expected_min:
            score = count / expected_min if expected_min > 0 else 0.0
            return score, "FAIL" if count == 0 else "PARTIAL"
        if expected_max is not None and count > expected_max:
            score = expected_max / count if count else 0.0
            return max(0.5, score), "PARTIAL"
        return 1.0, "PASS"

    def _record_status(self, family: str, status: str) -> None:
        """Update benchmark counters consistently for PASS/PARTIAL/FAIL/SKIP/ERROR."""
        self.stats[family]["total"] += 1
        if status == "PASS":
            self.stats[family]["passed"] += 1
        elif status == "PARTIAL":
            self.stats[family]["partial"] += 1
        else:
            self.stats[family]["failed"] += 1

    @staticmethod
    def _semantic_topic(params: Dict[str, Any]) -> str:
        """Normalize benchmark semantic query params to a single topic string."""
        query = params.get("query")
        if isinstance(query, str) and query.strip():
            return query.strip()

        topic = params.get("topic")
        if isinstance(topic, str) and topic.strip():
            return topic.strip()

        parts = []
        for key in ("topic1", "topic2"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())

        if parts:
            return " vs ".join(parts)

        raise KeyError("topic")

    @staticmethod
    def _bp_rp(star: Dict[str, Any]) -> Any:
        """Return BP-RP color if available."""
        if star.get("bp_rp") is not None:
            return star.get("bp_rp")
        bp = star.get("phot_bp_mean_mag")
        rp = star.get("phot_rp_mean_mag")
        if bp is None or rp is None:
            return None
        return bp - rp

    @staticmethod
    def _proper_motion_total(star: Dict[str, Any]) -> float:
        """Return total proper motion using any available field layout."""
        for key in ("total_proper_motion", "pm_total", "pm"):
            value = star.get(key)
            if isinstance(value, (int, float)):
                return float(value)

        pmra = star.get("pmra")
        pmdec = star.get("pmdec")
        if isinstance(pmra, (int, float)) and isinstance(pmdec, (int, float)):
            return math.sqrt(pmra ** 2 + pmdec ** 2)
        return 0.0

    @staticmethod
    def _distance_pc(star: Dict[str, Any]) -> Any:
        """Return distance in parsec if available or computable from parallax."""
        value = star.get("distance_pc")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)

        parallax = star.get("parallax")
        if isinstance(parallax, (int, float)) and parallax > 0:
            return 1000.0 / parallax
        return None

    def _evaluate_spatial(self, item: Dict) -> Dict[str, Any]:
        self._init_backends()
        start = time.time()
        try:
            params = item["params"]
            limit = int(params.get("limit", 100))
            stars = self.spatial.cone_search(
                ra=params["ra"],
                dec=params["dec"],
                radius=params["radius_deg"],
                limit=limit,
                include_discovery=True
            )
            latency = time.time() - start
            count = len(stars)
            expected = min(self._expected_min(item), limit)
            expected_max = self._expected_max(item)
            score, status = self._score_count(count, expected, expected_max)
            self._record_status("spatial", status)

            top_discovery = stars[0].get("discovery_score", 0) if stars else 0
            anomalous = sum(1 for s in stars if s.get("discovery_score", 0) > 0)

            return {
                "id": item["id"],
                "status": status,
                "stars_found": count,
                "expected": expected,
                "score": round(score, 3),
                "latency_ms": round(latency * 1000, 2),
                "top_discovery": top_discovery,
                "anomalous_count": anomalous,
                "query": self._query_text(item),
                "category": self._category(item),
                "difficulty": self._difficulty(item)
            }
        except Exception as e:
            self._record_status("spatial", "ERROR")
            return {
                "id": item["id"],
                "status": "ERROR",
                "error": str(e),
                "query": self._query_text(item)
            }

    def _evaluate_semantic(self, item: Dict) -> Dict[str, Any]:
        self._init_backends()
        start = time.time()
        try:
            if self.vector is None:
                self._record_status("semantic", "SKIP")
                return {
                    "id": item["id"],
                    "status": "SKIP",
                    "reason": "Vector backend unavailable",
                    "query": self._query_text(item)
                }

            params = item["params"]
            results = self.vector.search_similar(
                self._semantic_topic(params),
                limit=params.get("limit", 10)
            )
            latency = time.time() - start
            count = len(results)
            expected = self._expected_min(item)
            score, status = self._score_count(count, expected)
            top_score = float(results[0].get("score", 0.0)) if results else 0.0
            mean_score = (
                sum(float(r.get("score", 0.0)) for r in results) / count
                if count
                else 0.0
            )
            self._record_status("semantic", status)

            return {
                "id": item["id"],
                "status": status,
                "papers_found": count,
                "expected": expected,
                "score": round(score, 3),
                "top_similarity": round(top_score, 4),
                "mean_similarity": round(mean_score, 4),
                "latency_ms": round(latency * 1000, 2),
                "query": self._query_text(item),
                "category": self._category(item)
            }
        except Exception as e:
            self._record_status("semantic", "ERROR")
            return {
                "id": item["id"],
                "status": "ERROR",
                "error": str(e),
                "query": self._query_text(item)
            }

    def _evaluate_discovery(self, item: Dict) -> Dict[str, Any]:
        self._init_backends()
        start = time.time()
        try:
            params = item["params"]
            ruwe_min = params.get("min_ruwe", params.get("ruwe_min"))
            bp_rp_max = params.get("max_bp_rp", params.get("bp_rp_max"))
            bp_rp_min = params.get("min_bp_rp", params.get("bp_rp_min"))
            proper_motion_min = params.get(
                "min_proper_motion",
                params.get("motion_min", params.get("motion_threshold")),
            )
            distance_max = params.get("max_distance_pc")
            distance_min = params.get("min_distance_pc")
            g_max = params.get("max_g_mag", params.get("g_max"))
            g_min = params.get("min_g_mag", params.get("g_min"))
            parallax_min = params.get("parallax_min")
            parallax_max = params.get("parallax_max", params.get("parallax_max_mas"))
            abs_mag_max = params.get("abs_mag_max")
            abs_mag_min = params.get("abs_mag_min")
            limit = int(params.get("limit", 200))
            if "ra" in params and "dec" in params:
                stars = self.spatial.cone_search(
                    ra=params["ra"],
                    dec=params["dec"],
                    radius=params.get("radius_deg", 1.0),
                    limit=limit,
                    include_discovery=True
                )
            else:
                stars = self.spatial.cone_search(
                    ra=0, dec=0, radius=180,
                    limit=500,
                    include_discovery=True
                )

            filtered = []
            for s in stars:
                ruwe = s.get("ruwe")
                if ruwe_min is not None and (ruwe is None or ruwe < ruwe_min):
                    continue
                bp_rp = self._bp_rp(s)
                if bp_rp_max is not None:
                    if bp_rp is None or bp_rp >= bp_rp_max:
                        continue
                if bp_rp_min is not None:
                    if bp_rp is None or bp_rp < bp_rp_min:
                        continue
                if proper_motion_min is not None:
                    pm = self._proper_motion_total(s)
                    if pm < proper_motion_min:
                        continue
                distance_pc = self._distance_pc(s)
                if distance_max is not None:
                    if distance_pc is None or distance_pc > distance_max:
                        continue
                if distance_min is not None:
                    if distance_pc is None or distance_pc < distance_min:
                        continue
                phot_g = s.get("phot_g_mean_mag")
                if g_max is not None:
                    if phot_g is None or phot_g > g_max:
                        continue
                if g_min is not None:
                    if phot_g is None or phot_g < g_min:
                        continue
                parallax = s.get("parallax")
                if parallax_min is not None and parallax_max is not None and parallax_min > parallax_max:
                    if parallax is None or not (parallax >= parallax_min or parallax <= parallax_max):
                        continue
                else:
                    if parallax_min is not None and (parallax is None or parallax < parallax_min):
                        continue
                    if parallax_max is not None and (parallax is None or parallax > parallax_max):
                        continue
                if (abs_mag_min is not None or abs_mag_max is not None) and (
                    phot_g is None or parallax is None or parallax <= 0
                ):
                    continue
                if phot_g is not None and parallax is not None and parallax > 0:
                    abs_mag = phot_g + 5 * math.log10(parallax / 1000.0) + 5
                    if abs_mag_max is not None and abs_mag > abs_mag_max:
                        continue
                    if abs_mag_min is not None and abs_mag < abs_mag_min:
                        continue
                filtered.append(s)

            latency = time.time() - start
            count = len(filtered)
            expected = min(self._expected_min(item), limit)
            score, status = self._score_count(count, expected, self._expected_max(item))
            self._record_status("discovery", status)

            return {
                "id": item["id"],
                "status": status,
                "candidates_found": count,
                "expected": expected,
                "score": round(score, 3),
                "latency_ms": round(latency * 1000, 2),
                "query": self._query_text(item),
                "category": self._category(item),
                "difficulty": self._difficulty(item)
            }
        except Exception as e:
            self._record_status("discovery", "ERROR")
            return {
                "id": item["id"],
                "status": "ERROR",
                "error": str(e),
                "query": self._query_text(item)
            }

    def _evaluate_graph(self, item: Dict) -> Dict[str, Any]:
        self._init_backends()
        start = time.time()
        try:
            if self.graph is None:
                self._record_status("graph", "SKIP")
                return {
                    "id": item["id"],
                    "status": "SKIP",
                    "reason": "Graph backend unavailable",
                    "query": self._query_text(item)
                }

            gt = self._ground_truth(item)
            cluster_name = item["params"].get("cluster", gt.get("cluster", self._query_text(item).split()[-1]))
            members = self.graph.find_cluster_members(cluster_name, limit=50)
            latency = time.time() - start
            count = len(members)
            expected = min(self._expected_min(item), 50)
            score, status = self._score_count(count, expected)
            self._record_status("graph", status)

            return {
                "id": item["id"],
                "status": status,
                "members_found": count,
                "expected": expected,
                "score": round(score, 3),
                "latency_ms": round(latency * 1000, 2),
                "query": self._query_text(item),
                "category": self._category(item)
            }
        except Exception as e:
            self._record_status("graph", "ERROR")
            return {
                "id": item["id"],
                "status": "ERROR",
                "error": str(e),
                "query": self._query_text(item)
            }

    def _evaluate_hybrid(self, item: Dict) -> Dict[str, Any]:
        self._init_backends()
        start = time.time()
        try:
            params = item["params"]
            gt = self._ground_truth(item)
            limit = int(params.get("limit", 20))
            spatial_result = self.spatial.cone_search(
                ra=params["ra"],
                dec=params["dec"],
                radius=params["radius_deg"],
                limit=limit,
                include_discovery=True
            )
            spatial_result.sort(key=lambda s: s.get("discovery_score", 0), reverse=True)

            papers_result = []
            topic = params.get("topic") or params.get("query") or gt.get("cluster") or self._query_text(item)
            if self.vector:
                papers_result = self.vector.search_similar(topic, limit=10)

            related_papers_count = 0
            if self.graph and spatial_result:
                source_ids = [str(s["source_id"]) for s in spatial_result[: min(limit, 25)]]
                papers_by_star = self.graph.find_papers_for_stars(
                    source_ids,
                    include_cluster_context=True,
                    limit_per_star=10,
                )
                related_paper_ids = {
                    paper.get("arxiv_id")
                    for papers in papers_by_star.values()
                    for paper in papers
                    if paper.get("arxiv_id")
                }
                related_papers_count = len(related_paper_ids)

            latency = time.time() - start
            stars_count = len(spatial_result)
            papers_count = len(papers_result)

            expected = min(self._expected_min(item), limit)
            star_score, star_status = self._score_count(stars_count, expected, self._expected_max(item))
            semantic_score = 1.0 if papers_count > 0 else 0.0
            graph_score = 1.0 if related_papers_count > 0 else 0.0
            combined_score = 0.6 * star_score + 0.25 * semantic_score + 0.15 * graph_score
            if star_status == "PASS" and papers_count > 0:
                status = "PASS"
            elif combined_score > 0:
                status = "PARTIAL"
            else:
                status = "FAIL"
            self._record_status("hybrid", status)

            return {
                "id": item["id"],
                "status": status,
                "stars_found": stars_count,
                "papers_found": papers_count,
                "related_papers_found": related_papers_count,
                "score": round(combined_score, 3),
                "latency_ms": round(latency * 1000, 2),
                "query": self._query_text(item),
                "category": self._category(item)
            }
        except Exception as e:
            self._record_status("hybrid", "ERROR")
            return {
                "id": item["id"],
                "status": "ERROR",
                "error": str(e),
                "query": self._query_text(item)
            }

    def run_benchmark(self, queries: List[Dict]) -> List[Dict[str, Any]]:
        logger.info(f"Starting benchmark with {len(queries)} queries...")

        for i, item in enumerate(queries):
            qtype = self._query_type(item)
            query_text = self._query_text(item)
            logger.info(f"[{i+1}/{len(queries)}] Running {item['id']} ({qtype}): {query_text[:50]}...")

            if qtype == "spatial":
                result = self._evaluate_spatial(item)
            elif qtype == "semantic":
                result = self._evaluate_semantic(item)
            elif qtype == "discovery":
                result = self._evaluate_discovery(item)
            elif qtype == "graph":
                result = self._evaluate_graph(item)
            elif qtype == "hybrid":
                result = self._evaluate_hybrid(item)
            else:
                result = {"id": item["id"], "status": "UNKNOWN_TYPE", "query": query_text}

            result["family"] = qtype
            self.results.append(result)
            status_str = f"[{result['status']}]"
            score = result.get('score', 'N/A')
            latency = result.get('latency_ms', 'N/A')
            found = result.get('stars_found', result.get('papers_found', result.get('candidates_found', 'N/A')))
            if result['status'] != 'ERROR' and result['status'] != 'SKIP':
                logger.info(f"  {status_str} Found={found}, Score={score}, Latency={latency}")
            else:
                logger.info(f"  {status_str} {result.get('error', result.get('reason', 'Unknown'))}")

        return self.results

    def print_report(self):
        print("\n" + "=" * 80)
        print("           TAARYA COMPREHENSIVE BENCHMARK REPORT")
        print("=" * 80)
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total Queries: {len(self.results)}")
        print("=" * 80)

        print("\n[BY QUERY TYPE]")
        print(f"{'Type':<12} | {'Total':<8} | {'Passed':<8} | {'Partial':<8} | {'Failed':<8} | {'Pass Rate':<12}")
        print("-" * 68)
        for qtype, stat in self.stats.items():
            total = stat["total"]
            passed = stat["passed"]
            partial = stat.get("partial", 0)
            failed = stat["failed"]
            rate = (passed / total * 100) if total > 0 else 0
            print(f"{qtype:<12} | {total:<8} | {passed:<8} | {partial:<8} | {failed:<8} | {rate:<12.1f}%")

        print("\n[BY DIFFICULTY]")
        difficulty_stats = {"easy": {"total": 0, "passed": 0}, "medium": {"total": 0, "passed": 0},
                            "hard": {"total": 0, "passed": 0}, "very_hard": {"total": 0, "passed": 0}}
        for r in self.results:
            diff = r.get("difficulty", "medium")
            difficulty_stats[diff]["total"] += 1
            if r["status"] == "PASS":
                difficulty_stats[diff]["passed"] += 1

        print(f"{'Difficulty':<12} | {'Total':<8} | {'Passed':<8} | {'Pass Rate':<12}")
        print("-" * 45)
        for diff, stat in difficulty_stats.items():
            total = stat["total"]
            passed = stat["passed"]
            rate = (passed / total * 100) if total > 0 else 0
            print(f"{diff:<12} | {total:<8} | {passed:<8} | {rate:<12.1f}%")

        print("\n[DETAILED RESULTS]")
        print(f"{'ID':<6} | {'Status':<8} | {'Score':<8} | {'Latency':<12} | {'Category':<20}")
        print("-" * 70)
        for r in self.results:
            status = r["status"]
            score = r.get("score", "N/A")
            if isinstance(score, float):
                score = f"{score:.3f}"
            latency = r.get("latency_ms", "N/A")
            if isinstance(latency, float):
                latency = f"{latency:.1f}ms"
            category = r.get("category", "unknown")[:20]
            print(f"{r['id']:<6} | {status:<8} | {score:<8} | {latency:<12} | {category:<20}")

        overall = self._compute_overall_stats()
        print("\n[SUMMARY STATISTICS]")
        print(f"  Overall Pass Rate:    {overall['pass_rate']:.1f}%")
        print(f"  Average Score:        {overall['avg_score']:.3f}")
        print(f"  Average Latency:      {overall['avg_latency']:.1f}ms")
        print(f"  Total Stars Found:    {overall['total_stars']}")
        print(f"  Total Papers Found:   {overall['total_papers']}")
        print(f"  Total Candidates:     {overall['total_candidates']}")
        print("=" * 80)

    def _compute_overall_stats(self) -> Dict[str, Any]:
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        total = len(self.results)
        scores = [r["score"] for r in self.results if isinstance(r.get("score"), (int, float))]
        latencies = [r["latency_ms"] for r in self.results if isinstance(r.get("latency_ms"), (int, float))]
        stars = sum(r.get("stars_found", 0) for r in self.results)
        papers = sum(r.get("papers_found", 0) for r in self.results)
        candidates = sum(r.get("candidates_found", 0) for r in self.results)

        return {
            "pass_rate": (passed / total * 100) if total > 0 else 0,
            "avg_score": sum(scores) / len(scores) if scores else 0,
            "avg_latency": sum(latencies) / len(latencies) if latencies else 0,
            "total_stars": stars,
            "total_papers": papers,
            "total_candidates": candidates
        }

    def save_results(self, path: str = "eval/benchmark_results.json"):
        data = {
            "timestamp": datetime.now().isoformat(),
            "stats": self.stats,
            "results": self.results,
            "summary": self._compute_overall_stats()
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Results saved to {path}")


def main():
    import sys
    import os

    benchmark = TaarYaBenchmark()

    queries_path = "eval/benchmark_queries.json"
    if os.path.exists(queries_path):
        with open(queries_path, "r") as f:
            data = json.load(f)
            queries = data["queries"]
        logger.info(f"Loaded {len(queries)} queries from {queries_path}")
    else:
        logger.error(f"Queries file not found: {queries_path}")
        sys.exit(1)

    results = benchmark.run_benchmark(queries)
    benchmark.print_report()
    benchmark.save_results()


if __name__ == "__main__":
    main()
