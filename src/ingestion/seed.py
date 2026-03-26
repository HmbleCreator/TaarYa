"""Seed a few well-known sky regions into the local catalog."""

import logging
from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy import text, select

from src.database import postgres_conn
from src.ingestion.gaia_query import query_gaia_region
from src.models import Region

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
            phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, ruwe,
            catalog_source
        )
        VALUES (
            :source_id, :ra, :dec, :parallax, :pmra, :pmdec,
            :phot_g_mean_mag, :phot_bp_mean_mag, :phot_rp_mean_mag, :ruwe,
            :catalog_source
        )
        ON CONFLICT (source_id) DO UPDATE SET
            ra = EXCLUDED.ra,
            dec = EXCLUDED.dec,
            parallax = EXCLUDED.parallax,
            pmra = EXCLUDED.pmra,
            pmdec = EXCLUDED.pmdec,
            phot_g_mean_mag = EXCLUDED.phot_g_mean_mag,
            phot_bp_mean_mag = EXCLUDED.phot_bp_mean_mag,
            phot_rp_mean_mag = EXCLUDED.phot_rp_mean_mag,
            ruwe = EXCLUDED.ruwe,
            catalog_source = EXCLUDED.catalog_source
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
        inserted = 0

        def _upsert_rows(rows, count_new: bool) -> None:
            nonlocal inserted
            if not rows:
                return
            with db.session() as session:
                for row in rows:
                    row["catalog_source"] = "GAIA"
                    result = session.execute(insert_query, row)
                    if count_new:
                        inserted += result.rowcount or 0
                session.commit()

        if existing > 0:
            logger.info(
                f"Seed region {region['name']}: refreshing {existing} existing rows from Gaia..."
            )
            try:
                refresh_rows = query_gaia_region(
                    region["ra"],
                    region["dec"],
                    region["radius_deg"],
                    max_stars=existing,
                    offset=0,
                )
                _upsert_rows(refresh_rows, count_new=False)
            except Exception as e:
                logger.warning(
                    f"Seed region {region['name']}: refresh query failed ({e}), continuing"
                )

        logger.info(
            f"Seed region {region['name']}: existing={existing}, fetching new rows from offset {existing}..."
        )

        logger.info(f"Seed region {region['name']}: starting Gaia query...")

        try:
            rows = query_gaia_region(
                region["ra"],
                region["dec"],
                region["radius_deg"],
                max_stars=5000,
                offset=existing,
            )
        except Exception as e:
            logger.warning(
                f"Seed region {region['name']}: Gaia query failed ({e}), skipping"
            )
            continue

        _upsert_rows(rows, count_new=True)

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
