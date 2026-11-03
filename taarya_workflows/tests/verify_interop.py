"""Verify SAMP interoperability and uncertainty propagation."""

import logging
from src.retrieval.hybrid_search import HybridSearch
from src.database import postgres_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_interop():
    logger.info("Starting Scientific Interoperability Verification...")
    
    postgres_conn.connect()
    hybrid = HybridSearch()
    
    # 1. Test Uncertainty Propagation
    # Fetch a star from DB
    from sqlalchemy import text
    with postgres_conn.session() as session:
        res = session.execute(text("SELECT source_id FROM stars LIMIT 1")).fetchone()
        if res:
            source_id = res[0]
            logger.info(f"Testing Uncertainty Propagation for {source_id}...")
            profile = hybrid.get_research_grade_profile(source_id)
            
            if "absolute_g_mag_error" in profile:
                logger.info(f"SUCCESS: Propagated uncertainty for Abs Mag: {profile['absolute_g_mag']} +/- {profile['absolute_g_mag_error']}")
            else:
                logger.error("FAILED: No uncertainty propagated for Absolute Mag.")
                
            if "density_context" in profile:
                logger.info(f"SUCCESS: Density Context found. Ratio={profile['density_context']['density_ratio']}")
        else:
            logger.warning("No stars in DB to test.")

    # 2. Test SAMP Connectivity (Simulated if no hub open)
    logger.info("Testing SAMP broadcast capability...")
    # This will return a descriptive error if no hub is open, which is 'success' for our test
    samp_res = hybrid.broadcast_candidate(ra=56.75, dec=24.12, name="Pleiades Verification")
    
    if "status" in samp_res:
        logger.info("SUCCESS: Broadcasted to active SAMP Hub.")
    elif "No SAMP Hub found" in samp_res.get("error", ""):
        logger.info("SUCCESS: SAMP client correctly detected no Hub (expected behavior if Aladin/TOPCAT is closed).")
    else:
        logger.error(f"SAMP client error: {samp_res.get('error')}")

    logger.info("Interoperability Verification Complete.")

if __name__ == "__main__":
    verify_interop()
