"""Spatial search using PostgreSQL Q3C extension."""
import logging
from typing import List, Optional, Dict, Any

from sqlalchemy import text

from src.database import postgres_conn
from src.models import Star

logger = logging.getLogger(__name__)


class SpatialSearch:
    """Q3C-powered spatial queries on the stars catalog."""
    
    def cone_search(
        self,
        ra: float,
        dec: float,
        radius_deg: float,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Find all stars within a cone around given coordinates.
        
        Args:
            ra: Right Ascension in degrees (0-360)
            dec: Declination in degrees (-90 to 90)
            radius_deg: Search radius in degrees
            limit: Maximum number of results
            
        Returns:
            List of star records as dictionaries
        """
        logger.info(f"Cone search: RA={ra}, Dec={dec}, radius={radius_deg}°")
        
        postgres_conn.connect()
        
        query = text("""
            SELECT source_id, ra, dec, parallax, pmra, pmdec,
                   phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag,
                   catalog_source,
                   q3c_dist(ra, dec, :center_ra, :center_dec) AS angular_distance
            FROM stars
            WHERE q3c_radial_query(ra, dec, :center_ra, :center_dec, :radius)
            ORDER BY angular_distance
            LIMIT :limit
        """)
        
        with postgres_conn.session() as session:
            result = session.execute(query, {
                "center_ra": ra,
                "center_dec": dec,
                "radius": radius_deg,
                "limit": limit
            })
            
            rows = result.mappings().all()
            stars = [dict(row) for row in rows]
            
        logger.info(f"Found {len(stars)} stars in cone")
        return stars
    
    def radial_search(
        self,
        ra: float,
        dec: float,
        radius_deg: float,
        mag_limit: Optional[float] = None,
        min_parallax: Optional[float] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Cone search with optional magnitude and parallax filters.
        
        Args:
            ra: Right Ascension in degrees
            dec: Declination in degrees
            radius_deg: Search radius in degrees
            mag_limit: Maximum G-band magnitude (fainter limit)
            min_parallax: Minimum parallax in mas (distance filter)
            limit: Maximum results
            
        Returns:
            Filtered list of star records
        """
        conditions = ["q3c_radial_query(ra, dec, :center_ra, :center_dec, :radius)"]
        params = {
            "center_ra": ra,
            "center_dec": dec,
            "radius": radius_deg,
            "limit": limit
        }
        
        if mag_limit is not None:
            conditions.append("phot_g_mean_mag <= :mag_limit")
            params["mag_limit"] = mag_limit
        
        if min_parallax is not None:
            conditions.append("parallax >= :min_parallax")
            params["min_parallax"] = min_parallax
        
        where_clause = " AND ".join(conditions)
        
        query = text(f"""
            SELECT source_id, ra, dec, parallax, pmra, pmdec,
                   phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag,
                   catalog_source,
                   q3c_dist(ra, dec, :center_ra, :center_dec) AS angular_distance
            FROM stars
            WHERE {where_clause}
            ORDER BY angular_distance
            LIMIT :limit
        """)
        
        postgres_conn.connect()
        
        with postgres_conn.session() as session:
            result = session.execute(query, params)
            rows = result.mappings().all()
            stars = [dict(row) for row in rows]
        
        logger.info(f"Radial search: {len(stars)} stars (mag<={mag_limit}, plx>={min_parallax})")
        return stars
    
    def coordinate_lookup(self, source_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single star by its Gaia source ID.
        
        Args:
            source_id: Gaia DR3 source identifier
            
        Returns:
            Star record or None if not found
        """
        postgres_conn.connect()
        
        with postgres_conn.session() as session:
            star = session.query(Star).filter(
                Star.source_id == source_id
            ).first()
            
            if star is None:
                return None
            
            return {
                "source_id": star.source_id,
                "ra": star.ra,
                "dec": star.dec,
                "parallax": star.parallax,
                "pmra": star.pmra,
                "pmdec": star.pmdec,
                "phot_g_mean_mag": star.phot_g_mean_mag,
                "phot_bp_mean_mag": star.phot_bp_mean_mag,
                "phot_rp_mean_mag": star.phot_rp_mean_mag,
                "catalog_source": star.catalog_source,
            }
    
    def nearby_stars(
        self,
        source_id: str,
        radius_deg: float = 0.1,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Find stars near a known star.
        
        Args:
            source_id: Source star's Gaia ID
            radius_deg: Search radius in degrees
            limit: Maximum results
            
        Returns:
            List of nearby stars (excluding the source star)
        """
        star = self.coordinate_lookup(source_id)
        if star is None:
            logger.warning(f"Star {source_id} not found")
            return []
        
        results = self.cone_search(
            ra=star["ra"],
            dec=star["dec"],
            radius_deg=radius_deg,
            limit=limit + 1  # +1 to exclude self
        )
        
        # Remove the source star from results
        return [s for s in results if s["source_id"] != source_id][:limit]
    
    def count_in_region(self, ra: float, dec: float, radius_deg: float) -> int:
        """Count stars in a region without returning data."""
        postgres_conn.connect()
        
        query = text("""
            SELECT COUNT(*) as cnt
            FROM stars
            WHERE q3c_radial_query(ra, dec, :ra, :dec, :radius)
        """)
        
        with postgres_conn.session() as session:
            result = session.execute(query, {
                "ra": ra, "dec": dec, "radius": radius_deg
            })
            return result.scalar()
