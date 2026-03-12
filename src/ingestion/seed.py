"""Seed a few well-known sky regions into the local catalog."""
import logging
import socket
from typing import Dict, List

from astroquery.gaia import Gaia
from sqlalchemy import text

logger = logging.getLogger(__name__)

SEED_REGIONS: List[Dict[str, float]] = [
    {"name": "Hyades", "ra": 66.75, "dec": 15.87, "radius_deg": 5.0},
    {"name": "Pleiades", "ra": 56.75, "dec": 24.12, "radius_deg": 2.0},
    {"name": "Orion OB1", "ra": 83.82, "dec": -5.39, "radius_deg": 1.0},
]


def seed_catalog(db) -> None:
    """Seed a few famous regions if they are not already present."""
    Gaia.ROW_LIMIT = 2000
    Gaia.MAIN_GAIA_TABLE = "gaiadr3.gaia_source"

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

    for region in SEED_REGIONS:
        with db.session() as session:
            existing = session.execute(count_query, {
                "ra": region["ra"],
                "dec": region["dec"],
                "radius": region["radius_deg"],
            }).scalar() or 0

        if existing > 0:
            logger.info(f"Seed region {region['name']}: already loaded ({existing} stars), skipping")
            continue

        gaia_query = f"""
            SELECT TOP 2000
                source_id, ra, dec, parallax, pmra, pmdec, phot_g_mean_mag, bp_rp
            FROM gaiadr3.gaia_source
            WHERE CONTAINS(
                POINT('ICRS', ra, dec),
                CIRCLE('ICRS', {region['ra']}, {region['dec']}, {region['radius_deg']})
            ) = 1
              AND parallax > 0
              AND phot_g_mean_mag < 18
        """

        try:
            job = Gaia.launch_job_async(gaia_query, verbose=False)
            table = job.get_results()
        except (socket.timeout, TimeoutError, OSError, Exception) as e:
            logger.warning(f"Seed region {region['name']}: Gaia query failed ({e}), skipping")
            continue

        rows = []
        for record in table:
            rows.append({
                "source_id": str(record["source_id"]),
                "ra": float(record["ra"]),
                "dec": float(record["dec"]),
                "parallax": float(record["parallax"]) if record["parallax"] is not None else None,
                "pmra": float(record["pmra"]) if record["pmra"] is not None else None,
                "pmdec": float(record["pmdec"]) if record["pmdec"] is not None else None,
                "phot_g_mean_mag": float(record["phot_g_mean_mag"]) if record["phot_g_mean_mag"] is not None else None,
                "catalog_source": "GAIA",
            })

        inserted = 0
        if rows:
            with db.session() as session:
                for row in rows:
                    result = session.execute(insert_query, row)
                    inserted += result.rowcount or 0
                session.commit()

        logger.info(f"Seed region {region['name']}: inserted {inserted} rows")
