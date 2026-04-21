"""CLI entry points for installing and operating TaarYa as a Python package."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from src.utils.logger import setup_logging


def run_api(argv: Optional[Sequence[str]] = None) -> None:
    """Launch the FastAPI service."""
    parser = argparse.ArgumentParser(description="Run the TaarYa API service.")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind.")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable hot reload regardless of environment.",
    )
    args = parser.parse_args(argv)

    from src.config import settings
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload or settings.environment == "development",
    )


def init_db_cli(argv: Optional[Sequence[str]] = None) -> None:
    """Initialize PostgreSQL tables and the Q3C extension."""
    argparse.ArgumentParser(description="Initialize the TaarYa database.").parse_args(
        argv
    )
    setup_logging()

    from src.init_db import init_database

    init_database()


def seed_cli(argv: Optional[Sequence[str]] = None) -> None:
    """Seed well-known regions into the local catalog."""
    argparse.ArgumentParser(
        description="Seed famous sky regions into the local catalog."
    ).parse_args(argv)
    setup_logging()

    from src.database import postgres_conn
    from src.ingestion.seed import seed_catalog

    postgres_conn.connect()
    try:
        seed_catalog(postgres_conn)
    finally:
        postgres_conn.close()


def ingest_gaia_cli(argv: Optional[Sequence[str]] = None) -> None:
    """Ingest a Gaia catalog file into PostgreSQL."""
    parser = argparse.ArgumentParser(description="Ingest a Gaia catalog file.")
    parser.add_argument("filepath", type=str, help="Path to a Gaia CSV or FITS file.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional record limit for partial ingestion.",
    )
    args = parser.parse_args(argv)
    setup_logging()

    from src.ingestion.gaia_ingestor import GaiaIngestor

    GaiaIngestor().ingest_file(args.filepath, limit=args.limit)


def ingest_arxiv_cli(argv: Optional[Sequence[str]] = None) -> None:
    """Ingest astronomy papers from arXiv into Qdrant."""
    parser = argparse.ArgumentParser(description="Ingest astronomy papers from arXiv.")
    parser.add_argument(
        "--max-papers",
        type=int,
        default=300,
        help="Maximum number of papers to ingest.",
    )
    args = parser.parse_args(argv)
    setup_logging()

    from src.database import qdrant_conn
    from src.ingestion.arxiv_ingest import ingest_arxiv_papers

    qdrant_conn.connect()
    try:
        ingest_arxiv_papers(qdrant_conn, max_papers=args.max_papers)
    finally:
        qdrant_conn.close()
