"""VizieR cross-matching for multi-wavelength research."""

import logging
from typing import List, Dict, Any
from astroquery.vizier import Vizier
import astropy.units as u
from astropy.coordinates import SkyCoord

logger = logging.getLogger(__name__)

class VizierCrossMatch:
    """
    Cross-matches TaarYa candidates with major catalogs on VizieR.
    Supports 2MASS (Infrared), AllWISE (Mid-IR), and Chandra (X-ray).
    """

    def __init__(self):
        # Configure Vizier to return all columns and be reasonably fast
        self.vizier = Vizier(columns=["*"], row_limit=5)

    def cross_match_object(self, ra: float, dec: float, radius_arcsec: float = 2.0) -> Dict[str, Any]:
        """
        Cross-match a single position with major research catalogs.
        """
        coord = SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame='icrs')
        results = {}

        catalogs = {
            "2MASS": "II/246/out",
            "AllWISE": "II/328/allwise",
            "Chandra": "IX/57/csc2pc",
            "GALEX": "II/312/ais"
        }

        for name, vizier_id in catalogs.items():
            try:
                res = self.vizier.query_region(coord, radius=radius_arcsec*u.arcsec, catalog=vizier_id)
                if res and len(res) > 0:
                    # Convert Table to list of dicts
                    results[name] = [dict(row) for row in res[0]]
                else:
                    results[name] = []
            except Exception as e:
                logger.warning(f"Vizier query for {name} failed: {e}")
                results[name] = []

        return results

    def batch_cross_match(self, stars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run cross-matching for a batch of stars."""
        for star in stars:
            star["vizier_matches"] = self.cross_match_object(star["ra"], star["dec"])
        return stars
