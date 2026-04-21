"""Seed more regions for robust research evaluation."""

import logging
from datetime import datetime
from src.ingestion.gaia_query import query_gaia_region
from src.models import Region
from src.database import postgres_conn
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Regions to seed for a robust benchmark
RESEARCH_REGIONS = [
    {"name": "Galactic Center", "ra": 266.41, "dec": -29.00, "radius": 0.5},
    {"name": "LMC (Large Magellanic Cloud)", "ra": 80.89, "dec": -69.75, "radius": 0.5},
    {"name": "SMC (Small Magellanic Cloud)", "ra": 13.18, "dec": -72.82, "radius": 0.5},
    {"name": "Omega Centauri", "ra": 201.69, "dec": -47.47, "radius": 0.3},
    {"name": "M45 (Pleiades Extension)", "ra": 56.75, "dec": 24.12, "radius": 2.0},
    {"name": "Hyades Extension", "ra": 66.75, "dec": 15.87, "radius": 5.0},
    {"name": "Alpha Centauri", "ra": 219.9, "dec": -60.83, "radius": 0.1},
    {"name": "Betelgeuse Region", "ra": 88.79, "dec": 7.40, "radius": 0.5},
]

def ingest_region(name: str, ra: float, dec: float, radius_deg: float = 1.0):
    insert_query = text("""
        INSERT INTO stars (
            source_id, ra, dec, 
            parallax, parallax_error,
            pmra, pmra_error, pmdec, pmdec_error,
            radial_velocity, radial_velocity_error,
            phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag,
            phot_g_mean_flux_over_error, astrometric_sigma5d_max, ruwe,
            catalog_source
        )
        VALUES (
            :source_id, :ra, :dec, 
            :parallax, :parallax_error,
            :pmra, :pmra_error, :pmdec, :pmdec_error,
            :radial_velocity, :radial_velocity_error,
            :phot_g_mean_mag, :phot_bp_mean_mag, :phot_rp_mean_mag,
            :phot_g_mean_flux_over_error, :astrometric_sigma5d_max, :ruwe,
            :catalog_source
        )
        ON CONFLICT (source_id) DO NOTHING
    """)

    try:
        # Query Gaia
        stars = query_gaia_region(ra, dec, radius_deg)
        if not stars:
            return f"No stars found in region '{name}' at RA={ra}, Dec={dec} with radius={radius_deg}°."

        # Insert stars
        postgres_conn.connect()
        with postgres_conn.session() as session:
            inserted = 0
            for row in stars:
                row["catalog_source"] = "GAIA"
                result = session.execute(insert_query, row)
                inserted += result.rowcount or 0

            # Upsert region record
            session.merge(
                Region(
                    name=name,
                    ra=ra,
                    dec=dec,
                    radius_deg=radius_deg,
                    star_count=inserted,
                    ingested_at=datetime.utcnow(),
                )
            )
            session.commit()

        return f"Successfully ingested {inserted} stars from region '{name}'."
    except Exception as e:
        return f"Error ingesting region '{name}': {str(e)}"

def seed_all():
    logger.info("Starting research region seeding...")
    for region in RESEARCH_REGIONS:
        logger.info(f"Seeding {region['name']}...")
        result = ingest_region(
            name=region["name"],
            ra=region["ra"],
            dec=region["dec"],
            radius_deg=region["radius"]
        )
        logger.info(result)

if __name__ == "__main__":
    seed_all()
