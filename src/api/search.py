"""Hybrid search and system API routes."""
from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field
from typing import Optional

from src.retrieval.hybrid_search import HybridSearch

router = APIRouter(prefix="/search", tags=["Hybrid Search"])
hybrid = HybridSearch()


# ── Pydantic models for POST bodies ──────────────────────────────────

class HybridSearchRequest(BaseModel):
    """JSON body accepted by POST /api/search/hybrid."""
    q: Optional[str] = Field(None, description="Natural language query")
    query: Optional[str] = Field(None, description="Alias for q")
    ra: Optional[float] = Field(None, ge=0, le=360)
    dec: Optional[float] = Field(None, ge=-90, le=90)
    radius: Optional[float] = Field(None, gt=0, le=10)
    source_id: Optional[str] = None
    limit: int = Field(20, ge=1, le=100)


class ConeContextRequest(BaseModel):
    """JSON body accepted by POST /api/search/cone-with-context."""
    ra: float = Field(..., ge=0, le=360)
    dec: float = Field(..., ge=-90, le=90)
    radius: float = Field(..., gt=0, le=10)
    limit: int = Field(50, ge=1, le=500)


# ── Core search logic (shared by GET and POST) ───────────────────────

def _run_hybrid(
    q: Optional[str], query: Optional[str],
    ra: Optional[float], dec: Optional[float],
    radius: Optional[float], source_id: Optional[str],
    limit: int,
):
    return hybrid.multi_search(
        query_text=q or query,
        ra=ra, dec=dec, radius_deg=radius,
        source_id=source_id,
        limit=limit,
    )


# ── GET endpoints (original) ─────────────────────────────────────────

@router.get("/hybrid")
async def hybrid_search_get(
    q: Optional[str] = Query(None, description="Natural language query"),
    query: Optional[str] = Query(None, description="Natural language query alias"),
    ra: Optional[float] = Query(None, ge=0, le=360, description="Right Ascension"),
    dec: Optional[float] = Query(None, ge=-90, le=90, description="Declination"),
    radius: Optional[float] = Query(None, gt=0, le=10, description="Radius in degrees"),
    source_id: Optional[str] = Query(None, description="Star source ID"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Intelligent multi-backend search (GET).

    Automatically routes to the right backend(s) based on parameters:
    - ra/dec/radius -> Q3C cone search
    - q -> semantic vector search
    - source_id -> star lookup + graph traversal
    - Multiple params -> combined results from all applicable backends
    """
    return _run_hybrid(q, query, ra, dec, radius, source_id, limit)


@router.get("/cone-with-context")
async def cone_search_with_context_get(
    ra: float = Query(..., ge=0, le=360),
    dec: float = Query(..., ge=-90, le=90),
    radius: float = Query(..., gt=0, le=10),
    limit: int = Query(50, ge=1, le=500),
):
    """Cone search enriched with knowledge graph context (related papers)."""
    return hybrid.cone_search_with_context(
        ra=ra, dec=dec, radius_deg=radius, limit=limit
    )


# ── POST endpoints (for external tools / notebooks) ──────────────────

@router.post("/hybrid")
async def hybrid_search_post(body: HybridSearchRequest):
    """
    Intelligent multi-backend search (POST with JSON body).

    Accepts the same parameters as GET /hybrid but as a JSON payload,
    which is more natural for Python requests, Jupyter notebooks, and
    batch-processing scripts.
    """
    return _run_hybrid(
        body.q, body.query, body.ra, body.dec,
        body.radius, body.source_id, body.limit,
    )


@router.post("/cone-with-context")
async def cone_search_with_context_post(body: ConeContextRequest):
    """Cone search with graph context (POST with JSON body)."""
    return hybrid.cone_search_with_context(
        ra=body.ra, dec=body.dec, radius_deg=body.radius, limit=body.limit,
    )


# System stats endpoint
stats_router = APIRouter(tags=["System"])

@stats_router.get("/stats")
async def system_stats():
    """Get statistics from all backends (PostgreSQL, Qdrant, Neo4j)."""
    return hybrid.get_system_stats()
