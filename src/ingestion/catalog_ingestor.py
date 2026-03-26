"""Generic catalog ingestion for non-Gaia survey files."""

import argparse
import logging
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy.dialects.postgresql import insert

from src.database import postgres_conn
from src.models import Star
from src.ingestion.catalog_parser import CatalogParser, _normalize_catalog_name

logger = logging.getLogger(__name__)


class CatalogIngestor:
    """Ingest catalog files into the shared stars table."""

    def __init__(self, catalog_source: str, field_map: Optional[Dict[str, str]] = None):
        self.catalog_source = _normalize_catalog_name(catalog_source)
        self.parser = CatalogParser(self.catalog_source, field_map=field_map)

    def ingest_file(self, filepath: Path, limit: Optional[int] = None) -> int:
        logger.info(f"Starting {self.catalog_source} ingestion: {filepath}")
        total_ingested = 0

        postgres_conn.connect()

        with postgres_conn.session() as session:
            for chunk in self.parser.parse(filepath):
                if limit and total_ingested >= limit:
                    logger.info(f"Limit reached: {limit}")
                    break

                if limit:
                    remaining = limit - total_ingested
                    chunk = chunk.head(remaining)

                records = chunk.to_dict("records")
                if not records:
                    continue

                stmt = insert(Star).values(records)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["source_id"],
                    set_={col: stmt.excluded[col] for col in chunk.columns if col != "id"},
                )

                try:
                    session.execute(stmt)
                    session.commit()
                    total_ingested += len(records)
                    logger.info(f"Ingested {total_ingested} {self.catalog_source} records...")
                except Exception as exc:
                    logger.error(f"Failed to ingest {self.catalog_source} chunk: {exc}", exc_info=True)
                    session.rollback()

        logger.info(f"{self.catalog_source} ingestion complete: {total_ingested} total records")
        return total_ingested

    def get_stats(self) -> dict:
        postgres_conn.connect()

        with postgres_conn.session() as session:
            from sqlalchemy import func

            total = session.query(func.count(Star.id)).scalar()
            per_catalog = (
                session.query(Star.catalog_source, func.count(Star.id))
                .group_by(Star.catalog_source)
                .order_by(func.count(Star.id).desc())
                .all()
            )
            return {
                "total_stars": total,
                "catalogs": [(catalog, int(count)) for catalog, count in per_catalog],
            }


def main() -> None:
    from src.utils.logger import setup_logging

    setup_logging()

    parser = argparse.ArgumentParser(description="Ingest a generic astronomy catalog file")
    parser.add_argument("catalog_source", help="Catalog label, e.g. WISE, 2MASS, PAN-STARRS")
    parser.add_argument("filepath", help="Path to a CSV or JSON catalog file")
    parser.add_argument("limit", nargs="?", type=int, default=None, help="Maximum number of rows to ingest")
    args = parser.parse_args()

    ingestor = CatalogIngestor(args.catalog_source)
    count = ingestor.ingest_file(Path(args.filepath), limit=args.limit)
    stats = ingestor.get_stats()
    print(f"\nIngested {count} rows")
    print(f"Database stats: {stats}")


if __name__ == "__main__":
    main()
