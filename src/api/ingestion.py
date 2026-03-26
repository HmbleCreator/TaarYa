"""
Ingestion API — explicit endpoints to trigger data ingestion pipelines.

Neither pipeline starts automatically on server boot. The user must
POST to these endpoints to kick off ingestion.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.database import postgres_conn, qdrant_conn

router = APIRouter(prefix="/ingest", tags=["ingestion"])
logger = logging.getLogger(__name__)

# Track running jobs so we don't double-trigger
_running: dict[str, bool] = {"gaia": False, "arxiv": False}


def _run_gaia():
    _running["gaia"] = True
    try:
        # Import is deferred here as well — avoids any import-time Gaia contact
        from src.ingestion.seed import seed_catalog  # noqa: PLC0415

        logger.info("Gaia ingestion: starting seed_catalog...")
        seed_catalog(postgres_conn)
        logger.info("Gaia ingestion: complete")
    except Exception as exc:
        logger.error(f"Gaia ingestion failed: {exc}", exc_info=True)
    finally:
        _running["gaia"] = False


def _run_arxiv():
    _running["arxiv"] = True
    try:
        from src.ingestion.arxiv_ingest import ingest_arxiv_papers  # noqa: PLC0415

        logger.info("ArXiv ingestion: starting ingest_arxiv_papers...")
        ingest_arxiv_papers(qdrant_conn)
        logger.info("ArXiv ingestion: complete")
    except Exception as exc:
        logger.error(f"ArXiv ingestion failed: {exc}", exc_info=True)
    finally:
        _running["arxiv"] = False


@router.post("/gaia", summary="Trigger Gaia catalog ingestion")
async def trigger_gaia_ingestion(background_tasks: BackgroundTasks):
    """
    Start (or re-run) the Gaia DR3 catalog seeding pipeline in the background.
    Returns immediately; check server logs for progress.
    """
    if _running["gaia"]:
        raise HTTPException(status_code=409, detail="Gaia ingestion is already running")

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    background_tasks.add_task(loop.run_in_executor, executor, _run_gaia)
    return {"status": "started", "pipeline": "gaia"}


@router.post("/arxiv", summary="Trigger ArXiv paper ingestion")
async def trigger_arxiv_ingestion(background_tasks: BackgroundTasks):
    """
    Start (or re-run) the ArXiv paper ingestion pipeline in the background.
    Returns immediately; check server logs for progress.
    """
    if _running["arxiv"]:
        raise HTTPException(status_code=409, detail="ArXiv ingestion is already running")

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    background_tasks.add_task(loop.run_in_executor, executor, _run_arxiv)
    return {"status": "started", "pipeline": "arxiv"}


@router.get("/status", summary="Check ingestion pipeline status")
async def ingestion_status():
    """Return whether each ingestion pipeline is currently running."""
    return {
        "gaia": "running" if _running["gaia"] else "idle",
        "arxiv": "running" if _running["arxiv"] else "idle",
    }
