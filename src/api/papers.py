"""Paper search API routes."""
from fastapi import APIRouter, Query

from src.services.paper_service import PaperService
from src.schemas import PaperSearchResponse, PaperTopicResponse, PapersByStarResponse

router = APIRouter(prefix="/papers", tags=["Papers"])
_svc = PaperService()


@router.get("/search", response_model=PaperSearchResponse)
async def semantic_search(
    q: str = Query(..., min_length=3, description="Natural language search query"),
    limit: int = Query(10, ge=1, le=50, description="Max results"),
):
    """Semantic search across indexed papers using vector similarity."""
    results = _svc.semantic_search(query=q, limit=limit)
    return PaperSearchResponse(query=q, count=len(results), results=results)


@router.get("/by-star/{source_id}", response_model=PapersByStarResponse)
async def papers_for_star(
    source_id: str,
    include_cluster_context: bool = Query(
        True,
        description="Include papers linked through the star's cluster membership",
    ),
):
    """Find papers that mention a specific star (via knowledge graph)."""
    papers = _svc.by_star(source_id, include_cluster_context=include_cluster_context)
    return PapersByStarResponse(source_id=source_id, count=len(papers), papers=papers)


@router.get("/topic", response_model=PaperTopicResponse)
async def papers_by_topic(
    keyword: str = Query(..., min_length=2, description="Keyword to search in titles"),
    limit: int = Query(20, ge=1, le=100),
):
    """Find papers by keyword in title/abstract (via knowledge graph)."""
    papers = _svc.by_topic(keyword, limit=limit)
    return PaperTopicResponse(keyword=keyword, count=len(papers), papers=papers)
