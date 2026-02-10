import logging
from pathlib import Path
from astroquery.gaia import Gaia

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_sample_data(output_file='gaia_sample.csv', limit=1000):
    """Fetch sample data from Gaia DR3 using ADQL."""
    logger.info(f"Fetching {limit} rows from Gaia DR3...")
    
    # Query for specific columns required by the ingestor
    query = f"""
    SELECT TOP {limit}
        source_id, ra, dec, parallax, pmra, pmdec, phot_g_mean_mag, 
        phot_bp_mean_mag, phot_rp_mean_mag, radial_velocity, teff_gspphot
    FROM gaiadr3.gaia_source
    WHERE parallax IS NOT NULL
    """
    
    try:
        job = Gaia.launch_job_async(query)
        results = job.get_results()
        
        logger.info(f"Fetched {len(results)} rows.")
        
        # Save as CSV
        results.write(output_file, format='csv', overwrite=True)
        logger.info(f"Saved to {output_file}")
    except Exception as e:
        logger.error(f"Failed to fetch data: {e}")
        raise

if __name__ == "__main__":
    fetch_sample_data()
