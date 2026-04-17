"""Seed synthetic but realistic Gaia-like data for testing when network is unavailable."""

import logging
import random
from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy import text, select

from src.database import postgres_conn
from src.models import Region

logger = logging.getLogger(__name__)

SEED_REGIONS = [
    {"name": "Hyades", "ra": 66.75, "dec": 15.87, "radius_deg": 5.0},
    {"name": "Pleiades", "ra": 56.75, "dec": 24.12, "radius_deg": 2.0},
    {"name": "Orion OB1", "ra": 83.82, "dec": -5.39, "radius_deg": 1.0},
]


def _generate_cluster_stars(
    center_ra: float, center_dec: float, radius_deg: float, count: int, cluster_name: str
) -> List[Dict]:
    """Generate realistic-looking synthetic stars around a cluster center."""
    stars = []
    for i in range(count):
        ra_offset = random.gauss(0, radius_deg / 3)
        dec_offset = random.gauss(0, radius_deg / 3)
        star_ra = (center_ra + ra_offset + 360) % 360
        star_dec = max(-90, min(90, center_dec + dec_offset))

        parallax = random.gauss(8.5, 1.5)
        parallax = max(1.0, parallax)

        if cluster_name == "Hyades":
            pmra = random.gauss(90, 10)
            pmdec = random.gauss(25, 8)
        elif cluster_name == "Pleiades":
            pmra = random.gauss(20, 5)
            pmdec = random.gauss(-45, 5)
        else:
            pmra = random.gauss(5, 15)
            pmdec = random.gauss(-5, 10)

        phot_g = random.gauss(8.0, 2.0)
        phot_bp = phot_g + random.gauss(0.5, 0.3)
        phot_rp = phot_g - random.gauss(0.8, 0.3)

        ruwe = random.gauss(1.0, 0.15)
        ruwe = max(0.5, min(3.0, ruwe))

        source_id = random.randint(10**18, 10**19 - 1)

        stars.append({
            "source_id": str(source_id),
            "ra": round(star_ra, 7),
            "dec": round(star_dec, 7),
            "parallax": round(parallax, 4),
            "pmra": round(pmra, 4),
            "pmdec": round(pmdec, 4),
            "phot_g_mean_mag": round(phot_g, 3),
            "phot_bp_mean_mag": round(phot_bp, 3),
            "phot_rp_mean_mag": round(phot_rp, 3),
            "ruwe": round(ruwe, 3),
            "catalog_source": "GAIA",
        })
    return stars


def seed_synthetic_catalog(db) -> None:
    """Seed synthetic stars for known regions."""
    logger.info("Starting synthetic catalog seeding...")

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

    for region in SEED_REGIONS:
        logger.info(f"Generating synthetic stars for {region['name']}...")
        stars = _generate_cluster_stars(
            region["ra"], region["dec"], region["radius_deg"],
            count=500, cluster_name=region["name"]
        )

        inserted = 0
        with db.session() as session:
            for star in stars:
                result = session.execute(insert_query, star)
                inserted += result.rowcount or 0
            session.commit()

        logger.info(f"Inserted {inserted} stars for {region['name']}")

        from sqlalchemy.dialects.postgresql import insert
        with db.session() as session:
            stmt = insert(Region).values(
                name=region["name"],
                ra=region["ra"],
                dec=region["dec"],
                radius_deg=region["radius_deg"],
                star_count=inserted,
                ingested_at=datetime.now(timezone.utc),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["name"],
                set_={
                    "ra": stmt.excluded.ra,
                    "dec": stmt.excluded.dec,
                    "radius_deg": stmt.excluded.radius_deg,
                    "star_count": inserted,
                    "ingested_at": datetime.now(timezone.utc),
                },
            )
            session.execute(stmt)
            session.commit()

    logger.info("Synthetic catalog seeding complete!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    postgres_conn.connect()
    seed_synthetic_catalog(postgres_conn)
    postgres_conn.close()
