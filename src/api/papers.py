"""Paper search API routes."""
from fastapi import APIRouter, Query
from typing import Optional

from src.retrieval.vector_search import VectorSearch
from src.retrieval.graph_search import GraphSearch

router = APIRouter(prefix="/papers", tags=["Papers"])
vector = VectorSearch()
graph = GraphSearch()


@router.get("/search")
async def semantic_search(
    q: str = Query(..., min_length=3, description="Natural language search query"),
    limit: int = Query(10, ge=1, le=50, description="Max results"),
):
    """
    Semantic search across indexed papers using vector similarity.
    
    Uses sentence-transformers to embed the query and searches
    Qdrant for the most similar paper embeddings.
    """
    results = vector.search_similar(query_text=q, limit=limit)
    return {
        "query": q,
        "count": len(results),
        "results": results,
    }


@router.get("/by-star/{source_id}")
async def papers_for_star(source_id: str):
    """Find papers that mention a specific star (via knowledge graph)."""
    papers = graph.find_star_papers(source_id)
    return {
        "source_id": source_id,
        "count": len(papers),
        "papers": papers,
    }


@router.get("/topic")
async def papers_by_topic(
    keyword: str = Query(..., min_length=2, description="Keyword to search in titles"),
    limit: int = Query(20, ge=1, le=100),
):
    """Find papers by keyword in title/abstract (via knowledge graph)."""
    papers = graph.find_papers_about_topic(keyword, limit=limit)
    return {
        "keyword": keyword,
        "count": len(papers),
        "papers": papers,
    }
