"""Scientific orchestrator for coordinate systems, units, and provenance."""

import logging
from typing import Dict, Any, Tuple, Optional
from astropy import units as u
from astropy.coordinates import SkyCoord
import datetime

logger = logging.getLogger(__name__)

class ScientificOrchestrator:
    """
    Handles coordinate conversions, unit safety, and research provenance.
    Ensures TaarYa meets professional astronomical standards.
    """

    @staticmethod
    def parse_coordinates(ra: Any, dec: Any, frame: str = "icrs") -> Tuple[float, float]:
        """
        Convert coordinates from any frame (ICRS, Galactic, Ecliptic) to ICRS deg.
        
        Args:
            ra: Right Ascension or Longitude (deg)
            dec: Declination or Latitude (deg)
            frame: Coordinate frame ('icrs', 'galactic', 'fk5')
            
        Returns:
            Tuple of (ra_deg, dec_deg) in ICRS
        """
        try:
            if frame.lower() == "galactic":
                c = SkyCoord(l=ra*u.degree, b=dec*u.degree, frame='galactic')
                icrs = c.icrs
                return icrs.ra.degree, icrs.dec.degree
            elif frame.lower() == "icrs":
                return float(ra), float(dec)
            else:
                c = SkyCoord(ra=ra*u.degree, dec=dec*u.degree, frame=frame.lower())
                icrs = c.icrs
                return icrs.ra.degree, icrs.dec.degree
        except Exception as e:
            logger.error(f"Coordinate conversion failed: {e}")
            return float(ra), float(dec)

    @staticmethod
    def parse_radius(radius: float, unit: str = "deg") -> float:
        """
        Normalize search radius to degrees.
        
        Args:
            radius: Value of the radius
            unit: 'deg', 'arcmin', or 'arcsec'
            
        Returns:
            Radius in degrees
        """
        try:
            if unit == "arcmin":
                return (radius * u.arcmin).to(u.deg).value
            elif unit == "arcsec":
                return (radius * u.arcsec).to(u.deg).value
            return float(radius)
        except Exception as e:
            logger.error(f"Radius conversion failed: {e}")
            return float(radius)

    @staticmethod
    def create_provenance(query_type: str, params: Dict[str, Any], raw_query: str) -> Dict[str, Any]:
        """
        Create a provenance record for reproducibility.
        """
        return {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "query_type": query_type,
            "parameters": params,
            "raw_query": raw_query,
            "system_version": "TaarYa-v0.2.0-scientific",
            "reference_catalog": "Gaia DR3"
        }

    @staticmethod
    def format_star_with_units(star: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich star record with explicit unit metadata for export.
        """
        star["_units"] = {
            "ra": "deg",
            "dec": "deg",
            "parallax": "mas",
            "pmra": "mas/yr",
            "pmdec": "mas/yr",
            "phot_g_mean_mag": "mag",
            "ruwe": "dimensionless"
        }
        return star
