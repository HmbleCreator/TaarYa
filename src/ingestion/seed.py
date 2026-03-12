"""Seed a few well-known sky regions into the local catalog."""

import logging
from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy import text, select

from src.database import postgres_conn
from src.ingestion.gaia_query import query_gaia_region
from src.models import Region
from src.utils.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

SEED_REGIONS: List[Dict[str, float]] = [
    {"name": "Hyades", "ra": 66.75, "dec": 15.87, "radius_deg": 5.0},
    {"name": "Pleiades", "ra": 56.75, "dec": 24.12, "radius_deg": 2.0},
    {"name": "Orion OB1", "ra": 83.82, "dec": -5.39, "radius_deg": 1.0},
]


def _upsert_region(
    db, name: str, ra: float, dec: float, radius_deg: float, star_count: int
) -> None:
    """Insert or update a region record."""
    from sqlalchemy.dialects.postgresql import insert
    from src.models import Region

    with db.session() as session:
        stmt = insert(Region).values(
            name=name,
            ra=ra,
            dec=dec,
            radius_deg=radius_deg,
            star_count=star_count,
            ingested_at=datetime.now(timezone.utc),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["name"],
            set_={
                "ra": stmt.excluded.ra,
                "dec": stmt.excluded.dec,
                "radius_deg": stmt.excluded.radius_deg,
                "star_count": stmt.excluded.star_count,
                "ingested_at": stmt.excluded.ingested_at,
            },
        )
        session.execute(stmt)
        session.commit()


def seed_catalog(db) -> None:
    """Seed a few famous regions if they are not already present."""
    count_query = text("""
        SELECT COUNT(*)
        FROM stars
        WHERE q3c_radial_query(ra, dec, :ra, :dec, :radius)
    """)
    insert_query = text("""
        INSERT INTO stars (
            source_id, ra, dec, parallax, pmra, pmdec,
            phot_g_mean_mag, catalog_source
        )
        VALUES (
            :source_id, :ra, :dec, :parallax, :pmra, :pmdec,
            :phot_g_mean_mag, :catalog_source
        )
        ON CONFLICT (source_id) DO NOTHING
    """)

    # Get existing region counts from regions table
    with db.session() as session:
        existing_regions = {
            r.name: r.star_count
            for r in session.execute(select(Region)).scalars().all()
        }

    for region in SEED_REGIONS:
        # Get existing star count for this region
        existing = existing_regions.get(region["name"], 0)
        offset = existing

        logger.info(
            f"Seed region {region['name']}: existing={existing}, fetching from offset {offset}..."
        )

        logger.info(f"Seed region {region['name']}: starting Gaia query...")

        try:
            rows = query_gaia_region(
                region["ra"],
                region["dec"],
                region["radius_deg"],
                max_stars=5000,
                offset=offset,
            )
        except Exception as e:
            logger.warning(
                f"Seed region {region['name']}: Gaia query failed ({e}), skipping"
            )
            continue

        inserted = 0
        if rows:
            with db.session() as session:
                for row in rows:
                    row["catalog_source"] = "GAIA"
                    result = session.execute(insert_query, row)
                    inserted += result.rowcount or 0
                session.commit()

        total_count = existing + inserted
        logger.info(
            f"Seed region {region['name']}: inserted {inserted} rows (total: {total_count})"
        )

        # Upsert region record
        _upsert_region(
            db,
            region["name"],
            region["ra"],
            region["dec"],
            region["radius_deg"],
            total_count,
        )


if __name__ == "__main__":
    postgres_conn.connect()
    seed_catalog(postgres_conn)
    postgres_conn.close()
