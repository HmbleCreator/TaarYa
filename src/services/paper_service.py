"""Paper search service — wraps VectorSearch + GraphSearch with error handling."""
import logging
from typing import List, Dict, Any

from fastapi import HTTPException

from src.retrieval.vector_search import VectorSearch
from src.retrieval.graph_search import GraphSearch

logger = logging.getLogger(__name__)


class PaperService:
    """Business logic layer for paper search operations."""

    def __init__(self):
        self._vector = VectorSearch()
        self._graph = GraphSearch()

    def semantic_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Semantic vector search across indexed papers."""
        try:
            return self._vector.search_similar(query_text=query, limit=limit)
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            raise HTTPException(status_code=503, detail=f"Vector database unavailable: {e}")

    def by_star(self, source_id: str) -> List[Dict[str, Any]]:
        """Find papers mentioning a specific star via the knowledge graph."""
        try:
            return self._graph.find_star_papers(source_id)
        except Exception as e:
            logger.error(f"Paper-by-star lookup failed: {e}")
            raise HTTPException(status_code=503, detail=f"Graph database unavailable: {e}")

    def by_topic(self, keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Find papers by keyword in title/abstract."""
        try:
            return self._graph.find_papers_about_topic(keyword, limit=limit)
        except Exception as e:
            logger.error(f"Topic search failed: {e}")
            raise HTTPException(status_code=503, detail=f"Graph database unavailable: {e}")
