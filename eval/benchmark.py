import json
import time
import logging
from typing import List, Dict, Any
import numpy as np

# Mocking parts of the system for evaluation if necessary, 
# but ideally we use the real classes
from src.retrieval.hybrid_search import HybridSearch
from src.retrieval.spatial_search import SpatialSearch
from src.retrieval.vector_search import VectorSearch
from src.database import neo4j_conn, postgres_conn, qdrant_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_connections():
    """Initialize all database connections."""
    logger.info("Initializing database connections...")
    try:
        postgres_conn.connect()
        qdrant_conn.connect()
        neo4j_conn.connect()
        logger.info("All connections established.")
    except Exception as e:
        logger.error(f"Connection initialization failed: {e}")

# --- Evaluation Dataset ---
# In a real research paper, these would be curated from domain experts.
BENCHMARK_QUERIES = [
    {
        "id": "Q1",
        "query": "Find stars in the Pleiades cluster",
        "type": "spatial",
        "params": {"ra": 56.75, "dec": 24.12, "radius_deg": 2.0},
        "ground_truth_min_stars": 100
    },
    {
        "id": "Q2",
        "query": "Search for papers about Gaia DR3 astrometry",
        "type": "semantic",
        "text": "Gaia DR3 stellar catalog astrometry",
        "ground_truth_keywords": ["Gaia", "DR3", "astrometry"]
    },
    {
        "id": "Q3",
        "query": "Are there any stars in the Hyades mentioned in research?",
        "type": "hybrid",
        "params": {"ra": 66.75, "dec": 15.87, "radius_deg": 5.0},
        "text": "Hyades cluster stars",
        "expected_link": "MEMBER_OF"
    }
]

class TaarYaEvaluator:
    def __init__(self):
        self.hybrid = HybridSearch()
        self.spatial = SpatialSearch()
        self.vector = VectorSearch()

    def run_benchmark(self):
        results = []
        for item in BENCHMARK_QUERIES:
            logger.info(f"Evaluating {item['id']}: {item['query']}")
            
            start_time = time.time()
            
            if item["type"] == "spatial":
                p = item["params"]
                output = self.spatial.cone_search(ra=p["ra"], dec=p["dec"], radius=p["radius_deg"])
                metric = self._eval_spatial(output, item)
            elif item["type"] == "semantic":
                output = self.vector.search_similar(item["text"])
                metric = self._eval_semantic(output, item)
            elif item["type"] == "hybrid":
                p = item["params"]
                output = self.hybrid.cone_search_with_context(ra=p["ra"], dec=p["dec"], radius_deg=p["radius_deg"])
                metric = self._eval_hybrid(output, item)
            
            latency = time.time() - start_time
            results.append({
                "id": item["id"],
                "metric_score": metric,
                "latency": latency
            })
            
        self._print_report(results)

    def _eval_spatial(self, output, ground_truth) -> float:
        count = len(output)
        if count >= ground_truth["ground_truth_min_stars"]:
            return 1.0
        return count / ground_truth["ground_truth_min_stars"]

    def _eval_semantic(self, output, ground_truth) -> float:
        if not output: return 0.0
        matches = 0
        for paper in output:
            title = paper["payload"].get("title", "").lower()
            if any(kw.lower() in title for kw in ground_truth["ground_truth_keywords"]):
                matches += 1
        return matches / len(output)

    def _eval_hybrid(self, output, ground_truth) -> float:
        # Check if we have both stars AND related papers
        star_score = self._eval_spatial(output.get("stars", []), {"ground_truth_min_stars": 10})
        paper_score = 1.0 if output.get("related_papers") else 0.0
        return (star_score + paper_score) / 2.0

    def _print_report(self, results):
        print("\n" + "="*40)
        print(" TAARYA RESEARCH EVALUATION REPORT ")
        print("="*40)
        print(f"{'ID':<5} | {'Score':<8} | {'Latency (s)':<12}")
        print("-" * 40)
        for r in results:
            print(f"{r['id']:<5} | {r['metric_score']:<8.2f} | {r['latency']:<12.4f}")
        
        avg_score = np.mean([r["metric_score"] for r in results])
        print("-" * 40)
        print(f"OVERALL SYSTEM SCORE: {avg_score:.2f}")
        print("="*40)

if __name__ == "__main__":
    init_connections()
    evaluator = TaarYaEvaluator()
    evaluator.run_benchmark()
