"""Comprehensive evaluation with 35 expert-curated astronomical queries."""

import json
import math
import time
import logging
import statistics
from datetime import datetime
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TaarYaBenchmark:
    def __init__(self):
        self.results = []
        self.spatial = None
        self.graph = None
        self.vector = None
        self.stats = {
            "spatial": {"total": 0, "passed": 0, "failed": 0},
            "semantic": {"total": 0, "passed": 0, "failed": 0},
            "discovery": {"total": 0, "passed": 0, "failed": 0},
            "graph": {"total": 0, "passed": 0, "failed": 0},
            "hybrid": {"total": 0, "passed": 0, "failed": 0},
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
    def _semantic_topic(params: Dict[str, Any]) -> str:
        """Normalize benchmark semantic query params to a single topic string."""
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
            stars = self.spatial.cone_search(
                ra=item["params"]["ra"],
                dec=item["params"]["dec"],
                radius=item["params"]["radius_deg"],
                limit=100,
                include_discovery=True
            )
            latency = time.time() - start
            count = len(stars)
            expected = item["expected_min_results"]

            if count >= expected:
                score = 1.0
                status = "PASS"
                self.stats["spatial"]["passed"] += 1
            else:
                score = count / expected if expected > 0 else 0
                status = "FAIL"
                self.stats["spatial"]["failed"] += 1

            self.stats["spatial"]["total"] += 1

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
                "query": item["query"],
                "category": item["category"],
                "difficulty": item["difficulty"]
            }
        except Exception as e:
            self.stats["spatial"]["total"] += 1
            self.stats["spatial"]["failed"] += 1
            return {
                "id": item["id"],
                "status": "ERROR",
                "error": str(e),
                "query": item["query"]
            }

    def _evaluate_semantic(self, item: Dict) -> Dict[str, Any]:
        self._init_backends()
        start = time.time()
        try:
            if self.vector is None:
                return {
                    "id": item["id"],
                    "status": "SKIP",
                    "reason": "Vector backend unavailable",
                    "query": item["query"]
                }

            results = self.vector.search_similar(
                self._semantic_topic(item["params"]),
                limit=item["params"].get("limit", 10)
            )
            latency = time.time() - start
            count = len(results)
            expected = item["expected_min_results"]

            if count >= expected:
                score = 1.0
                status = "PASS"
                self.stats["semantic"]["passed"] += 1
            else:
                score = count / expected if expected > 0 else 0
                status = "FAIL"
                self.stats["semantic"]["failed"] += 1

            self.stats["semantic"]["total"] += 1

            return {
                "id": item["id"],
                "status": status,
                "papers_found": count,
                "expected": expected,
                "score": round(score, 3),
                "latency_ms": round(latency * 1000, 2),
                "query": item["query"],
                "category": item["category"]
            }
        except Exception as e:
            self.stats["semantic"]["total"] += 1
            self.stats["semantic"]["failed"] += 1
            return {
                "id": item["id"],
                "status": "ERROR",
                "error": str(e),
                "query": item["query"]
            }

    def _evaluate_discovery(self, item: Dict) -> Dict[str, Any]:
        self._init_backends()
        start = time.time()
        try:
            params = item["params"]
            if "ra" in params and "dec" in params:
                stars = self.spatial.cone_search(
                    ra=params["ra"],
                    dec=params["dec"],
                    radius=params.get("radius_deg", 1.0),
                    limit=200,
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
                if "min_ruwe" in params and (ruwe is None or ruwe < params["min_ruwe"]):
                    continue
                bp_rp = self._bp_rp(s)
                if "max_bp_rp" in params:
                    if bp_rp is None or bp_rp >= params["max_bp_rp"]:
                        continue
                if "min_bp_rp" in params:
                    if bp_rp is None or bp_rp < params["min_bp_rp"]:
                        continue
                if "min_proper_motion" in params:
                    pm = self._proper_motion_total(s)
                    if pm < params["min_proper_motion"]:
                        continue
                distance_pc = self._distance_pc(s)
                if "max_distance_pc" in params:
                    if distance_pc is None or distance_pc > params["max_distance_pc"]:
                        continue
                if "min_distance_pc" in params:
                    if distance_pc is None or distance_pc < params["min_distance_pc"]:
                        continue
                phot_g = s.get("phot_g_mean_mag")
                if "max_g_mag" in params:
                    if phot_g is None or phot_g > params["max_g_mag"]:
                        continue
                if "min_g_mag" in params:
                    if phot_g is None or phot_g < params["min_g_mag"]:
                        continue
                filtered.append(s)

            latency = time.time() - start
            count = len(filtered)
            expected = item["expected_min_results"]

            if count >= expected:
                score = 1.0
                status = "PASS"
                self.stats["discovery"]["passed"] += 1
            else:
                score = 0.5 if count > 0 else 0
                status = "PARTIAL" if count > 0 else "FAIL"
                if status == "FAIL":
                    self.stats["discovery"]["failed"] += 1
                else:
                    self.stats["discovery"]["passed"] += 1

            self.stats["discovery"]["total"] += 1

            return {
                "id": item["id"],
                "status": status,
                "candidates_found": count,
                "expected": expected,
                "score": round(score, 3),
                "latency_ms": round(latency * 1000, 2),
                "query": item["query"],
                "category": item["category"],
                "difficulty": item["difficulty"]
            }
        except Exception as e:
            self.stats["discovery"]["total"] += 1
            self.stats["discovery"]["failed"] += 1
            return {
                "id": item["id"],
                "status": "ERROR",
                "error": str(e),
                "query": item["query"]
            }

    def _evaluate_graph(self, item: Dict) -> Dict[str, Any]:
        self._init_backends()
        start = time.time()
        try:
            if self.graph is None:
                return {
                    "id": item["id"],
                    "status": "SKIP",
                    "reason": "Graph backend unavailable",
                    "query": item["query"]
                }

            cluster_name = item["params"].get("cluster", item["query"].split()[-1])
            members = self.graph.find_cluster_members(cluster_name, limit=50)
            latency = time.time() - start
            count = len(members)
            expected = item["expected_min_results"]

            if count >= expected:
                score = 1.0
                status = "PASS"
                self.stats["graph"]["passed"] += 1
            else:
                score = count / expected if expected > 0 else 0
                status = "FAIL"
                self.stats["graph"]["failed"] += 1

            self.stats["graph"]["total"] += 1

            return {
                "id": item["id"],
                "status": status,
                "members_found": count,
                "expected": expected,
                "score": round(score, 3),
                "latency_ms": round(latency * 1000, 2),
                "query": item["query"],
                "category": item["category"]
            }
        except Exception as e:
            self.stats["graph"]["total"] += 1
            self.stats["graph"]["failed"] += 1
            return {
                "id": item["id"],
                "status": "ERROR",
                "error": str(e),
                "query": item["query"]
            }

    def _evaluate_hybrid(self, item: Dict) -> Dict[str, Any]:
        self._init_backends()
        start = time.time()
        try:
            spatial_result = self.spatial.cone_search(
                ra=item["params"]["ra"],
                dec=item["params"]["dec"],
                radius=item["params"]["radius_deg"],
                limit=50,
                include_discovery=True
            )

            papers_result = []
            if self.graph:
                papers_result = self.graph.find_papers_about_topic(
                    item["params"]["topic"],
                    limit=10
                )

            latency = time.time() - start
            stars_count = len(spatial_result)
            papers_count = len(papers_result)

            combined_score = 0.5 if stars_count > 0 else 0
            combined_score += 0.5 if papers_count > 0 else 0

            expected = item["expected_min_results"]
            if stars_count >= expected:
                combined_score = max(combined_score, 1.0)

            status = "PASS" if combined_score >= 0.8 else "PARTIAL" if combined_score > 0 else "FAIL"
            self.stats["hybrid"]["total"] += 1
            if status == "PASS":
                self.stats["hybrid"]["passed"] += 1
            else:
                self.stats["hybrid"]["failed"] += 1

            return {
                "id": item["id"],
                "status": status,
                "stars_found": stars_count,
                "papers_found": papers_count,
                "score": round(combined_score, 3),
                "latency_ms": round(latency * 1000, 2),
                "query": item["query"],
                "category": item["category"]
            }
        except Exception as e:
            self.stats["hybrid"]["total"] += 1
            self.stats["hybrid"]["failed"] += 1
            return {
                "id": item["id"],
                "status": "ERROR",
                "error": str(e),
                "query": item["query"]
            }

    def run_benchmark(self, queries: List[Dict]) -> List[Dict[str, Any]]:
        logger.info(f"Starting benchmark with {len(queries)} queries...")

        for i, item in enumerate(queries):
            qtype = item["type"]
            logger.info(f"[{i+1}/{len(queries)}] Running {item['id']} ({qtype}): {item['query'][:50]}...")

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
                result = {"id": item["id"], "status": "UNKNOWN_TYPE", "query": item["query"]}

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
        print(f"{'Type':<12} | {'Total':<8} | {'Passed':<8} | {'Failed':<8} | {'Pass Rate':<12}")
        print("-" * 55)
        for qtype, stat in self.stats.items():
            total = stat["total"]
            passed = stat["passed"]
            failed = stat["failed"]
            rate = (passed / total * 100) if total > 0 else 0
            print(f"{qtype:<12} | {total:<8} | {passed:<8} | {failed:<8} | {rate:<12.1f}%")

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
