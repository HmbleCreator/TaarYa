"""FastAPI application entry point."""
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from src.config import settings
from src.utils.logger import setup_logging
from src.database import postgres_conn, qdrant_conn, neo4j_conn

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Resolve project root (parent of src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle for database connections."""
    logger.info("Starting TaarYa — connecting backends...")
    try:
        postgres_conn.connect()
        logger.info("PostgreSQL: connected")
    except Exception as e:
        logger.warning(f"PostgreSQL: {e}")
    try:
        qdrant_conn.connect()
        logger.info("Qdrant: connected")
    except Exception as e:
        logger.warning(f"Qdrant: {e}")
    try:
        neo4j_conn.connect()
        logger.info("Neo4j: connected")
    except Exception as e:
        logger.warning(f"Neo4j: {e}")

    yield  # App is running

    logger.info("Shutting down TaarYa — closing connections...")
    postgres_conn.close()
    qdrant_conn.close()
    neo4j_conn.close()


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
        reload=True if settings.environment == "development" else False,
    )
