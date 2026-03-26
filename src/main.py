"""FastAPI application entry point."""

import sys
import os

os.environ["PYTHONIOENCODING"] = "utf-8"

import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from src.config import settings
from src.utils.logger import setup_logging
from src.database import postgres_conn, qdrant_conn, neo4j_conn
from src.api import regions as regions_router

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Resolve project root (parent of src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"


def _ensure_star_schema() -> None:
    """Add optional columns needed by newer visualizations without breaking old installs."""
    postgres_conn.connect()
    try:
        with postgres_conn.engine.begin() as conn:
            conn.execute(text("ALTER TABLE stars ADD COLUMN IF NOT EXISTS object_class VARCHAR(40)"))
    except Exception as exc:
        logger.warning(f"Star schema migration skipped or already applied: {exc}")



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle for database connections."""
    logger.info("Starting TaarYa — connecting backends...")
    try:
        postgres_conn.connect()
        logger.info("PostgreSQL: connected")

        # Ensure regions table exists
        from src.models import Base

        Base.metadata.create_all(postgres_conn.engine)
        _ensure_star_schema()
        logger.info("Database tables: ensured")

        qdrant_conn.connect()
        logger.info("Qdrant: connected")
    except Exception as e:
        logger.error(f"Failed to connect databases: {e}", exc_info=True)

    try:
        neo4j_conn.connect()
        logger.info("Neo4j: connected")
    except Exception as e:
        logger.warning(f"Neo4j unavailable — graph features disabled: {e}")

    logger.info("TaarYa ready. Ingestion pipelines idle — trigger via POST /api/ingest/gaia or /api/ingest/arxiv")
    yield  # App is running

    logger.info("Shutting down TaarYa — closing connections...")
    postgres_conn.close()
    qdrant_conn.close()
    neo4j_conn.close()
    logger.info("All connections closed")



# Create FastAPI app
app = FastAPI(
    title="TaarYa",
    description="Intelligent RAG-Driven Architecture for Astronomical Star Catalogs",
    version="0.2.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    """Redirect to the TaarYa Dashboard."""
    return RedirectResponse(url="/static/dashboard.html")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# Register API routers
from src.api.stars import router as stars_router
from src.api.papers import router as papers_router
from src.api.search import router as search_router, stats_router
from src.api.agent import router as agent_router
from src.api.sessions import router as sessions_router
from src.api.ingestion import router as ingestion_router

app.include_router(stars_router, prefix="/api")
app.include_router(papers_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(regions_router.router, prefix="/api")
app.include_router(ingestion_router, prefix="/api")



if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "development",
    )
