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
_running: dict[str, bool] = {"gaia": False, "arxiv": False, "graph": False}
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


def _run_graph():
    _running["graph"] = True
    try:
        from src.ingestion.graph_ingest import ingest_graph  # noqa: PLC0415

        logger.info("Graph reconciliation: starting ingest_graph...")
        ingest_graph()
        logger.info("Graph reconciliation: complete")
    except Exception as exc:
        logger.error(f"Graph reconciliation failed: {exc}", exc_info=True)
    finally:
        _running["graph"] = False


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


@router.post("/graph", summary="Trigger a full Neo4j graph reconciliation")
async def trigger_graph_reconciliation(background_tasks: BackgroundTasks):
    """
    Rebuild or reconcile the Neo4j graph from PostgreSQL/Qdrant in the background.
    Returns immediately; check server logs for progress.
    """
    if _running["graph"]:
        raise HTTPException(status_code=409, detail="Graph reconciliation is already running")

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    background_tasks.add_task(loop.run_in_executor, executor, _run_graph)
    return {"status": "started", "pipeline": "graph"}


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
        "graph": "running" if _running["graph"] else "idle",
        "catalogs": {
            name: "running" if running else "idle"
            for name, running in sorted(_running_catalogs.items())
        },
    }


class ExpandCoverageRequest(BaseModel):
    """Request body for sky-coverage expansion."""
    fetch_gaia: bool = Field(False, description="Also fetch Gaia DR3 stars via TAP+ (requires internet)")
    max_stars_per_region: int = Field(500, ge=10, le=5000, description="Max stars to fetch per region")


_running["expand"] = False
_running["mentioned_in"] = False


def _run_expand_coverage(fetch_gaia: bool, max_stars: int):
    """Background task: seed extended regions and optionally fetch Gaia stars."""
    _running["expand"] = True
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from scripts.expand_sky_coverage import seed_extended_regions, fetch_gaia_for_regions
        count = seed_extended_regions()
        logger.info(f"Seeded {count} extended regions")
        stars = 0
        if fetch_gaia:
            stars = fetch_gaia_for_regions(max_stars_per_region=max_stars)
            logger.info(f"Fetched {stars} Gaia DR3 stars for extended regions")
        # Trigger graph sync for the new data
        try:
            from src.database import neo4j_conn
            neo4j_conn.connect()
            from src.ingestion.graph_ingest import ingest_graph
            ingest_graph()
        except Exception as e:
            logger.warning(f"Post-expansion graph sync failed: {e}")
    except Exception as e:
        logger.error(f"Coverage expansion failed: {e}", exc_info=True)
    finally:
        _running["expand"] = False


@router.post("/expand-coverage", summary="Expand sky coverage with additional clusters")
async def expand_coverage(
    request: ExpandCoverageRequest,
    background_tasks: BackgroundTasks,
):
    """Seed extended regions (globular clusters, OB associations, SFRs, moving groups)
    and optionally fetch Gaia DR3 stars for each region.
    """
    if _running.get("expand"):
        raise HTTPException(status_code=409, detail="Coverage expansion already in progress")

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    background_tasks.add_task(
        loop.run_in_executor, executor,
        _run_expand_coverage, request.fetch_gaia, request.max_stars_per_region,
    )
    return {
        "status": "started",
        "pipeline": "expand-coverage",
        "fetch_gaia": request.fetch_gaia,
        "max_stars_per_region": request.max_stars_per_region,
    }


def _run_mentioned_in_linking():
    """Background task: run cluster-mediated MENTIONED_IN linking."""
    _running["mentioned_in"] = True
    try:
        from src.database import neo4j_conn
        neo4j_conn.connect()
        from src.retrieval.graph_search import GraphSearch
        from src.ingestion.graph_ingest import link_papers_to_stars_via_clusters
        graph = GraphSearch()
        count = link_papers_to_stars_via_clusters(graph)
        logger.info(f"Cluster-mediated linking created {count} MENTIONED_IN edges")
    except Exception as e:
        logger.error(f"MENTIONED_IN linking failed: {e}", exc_info=True)
    finally:
        _running["mentioned_in"] = False


@router.post("/mentioned-in", summary="Populate MENTIONED_IN edges via cluster mediation")
async def trigger_mentioned_in(background_tasks: BackgroundTasks):
    """Create MENTIONED_IN edges between papers and the top stars in clusters they cover."""
    if _running.get("mentioned_in"):
        raise HTTPException(status_code=409, detail="MENTIONED_IN linking already in progress")

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    background_tasks.add_task(
        loop.run_in_executor, executor, _run_mentioned_in_linking,
    )
    return {"status": "started", "pipeline": "mentioned-in"}
