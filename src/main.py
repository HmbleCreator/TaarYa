"""FastAPI application entry point."""
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import logging

from src.config import settings
from src.utils.logger import setup_logging

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Resolve project root (parent of src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"

# Create FastAPI app
app = FastAPI(
    title="TaarYa",
    description="Intelligent RAG-Driven Architecture for Astronomical Star Catalogs",
    version="0.1.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (CSS, JS)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse)
async def root():
    """Serve the TaarYa dashboard UI."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# Register API routers
from src.api.stars import router as stars_router
from src.api.papers import router as papers_router
from src.api.search import router as search_router, stats_router
from src.api.agent import router as agent_router

app.include_router(stars_router, prefix="/api")
app.include_router(papers_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(agent_router, prefix="/api")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True if settings.environment == "development" else False
    )
