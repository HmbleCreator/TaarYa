"""Verification of statistical rigor and interpretability."""

import logging
from src.retrieval.hybrid_search import HybridSearch
from src.database import postgres_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_rigor():
    logger.info("Starting Statistical Rigor Verification...")
    
    postgres_conn.connect()
    hybrid = HybridSearch()
    
    # Use Pleiades for testing
    ra, dec, radius = 56.75, 24.12, 0.5
    
    logger.info(f"Running multi-seed sweep at RA={ra}, Dec={dec}...")
    robust_stars = hybrid.get_statistically_robust_candidates(ra, dec, radius)
    
    if robust_stars:
        top = robust_stars[0]
        stat = top["robust_score"]
        logger.info(f"SUCCESS: Robust candidate found.")
        logger.info(f"Candidate: {top['source_id']}")
        logger.info(f"Mean Score: {stat['mean_score']} (std_dev: {stat['std_dev']})")
        logger.info(f"Confidence: {stat['confidence']}")
        logger.info(f"Top Feature: {list(stat['feature_importance'].keys())[0]}")
    else:
        logger.warning("No stars found for robust sweep.")

    # Test Alerts
    logger.info("Testing Gaia Science Alerts stream...")
    alerts = hybrid.alerts.fetch_latest_alerts(limit=5)
    if alerts:
        logger.info(f"SUCCESS: Fetched {len(alerts)} real-time alerts.")
        logger.info(f"Latest Alert: {alerts[0]['alert_name']} at RA={alerts[0]['ra']}")
    else:
        logger.error("FAILED to fetch Gaia alerts.")

    logger.info("Statistical Rigor Verification Complete.")

if __name__ == "__main__":
    verify_rigor()
