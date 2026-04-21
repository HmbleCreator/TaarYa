"""Comprehensive evaluation script for TaarYa research metrics."""

import json
import time
import logging
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def evaluate_spatial_retrieval() -> Dict[str, Any]:
    """Test cone search performance."""
    from src.retrieval.spatial_search import SpatialSearch

    spatial = SpatialSearch()
    queries = [
        {"name": "Pleiades", "ra": 56.75, "dec": 24.12, "radius": 2.0, "min_stars": 50},
        {"name": "Hyades", "ra": 66.75, "dec": 15.87, "radius": 5.0, "min_stars": 100},
        {"name": "Orion OB1", "ra": 83.82, "dec": -5.39, "radius": 1.0, "min_stars": 30},
    ]

    results = []
    for q in queries:
        start = time.time()
        stars = spatial.cone_search(q["ra"], q["dec"], q["radius"], limit=100, include_discovery=True)
        latency = time.time() - start

        scored_stars = [s for s in stars if s.get("discovery_score", 0) > 0]
        results.append({
            "query": q["name"],
            "stars_found": len(stars),
            "anomalous_stars": len(scored_stars),
            "top_discovery_score": stars[0].get("discovery_score", 0) if stars else 0,
            "latency_s": round(latency, 4),
            "precision": 1.0 if len(stars) >= q["min_stars"] else len(stars) / q["min_stars"]
        })

    return {"spatial": results}


def evaluate_discovery_scoring() -> Dict[str, Any]:
    """Test discovery scoring distribution."""
    from src.retrieval.spatial_search import SpatialSearch

    spatial = SpatialSearch()
    stars = spatial.cone_search(66.75, 15.87, 5.0, limit=200, include_discovery=True)

    scores = [s.get("discovery_score", 0) for s in stars]
    non_zero = [s for s in scores if s > 0]

    return {
        "discovery": {
            "total_stars": len(stars),
            "anomalous_count": len(non_zero),
            "max_score": max(scores) if scores else 0,
            "mean_score": sum(scores) / len(scores) if scores else 0,
            "anomaly_rate": len(non_zero) / len(stars) if stars else 0
        }
    }


def evaluate_graph_connectivity() -> Dict[str, Any]:
    """Test graph query performance."""
    from src.database import neo4j_conn
    from src.retrieval.graph_search import GraphSearch

    neo4j_conn.connect()
    graph = GraphSearch()
    start = time.time()

    stats = graph.get_graph_stats()

    hyades_members = graph.find_cluster_members("Hyades", limit=10)
    latency = time.time() - start

    return {
        "graph": {
            "nodes": stats,
            "hyades_sample_members": len(hyades_members),
            "query_latency_s": round(latency, 4)
        }
    }


def evaluate_knowledge_graph_links() -> Dict[str, Any]:
    """Test cross-catalog linking quality."""
    from src.database import neo4j_conn
    from src.retrieval.graph_search import GraphSearch

    neo4j_conn.connect()
    graph = GraphSearch()

    cluster_queries = ["Hyades", "Pleiades", "Orion OB1"]
    results = []

    for cluster in cluster_queries:
        members = graph.find_cluster_members(cluster, limit=100)
        papers_covering = graph.find_papers_about_topic(cluster, limit=10)
        results.append({
            "cluster": cluster,
            "member_count": len(members),
            "covering_papers": len(papers_covering)
        })

    return {"knowledge_graph_links": results}


def run_full_evaluation() -> Dict[str, Any]:
    """Run complete system evaluation."""
    logger.info("=" * 60)
    logger.info("TAARYA RESEARCH EVALUATION")
    logger.info("=" * 60)

    spatial = evaluate_spatial_retrieval()
    discovery = evaluate_discovery_scoring()
    graph = evaluate_graph_connectivity()
    links = evaluate_knowledge_graph_links()

    all_results = {
        "spatial_retrieval": spatial["spatial"],
        "discovery_analysis": discovery["discovery"],
        "graph_metrics": graph["graph"],
        "cross_catalog_links": links["knowledge_graph_links"]
    }

    print("\n" + "=" * 70)
    print("                     TAARYA RESEARCH EVALUATION REPORT")
    print("=" * 70)

    print("\n[SPATIAL RETRIEVAL]")
    print(f"{'Query':<15} | {'Stars':<6} | {'Anomalous':<10} | {'Top Score':<12} | {'Latency':<10} | {'Precision':<10}")
    print("-" * 75)
    for r in all_results["spatial_retrieval"]:
        print(f"{r['query']:<15} | {r['stars_found']:<6} | {r['anomalous_stars']:<10} | {r['top_discovery_score']:<12.1f} | {r['latency_s']:<10.4f}s | {r['precision']:<10.3f}")

    print("\n[DISCOVERY SCORING]")
    d = all_results["discovery_analysis"]
    print(f"  Total stars analyzed: {d['total_stars']}")
    print(f"  Anomalous candidates: {d['anomalous_count']} ({d['anomaly_rate']*100:.1f}%)")
    print(f"  Max discovery score:  {d['max_score']:.1f}")
    print(f"  Mean discovery score:  {d['mean_score']:.2f}")

    print("\n[GRAPH METRICS]")
    g = all_results["graph_metrics"]
    print(f"  Star nodes: {g['nodes'].get('stars', 'N/A')}")
    print(f"  Paper nodes: {g['nodes'].get('papers', 'N/A')}")
    print(f"  Cluster nodes: {g['nodes'].get('clusters', 'N/A')}")
    print(f"  Relationships: {g['nodes'].get('relationships', 'N/A')}")
    print(f"  Query latency: {g['query_latency_s']:.4f}s")

    print("\n[CROSS-CATALOG LINKS]")
    print(f"{'Cluster':<15} | {'Members':<10} | {'Covering Papers':<20}")
    print("-" * 50)
    for link in all_results["cross_catalog_links"]:
        print(f"{link['cluster']:<15} | {link['member_count']:<10} | {link['covering_papers']:<20}")

    print("\n" + "=" * 70)
    print("                      EVALUATION COMPLETE")
    print("=" * 70)

    return all_results


if __name__ == "__main__":
    results = run_full_evaluation()

    with open("eval/results.json", "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Results saved to eval/results.json")
