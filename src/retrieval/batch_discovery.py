"""Advanced batch discovery engine for scientific research."""

import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from src.database import postgres_conn

logger = logging.getLogger(__name__)

class BatchDiscoveryEngine:
    """
    Runs high-fidelity discovery queries across the entire ingested catalog.
    Supports SNR filtering, quality cuts, and kinematic anomaly detection.
    """

    def find_high_velocity_candidates(self, min_snr: float = 5.0, min_pm: float = 100.0, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Find runaway or hypervelocity star candidates.
        Filter by high proper motion and good astrometric quality.
        """
        query = text("""
            SELECT source_id, ra, dec, pmra, pmdec, phot_g_mean_mag, parallax, ruwe,
                   sqrt(pow(pmra, 2) + pow(pmdec, 2)) as total_pm
            FROM stars
            WHERE sqrt(pow(pmra, 2) + pow(pmdec, 2)) > :min_pm
              AND (parallax IS NULL OR parallax / parallax_error > :min_snr)
              AND phot_g_mean_mag < 16
            ORDER BY total_pm DESC
            LIMIT :limit
        """)
        
        with postgres_conn.session() as session:
            result = session.execute(query, {"min_pm": min_pm, "min_snr": min_snr, "limit": limit})
            return [dict(row) for row in result.mappings().all()]

    def find_binary_candidates(self, min_ruwe: float = 1.4, min_parallax: float = 5.0, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Find potential binary systems based on RUWE and proximity.
        """
        query = text("""
            SELECT source_id, ra, dec, parallax, ruwe, phot_g_mean_mag
            FROM stars
            WHERE ruwe > :min_ruwe
              AND parallax > :min_parallax
            ORDER BY ruwe DESC
            LIMIT :limit
        """)
        
        with postgres_conn.session() as session:
            result = session.execute(query, {"min_ruwe": min_ruwe, "min_parallax": min_parallax, "limit": limit})
            return [dict(row) for row in result.mappings().all()]

    def custom_scientific_query(self, sql_where: str, params: Dict[str, Any] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Allows researchers to run custom filtering logic (read-only).
        """
        # Basic SQL injection safety for where clause (extremely limited)
        forbidden = ["DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER"]
        if any(f in sql_where.upper() for f in forbidden):
            raise ValueError("Forbidden SQL keyword detected in custom query.")

        query = text(f"""
            SELECT * FROM stars
            WHERE {sql_where}
            LIMIT :limit
        """)
        
        with postgres_conn.session() as session:
            result = session.execute(query, {**(params or {}), "limit": limit})
            return [dict(row) for row in result.mappings().all()]
