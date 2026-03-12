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

from src.config import settings
from src.utils.logger import setup_logging
from src.database import postgres_conn, qdrant_conn, neo4j_conn
from src.ingestion.seed import seed_catalog
from src.ingestion.arxiv_ingest import ingest_arxiv_papers

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Resolve project root (parent of src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"


async def run_seed_in_background(db, qdrant):
    """Run catalog seeding and ArXiv ingestion without blocking app startup."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        try:
            logger.info("Background task: starting seed_catalog...")
            await loop.run_in_executor(pool, seed_catalog, db)
            logger.info("Background task: seed_catalog completed")
        except Exception as e:
            logger.error(f"seed_catalog failed: {e}", exc_info=True)
            # Don't return — still attempt ArXiv ingestion

        try:
            logger.info("Background task: starting ingest_arxiv_papers...")
            await loop.run_in_executor(pool, ingest_arxiv_papers, qdrant)
            logger.info("Background task: ingest_arxiv_papers completed")
        except Exception as e:
            logger.error(f"ingest_arxiv_papers failed: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle for database connections."""
    logger.info("Starting TaarYa — connecting backends...")
    try:
        postgres_conn.connect()
        logger.info("PostgreSQL: connected")
        qdrant_conn.connect()
        logger.info("Qdrant: connected")

        if os.getenv("RUN_INGESTION", "").lower() == "true":
            task = asyncio.create_task(
                run_seed_in_background(postgres_conn, qdrant_conn)
            )
            task.add_done_callback(
                lambda t: logger.error(
                    f"Background task failed: {t.exception()}", exc_info=t.exception()
                )
                if not t.cancelled() and t.exception()
                else None
            )
        else:
            logger.info(
                "Skipping seed and ingestion (set RUN_INGESTION=true to enable)"
            )
    except Exception as e:
        logger.error(f"Failed to start background task: {e}", exc_info=True)

    try:
        neo4j_conn.connect()
        logger.info("Neo4j: connected")
    except Exception as e:
        logger.warning(f"Neo4j unavailable — graph features disabled: {e}")

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

app.include_router(stars_router, prefix="/api")
app.include_router(papers_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "development",
    )
