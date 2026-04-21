"""Verify the scientific robustness of TaarYa."""

import logging
from src.retrieval.spatial_search import SpatialSearch
from src.utils.scientific_output import export_to_votable, export_to_json
from src.database import postgres_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_scientific_grade():
    logger.info("Starting Scientific Robustness Verification...")
    
    spatial = SpatialSearch()
    postgres_conn.connect()
    
    # 1. Test Coordinate Conversion: Galactic Center region in Galactic coordinates
    # l=0, b=0 is the Galactic Center
    logger.info("Testing Galactic coordinate search (l=0, b=0)...")
    galactic_stars = spatial.cone_search(ra=0, dec=0, radius=0.5, frame="galactic", limit=10)
    
    if galactic_stars:
        logger.info(f"SUCCESS: Found {len(galactic_stars)} stars using Galactic coordinates.")
        logger.info(f"First star ICRS: RA={galactic_stars[0]['ra']}, Dec={galactic_stars[0]['dec']}")
    else:
        logger.warning("No stars found in Galactic Center (database might not be seeded for this region).")

    # 2. Test Unit Handling: High-resolution search in arcminutes
    logger.info("Testing radius unit handling (30 arcminutes)...")
    # Pleiades: RA=56.75, Dec=24.12
    arcmin_stars = spatial.cone_search(ra=56.75, dec=24.12, radius=30, unit="arcmin", limit=10)
    
    if arcmin_stars:
        logger.info(f"SUCCESS: Found {len(arcmin_stars)} stars using arcminute units.")
    else:
        logger.error("FAILED: No stars found in Pleiades with 30 arcmin radius.")

    # 3. Test Provenance & Export
    if arcmin_stars:
        logger.info("Testing Research Provenance & VOTable Export...")
        votable = export_to_votable(arcmin_stars)
        
        if "Provenance_Type" in votable and "Provenance_RawQuery" in votable:
            logger.info("SUCCESS: VOTable contains research provenance metadata.")
        else:
            logger.error("FAILED: VOTable missing provenance metadata.")
            
        json_out = export_to_json(arcmin_stars)
        if '"provenance":' in json_out:
            logger.info("SUCCESS: JSON contains research provenance metadata.")
        else:
            logger.error("FAILED: JSON missing provenance metadata.")

    logger.info("Scientific Robustness Verification Complete.")

if __name__ == "__main__":
    verify_scientific_grade()
