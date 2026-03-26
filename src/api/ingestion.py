"""
Ingestion API — explicit endpoints to trigger data ingestion pipelines.

Neither pipeline starts automatically on server boot. The user must
POST to these endpoints to kick off ingestion.
"""

import asyncio
import base64
import binascii
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict

from src.database import postgres_conn, qdrant_conn

router = APIRouter(prefix="/ingest", tags=["ingestion"])
logger = logging.getLogger(__name__)

# Track running jobs so we don't double-trigger
_running: dict[str, bool] = {"gaia": False, "arxiv": False}
_running_catalogs: dict[str, bool] = {}


class CatalogIngestRequest(BaseModel):
    """Request body for generic catalog ingestion."""
    catalog_source: str = Field(..., min_length=1, description="Catalog label, e.g. WISE")
    filepath: str = Field(..., min_length=1, description="Path to a CSV or JSON file on the server")
    limit: Optional[int] = Field(None, ge=1, description="Optional row limit")
    field_map: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional column remapping for non-standard catalog files",
    )


class CatalogUploadRequest(BaseModel):
    """Request body for browser-based catalog uploads."""
    catalog_source: str = Field(..., min_length=1, description="Catalog label, e.g. WISE")
    filename: str = Field(..., min_length=1, description="Original file name used to infer the parser")
    content_base64: str = Field(..., min_length=1, description="Base64-encoded file content")
    limit: Optional[int] = Field(None, ge=1, description="Optional row limit")
    field_map: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional column remapping for non-standard catalog files",
    )


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


def _run_catalog(
    catalog_source: str,
    filepath: str,
    limit: Optional[int],
    field_map: Optional[Dict[str, str]],
    cleanup_path: Optional[str] = None,
):
    catalog_key = catalog_source.strip().upper()
    _running_catalogs[catalog_key] = True
    try:
        from src.ingestion.catalog_ingestor import CatalogIngestor  # noqa: PLC0415

        logger.info(f"{catalog_key} ingestion: starting catalog ingest...")
        ingestor = CatalogIngestor(catalog_key, field_map=field_map)
        ingestor.ingest_file(Path(filepath), limit=limit)
        logger.info(f"{catalog_key} ingestion: complete")
    except Exception as exc:
        logger.error(f"{catalog_key} ingestion failed: {exc}", exc_info=True)
    finally:
        _running_catalogs[catalog_key] = False
        if cleanup_path:
            try:
                Path(cleanup_path).unlink(missing_ok=True)
            except Exception:
                logger.warning(f"Failed to remove temporary upload file: {cleanup_path}")


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


@router.post("/catalog", summary="Trigger a generic catalog ingestion")
async def trigger_catalog_ingestion(
    request: CatalogIngestRequest,
    background_tasks: BackgroundTasks,
):
    """Ingest a generic survey catalog file into the shared stars table."""
    catalog_key = request.catalog_source.strip().upper()
    if _running_catalogs.get(catalog_key):
        raise HTTPException(
            status_code=409,
            detail=f"{catalog_key} ingestion is already running",
        )

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    background_tasks.add_task(
        loop.run_in_executor,
        executor,
        _run_catalog,
        request.catalog_source,
        request.filepath,
        request.limit,
        request.field_map,
    )
    return {"status": "started", "pipeline": "catalog", "catalog_source": catalog_key}


@router.post("/catalog/upload", summary="Upload and ingest a catalog file from the browser")
async def upload_catalog_ingestion(
    request: CatalogUploadRequest,
    background_tasks: BackgroundTasks,
):
    """Accept a browser-uploaded CSV/JSON/FITS file and ingest it asynchronously."""
    catalog_key = request.catalog_source.strip().upper()
    if _running_catalogs.get(catalog_key):
        raise HTTPException(
            status_code=409,
            detail=f"{catalog_key} ingestion is already running",
        )

    try:
        payload = base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid upload payload: {exc}") from exc

    suffix = Path(request.filename).suffix.lower() or ".csv"
    if suffix not in {".csv", ".json", ".jsonl", ".fits", ".fit"}:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use CSV, JSON, JSONL, FITS, or FIT.")

    temp_dir = Path(tempfile.gettempdir()) / "taarya_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=temp_dir) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    background_tasks.add_task(
        loop.run_in_executor,
        executor,
        _run_catalog,
        request.catalog_source,
        str(temp_path),
        request.limit,
        request.field_map,
        str(temp_path),
    )
    return {
        "status": "started",
        "pipeline": "catalog",
        "catalog_source": catalog_key,
        "filename": request.filename,
        "upload": True,
    }


@router.get("/status", summary="Check ingestion pipeline status")
async def ingestion_status():
    """Return whether each ingestion pipeline is currently running."""
    return {
        "gaia": "running" if _running["gaia"] else "idle",
        "arxiv": "running" if _running["arxiv"] else "idle",
        "catalogs": {
            name: "running" if running else "idle"
            for name, running in sorted(_running_catalogs.items())
        },
    }
