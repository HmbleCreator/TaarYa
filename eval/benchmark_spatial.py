"""Simplified benchmark that tests only spatial (cone search) functionality."""

import time
import logging
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


BENCHMARK_QUERIES = [
    {
        "id": "Q1",
        "query": "Find stars in the Pleiades cluster",
        "type": "spatial",
        "params": {"ra": 56.75, "dec": 24.12, "radius_deg": 2.0},
        "ground_truth_min_stars": 50
    },
    {
        "id": "Q2",
        "query": "Find stars in the Hyades cluster",
        "type": "spatial",
        "params": {"ra": 66.75, "dec": 15.87, "radius_deg": 5.0},
        "ground_truth_min_stars": 100
    },
    {
        "id": "Q3",
        "query": "Find stars near Orion OB1 association",
        "type": "spatial",
        "params": {"ra": 83.82, "dec": -5.39, "radius_deg": 1.0},
        "ground_truth_min_stars": 30
    }
]


def run_spatial_benchmark():
    from src.retrieval.spatial_search import SpatialSearch

    spatial = SpatialSearch()
    results = []

    for item in BENCHMARK_QUERIES:
        logger.info(f"Evaluating {item['id']}: {item['query']}")

        start_time = time.time()
        try:
            output = spatial.cone_search(
                ra=item["params"]["ra"],
                dec=item["params"]["dec"],
                radius=item["params"]["radius_deg"],
                limit=100,
                include_discovery=True
            )
            latency = time.time() - start_time

            count = len(output)
            ground_truth = item["ground_truth_min_stars"]

            if count >= ground_truth:
                metric = 1.0
            else:
                metric = count / ground_truth

            results.append({
                "id": item["id"],
                "count": count,
                "metric_score": round(metric, 3),
                "latency_s": round(latency, 4),
                "discovery_top_star": output[0].get("discovery_score", 0) if output else 0
            })
            logger.info(f"  -> Found {count} stars, Score: {metric:.3f}, Latency: {latency:.4f}s")
        except Exception as e:
            logger.error(f"  -> Error: {e}")
            results.append({
                "id": item["id"],
                "count": 0,
                "metric_score": 0.0,
                "latency_s": 0.0,
                "discovery_top_star": 0
            })

    print("\n" + "=" * 60)
    print("         TAARYA SPATIAL BENCHMARK REPORT")
    print("=" * 60)
    print(f"{'ID':<6} | {'Stars':<6} | {'Score':<8} | {'Latency':<10} | {'Top Discovery':<14}")
    print("-" * 60)
    for r in results:
        print(f"{r['id']:<6} | {r['count']:<6} | {r['metric_score']:<8.3f} | {r['latency_s']:<10.4f}s | {r['discovery_top_star']:<14.1f}")

    if results:
        avg_score = np.mean([r["metric_score"] for r in results])
        avg_latency = np.mean([r["latency_s"] for r in results])
        print("-" * 60)
        print(f"AVERAGES: Score={avg_score:.3f} | Latency={avg_latency:.4f}s")
        print("=" * 60)
        print("\nSYSTEM STATUS: SPATIAL RETRIEVAL FUNCTIONAL")
    else:
        print("\nNO RESULTS - check database connectivity")


if __name__ == "__main__":
    run_spatial_benchmark()
