"""Health check utilities for all TaarYa backends."""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def check_postgres() -> Dict[str, Any]:
    """Check PostgreSQL connectivity and return stats."""
    try:
        from src.database import postgres_conn
        from sqlalchemy import text

        postgres_conn.connect()
        with postgres_conn.session() as session:
            star_count = session.execute(text("SELECT COUNT(*) FROM stars")).scalar()
            region_count = session.execute(text("SELECT COUNT(*) FROM regions")).scalar()

        return {
            "status": "healthy",
            "stars": int(star_count),
            "regions": int(region_count)
        }
    except Exception as e:
        logger.error(f"PostgreSQL health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


def check_neo4j() -> Dict[str, Any]:
    """Check Neo4j connectivity and return graph stats."""
    try:
        from src.database import neo4j_conn
        from src.retrieval.graph_search import GraphSearch

        neo4j_conn.connect()
        graph = GraphSearch()
        stats = graph.get_graph_stats()
        return {"status": "healthy", **stats}
    except Exception as e:
        logger.error(f"Neo4j health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


def check_qdrant() -> Dict[str, Any]:
    """Check Qdrant connectivity and return collection stats."""
    try:
        from src.database import qdrant_conn

        client = qdrant_conn.get_client()
        collections = client.get_collections()
        collection_names = [c.name for c in collections.collections]

        paper_count = 0
        if "papers" in collection_names:
            paper_count = client.get_collection("papers").points_count

        return {
            "status": "healthy",
            "collections": collection_names,
            "papers": paper_count
        }
    except Exception as e:
        logger.error(f"Qdrant health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


def check_all() -> Dict[str, Any]:
    """Run all health checks and return combined status."""
    postgres = check_postgres()
    neo4j = check_neo4j()
    qdrant = check_qdrant()

    all_healthy = (
        postgres.get("status") == "healthy" and
        neo4j.get("status") == "healthy" and
        qdrant.get("status") == "healthy"
    )

    return {
        "overall": "healthy" if all_healthy else "degraded",
        "postgres": postgres,
        "neo4j": neo4j,
        "qdrant": qdrant
    }


if __name__ == "__main__":
    import json
    print(json.dumps(check_all(), indent=2))
