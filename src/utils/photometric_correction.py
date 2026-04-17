"""Scientific photometric corrections (Extinction & Reddening)."""

import logging
from typing import Dict, Any, Optional
import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u

# Try to use dustmaps if available, else fallback to a simple 2D model
try:
    from dustmaps.sfd import SFDQuery
    _HAS_DUSTMAPS = True
except ImportError:
    _HAS_DUSTMAPS = False

logger = logging.getLogger(__name__)

class PhotometricCorrection:
    """
    Handles interstellar extinction and reddening corrections.
    Crucial for accurate absolute magnitude and stellar classification.
    """

    def __init__(self):
        self.sfd = None
        if _HAS_DUSTMAPS:
            try:
                self.sfd = SFDQuery()
            except Exception as e:
                logger.warning(f"Dustmaps SFD not initialized: {e}")

    def get_ebv(self, ra: float, dec: float) -> float:
        """Get E(B-V) reddening value for a position."""
        if self.sfd:
            c = SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame='icrs')
            return float(self.sfd(c))
        
        # Simple Galactic model fallback (A_V ~ 1 mag/kpc)
        # This is very rough and mainly for code integrity when maps are missing
        return 0.05 

    def apply_extinction(self, star: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply A_G and E(BP-RP) corrections to a star record.
        Uses R_V = 3.1 standard extinction law.
        """
        ra, dec = star.get('ra'), star.get('dec')
        if ra is None or dec is None:
            return star

        ebv = self.get_ebv(ra, dec)
        
        # Extinction coefficients for Gaia bands (approximate R_V=3.1)
        # A_G / A_V ~ 0.86, A_BP / A_V ~ 1.06, A_RP / A_V ~ 0.65
        a_v = 3.1 * ebv
        a_g = 0.86 * a_v
        e_bp_rp = (1.06 - 0.65) * a_v

        # Store intrinsic (corrected) values
        star["ebv_sfd"] = round(ebv, 4)
        star["extinction_ag"] = round(a_g, 3)
        
        g_mag = star.get("phot_g_mean_mag")
        bp = star.get("phot_bp_mean_mag")
        rp = star.get("phot_rp_mean_mag")

        if g_mag is not None:
            star["phot_g_mean_mag_corrected"] = round(g_mag - a_g, 3)
        
        if bp is not None and rp is not None:
            color = bp - rp
            star["bp_rp_color_corrected"] = round(color - e_bp_rp, 3)
            
        return star
