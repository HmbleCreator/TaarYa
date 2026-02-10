"""API routes."""
from src.api.stars import router as stars_router
from src.api.papers import router as papers_router
from src.api.search import router as search_router, stats_router

__all__ = ["stars_router", "papers_router", "search_router", "stats_router"]
