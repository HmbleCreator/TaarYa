"""Multi-Wavelength Spectral Energy Distribution (SED) Analysis."""

import logging
from typing import Dict, Any, List, Optional
import numpy as np

logger = logging.getLogger(__name__)

class SEDFitter:
    """
    Fits multi-wavelength flux data (Gaia, 2MASS, AllWISE) to 
    determine effective temperature and stellar parameters.
    """

    # Filter wavelengths in microns
    WAVELENGTHS = {
        "phot_g_mean_mag": 0.673,
        "phot_bp_mean_mag": 0.532,
        "phot_rp_mean_mag": 0.797,
        "Jmag": 1.235,
        "Hmag": 1.662,
        "Kmag": 2.159,
        "W1mag": 3.352,
        "W2mag": 4.603
    }

    def _mag_to_flux(self, mag: float, filter_name: str) -> Optional[float]:
        """Convert magnitude to flux (Jy)."""
        # Very rough zero points for quick fitting
        zero_points = {
            "phot_g_mean_mag": 3228.75,
            "phot_bp_mean_mag": 3552.01,
            "phot_rp_mean_mag": 2554.95,
            "Jmag": 1594,
            "Hmag": 1024,
            "Kmag": 666.7,
            "W1mag": 309.54,
            "W2mag": 171.78
        }
        if filter_name not in zero_points or mag is None:
            return None
        return zero_points[filter_name] * (10**(-0.4 * mag))

    def compute_sed(self, star: Dict[str, Any], vizier_matches: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Build an SED from available Gaia and VizieR photometry.
        """
        flux_points = []
        
        # 1. Gaia points
        for filter_name in ["phot_g_mean_mag", "phot_bp_mean_mag", "phot_rp_mean_mag"]:
            mag = star.get(filter_name)
            flux = self._mag_to_flux(mag, filter_name)
            if flux:
                flux_points.append({
                    "filter": filter_name,
                    "wavelength_um": self.WAVELENGTHS[filter_name],
                    "flux_jy": round(flux, 4),
                    "mag": mag
                })

        # 2. 2MASS points
        if "2MASS" in vizier_matches and vizier_matches["2MASS"]:
            m = vizier_matches["2MASS"][0]
            for f in ["Jmag", "Hmag", "Kmag"]:
                mag = m.get(f)
                flux = self._mag_to_flux(mag, f)
                if flux:
                    flux_points.append({
                        "filter": f"2MASS_{f}",
                        "wavelength_um": self.WAVELENGTHS[f],
                        "flux_jy": round(flux, 4),
                        "mag": mag
                    })

        # 3. AllWISE points
        if "AllWISE" in vizier_matches and vizier_matches["AllWISE"]:
            m = vizier_matches["AllWISE"][0]
            for f in ["W1mag", "W2mag"]:
                mag = m.get(f)
                flux = self._mag_to_flux(mag, f)
                if flux:
                    flux_points.append({
                        "filter": f"AllWISE_{f}",
                        "wavelength_um": self.WAVELENGTHS[f],
                        "flux_jy": round(flux, 4),
                        "mag": mag
                    })

        return sorted(flux_points, key=lambda x: x["wavelength_um"])

    def estimate_teff_from_sed(self, flux_points: List[Dict[str, Any]]) -> Optional[float]:
        """
        Rough Teff estimation from the peak wavelength (Wien's Law fallback).
        Real fitting would use an ATLAS9/Phoenix model grid.
        """
        if not flux_points:
            return None
            
        # Very simple estimate based on G-band and J-band slope
        # This is a placeholder for a real fitting routine
        peak_idx = np.argmax([p["flux_jy"] for p in flux_points])
        peak_wl = flux_points[peak_idx]["wavelength_um"]
        
        # Wien's Displacement Law: b / lambda_max (lambda in microns)
        # b = 2898 um*K
        teff = 2898.0 / peak_wl
        return round(float(teff), 0)
