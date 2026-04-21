"""Migration script to update the stars table with professional research columns."""

import logging
from sqlalchemy import text
from src.database import postgres_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate():
    logger.info("Starting database migration for research columns...")
    
    # Columns to add
    new_columns = [
        ("pmra_error", "DOUBLE PRECISION"),
        ("pmdec_error", "DOUBLE PRECISION"),
        ("radial_velocity", "DOUBLE PRECISION"),
        ("radial_velocity_error", "DOUBLE PRECISION"),
        ("phot_g_mean_flux_over_error", "DOUBLE PRECISION"),
        ("astrometric_sigma5d_max", "DOUBLE PRECISION"),
    ]
    
    postgres_conn.connect()
    with postgres_conn.session() as session:
        for col_name, col_type in new_columns:
            try:
                # Check if column exists first
                check_query = text(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='stars' AND column_name='{col_name}';
                """)
                result = session.execute(check_query).fetchone()
                
                if not result:
                    logger.info(f"Adding column {col_name}...")
                    alter_query = text(f"ALTER TABLE stars ADD COLUMN {col_name} {col_type};")
                    session.execute(alter_query)
                    session.commit()
                else:
                    logger.info(f"Column {col_name} already exists.")
            except Exception as e:
                logger.error(f"Failed to add column {col_name}: {e}")
                session.rollback()

    logger.info("Migration complete.")

if __name__ == "__main__":
    migrate()
