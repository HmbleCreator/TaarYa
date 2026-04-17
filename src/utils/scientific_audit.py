"""Scientific audit and discovery verification."""

import logging
from typing import List, Dict, Any
from src.retrieval.hybrid_search import HybridSearch
from src.utils.simbad_validation import validate_star_in_simbad

from src.database import neo4j_conn, postgres_conn, qdrant_conn

logger = logging.getLogger(__name__)

def init_connections():
    postgres_conn.connect()
    qdrant_conn.connect()
    neo4j_conn.connect()

class ScientificAudit:
    """Audits the TaarYa system for scientific robustness."""
    
    def __init__(self):
        self.hybrid = HybridSearch()

    def run_discovery_audit(self, ra: float, dec: float, radius: float = 1.0) -> Dict[str, Any]:
        """Verify discovery candidates against SIMBAD."""
        logger.info(f"Running discovery audit at RA={ra}, Dec={dec}...")
        
        # 1. Get TaarYa candidates
        taarya_res = self.hybrid.cone_search_with_context(ra, dec, radius)
        stars = taarya_res.get("stars", [])
        
        # 2. Filter high-scoring candidates
        candidates = [s for s in stars if s.get("discovery_score", 0) > 10.0]
        
        # 3. Validate against SIMBAD
        validated = []
        for c in candidates:
            simbad_res = validate_star_in_simbad(c["source_id"], ra=c["ra"], dec=c["dec"])
            if simbad_res:
                validated.append({
                    "source_id": c["source_id"],
                    "taarya_score": c["discovery_score"],
                    "taarya_reasons": c["discovery_reasons"],
                    "simbad_match": simbad_res["validated"],
                    "simbad_otype": simbad_res.get("otype", "Unknown"),
                    "status": "Verified" if simbad_res["validated"] else "New Discovery Candidate"
                })
            
        return {
            "total_stars": len(stars),
            "candidates_found": len(candidates),
            "validated_candidates": validated,
            "system_health": "Scientifically Robust" if len(validated) > 0 else "Pending Calibrated Data"
        }

if __name__ == "__main__":
    init_connections()
    audit = ScientificAudit()
    res = audit.run_discovery_audit(66.75, 15.87, 2.0)
    print(res)
