"""Advanced scientific analysis for astronomical discovery."""

import math
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ScientificAnalysis:
    """
    Provides derived physical parameters and sensitivity analysis.
    Useful for "reasoning" about candidates in a research context.
    """

    @staticmethod
    def estimate_absolute_magnitude_with_error(g_mag: float, parallax_mas: float, g_mag_err: float = 0.01, parallax_err: float = 0.01) -> Dict[str, Any]:
        """
        Calculate absolute G magnitude with uncertainty propagation.
        M = m + 5 + 5 * log10(parallax/1000)
        Using Delta Method: sigma_M^2 = (dM/dm)^2 * sigma_m^2 + (dM/dpi)^2 * sigma_pi^2
        """
        if parallax_mas <= 0:
            return {"value": None, "error": None}
        
        try:
            m_abs = g_mag + 5 + 5 * math.log10(parallax_mas / 1000.0)
            
            # dM/dm = 1
            # dM/dpi = 5 / (pi * ln(10))
            term_m = g_mag_err ** 2
            term_pi = (5 / (parallax_mas * math.log(10))) ** 2 * (parallax_err ** 2)
            m_abs_err = math.sqrt(term_m + term_pi)
            
            return {"value": round(m_abs, 2), "error": round(m_abs_err, 3)}
        except (ValueError, OverflowError):
            return {"value": None, "error": None}

    @staticmethod
    def estimate_teff_with_error(teff: float, g_mag_err: float, bp_mag_err: float, rp_mag_err: float) -> Dict[str, Any]:
        """
        Propagate photometric errors into Teff uncertainty.
        Simplified model: sigma_Teff proportional to color uncertainty.
        """
        if teff is None: return {"value": None, "error": None}
        
        # Color uncertainty sigma_color = sqrt(sigma_bp^2 + sigma_rp^2)
        color_err = math.sqrt(bp_mag_err**2 + rp_mag_err**2)
        # Heuristic: 100K error per 0.01 mag in color
        teff_err = color_err * 10000.0
        
        return {"value": round(teff, 0), "error": round(teff_err, 0)}

    @staticmethod
    def estimate_binary_separation_limit(ruwe: float, parallax_mas: float) -> Optional[float]:
        """
        Estimate the possible angular separation of a binary companion
        that would cause the observed RUWE.
        Rough heuristic: Higher RUWE at larger parallax implies wider separation.
        """
        if ruwe <= 1.0 or parallax_mas <= 0:
            return 0.0
        # Heuristic: separation in AU proportional to (RUWE-1) * distance
        distance_pc = 1000.0 / parallax_mas
        return (ruwe - 1.0) * distance_pc * 0.5 # AU equivalent

    @staticmethod
    def physical_radius_limit(radius_deg: float, parallax_mas: float) -> Optional[float]:
        """
        Convert angular search radius to physical parsecs at the object's distance.
        """
        if parallax_mas <= 0:
            return None
        distance_pc = 1000.0 / parallax_mas
        radius_rad = math.radians(radius_deg)
        return radius_rad * distance_pc

    @staticmethod
    def classify_stellar_population(bp_rp: float, abs_g: float) -> str:
        """
        Rough classification based on HR diagram position.
        """
        if abs_g < 3 and bp_rp < 0.8:
            return "Main Sequence (O/B/A)"
        if abs_g < 1 and bp_rp > 1.2:
            return "Giant Branch"
        if abs_g > 10:
            return "White Dwarf Candidate"
        if bp_rp > 2.5:
            return "M-Dwarf / Low Mass"
        return "Main Sequence"
