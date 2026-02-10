"""Hybrid search and system API routes."""
from fastapi import APIRouter, Query
from typing import Optional

from src.retrieval.hybrid_search import HybridSearch

router = APIRouter(prefix="/search", tags=["Hybrid Search"])
hybrid = HybridSearch()


@router.get("/hybrid")
async def hybrid_search(
    q: Optional[str] = Query(None, description="Natural language query"),
    ra: Optional[float] = Query(None, ge=0, le=360, description="Right Ascension"),
    dec: Optional[float] = Query(None, ge=-90, le=90, description="Declination"),
    radius: Optional[float] = Query(None, gt=0, le=10, description="Radius in degrees"),
    source_id: Optional[str] = Query(None, description="Star source ID"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Intelligent multi-backend search.
    
    Automatically routes to the right backend(s) based on parameters:
    - ra/dec/radius → Q3C cone search
    - q → semantic vector search
    - source_id → star lookup + graph traversal
    - Multiple params → combined results from all applicable backends
    """
    results = hybrid.multi_search(
        query_text=q,
        ra=ra, dec=dec, radius_deg=radius,
        source_id=source_id,
        limit=limit
    )
    return results


@router.get("/cone-with-context")
async def cone_search_with_context(
    ra: float = Query(..., ge=0, le=360),
    dec: float = Query(..., ge=-90, le=90),
    radius: float = Query(..., gt=0, le=10),
    limit: int = Query(50, ge=1, le=500),
):
    """Cone search enriched with knowledge graph context (related papers)."""
    return hybrid.cone_search_with_context(
        ra=ra, dec=dec, radius_deg=radius, limit=limit
    )


# System stats endpoint
stats_router = APIRouter(tags=["System"])

@stats_router.get("/stats")
async def system_stats():
    """Get statistics from all backends (PostgreSQL, Qdrant, Neo4j)."""
    return hybrid.get_system_stats()
