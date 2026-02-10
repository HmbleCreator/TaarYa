"""Ingest Gaia catalog data into PostgreSQL."""
import logging
from pathlib import Path
from typing import Optional
import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from src.database import postgres_conn
from src.models import Star
from src.ingestion.gaia_parser import GaiaParser

logger = logging.getLogger(__name__)


class GaiaIngestor:
    """Ingest Gaia catalog data into PostgreSQL with Q3C indexing."""
    
    def __init__(self):
        self.parser = GaiaParser()
    
    def ingest_file(self, filepath: Path, limit: Optional[int] = None) -> int:
        """
        Ingest a Gaia catalog file.
        
        Args:
            filepath: Path to catalog file
            limit: Maximum number of records to ingest (None for all)
            
        Returns:
            Number of records ingested
        """
        logger.info(f"Starting ingestion: {filepath}")
        total_ingested = 0
        
        postgres_conn.connect()
        
        with postgres_conn.session() as session:
            for chunk in self.parser.parse(filepath):
                # Apply limit if specified
                if limit and total_ingested >= limit:
                    logger.info(f"Limit reached: {limit}")
                    break
                
                if limit:
                    remaining = limit - total_ingested
                    chunk = chunk.head(remaining)
                
                # Convert DataFrame to dict records
                records = chunk.to_dict('records')
                
                # Upsert using PostgreSQL INSERT ... ON CONFLICT
                stmt = insert(Star).values(records)
                stmt = stmt.on_conflict_do_update(
                    index_elements=['source_id'],
                    set_={col: stmt.excluded[col] for col in chunk.columns if col != 'id'}
                )
                
                try:
                    session.execute(stmt)
                    session.commit()
                    total_ingested += len(records)
                    logger.info(f"Ingested {total_ingested} records...")
                except Exception as e:
                    import traceback
                    logger.error(f"Failed to ingest chunk: {str(e)}")
                    traceback.print_exc()
                    session.rollback()
        
        logger.info(f"Ingestion complete: {total_ingested} total records")
        return total_ingested
    
    def get_stats(self) -> dict:
        """Get ingestion statistics."""
        postgres_conn.connect()
        
        with postgres_conn.session() as session:
            from sqlalchemy import func
            
            total = session.query(func.count(Star.id)).scalar()
            
            stats = {
                'total_stars': total,
                'catalogs': session.query(Star.catalog_source).distinct().all()
            }
            
            return stats


if __name__ == "__main__":
    from src.utils.logger import setup_logging
    import sys
    
    setup_logging()
    
    if len(sys.argv) < 2:
        print("Usage: python -m src.ingestion.gaia_ingestor <filepath> [limit]")
        sys.exit(1)
    
    filepath = Path(sys.argv[1])
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    ingestor = GaiaIngestor()
    count = ingestor.ingest_file(filepath, limit=limit)
    
    stats = ingestor.get_stats()
    print(f"\nDatabase stats: {stats}")
