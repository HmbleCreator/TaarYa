"""MESA Profile exporter for stellar evolution modeling."""

import logging
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

ABSOLUTE_MAG_FORMULA = "M_G = G + 5 + 5*log10(plx/1000)"
STRICT_MOTION_THRESHOLD_MAS_P_YR = 80.0


class TaarYaMESA:
    """
    Exports TaarYa discovery data into MESA-compatible configuration files (.inlist).
    Allows researchers to immediately simulate the life-cycle of a discovered star.
    """

    @staticmethod
    def _bp_rp_from_star(star: Dict[str, Any]) -> Optional[float]:
        bp = star.get("phot_bp_mean_mag")
        rp = star.get("phot_rp_mean_mag")
        if bp is not None and rp is not None:
            try:
                return float(bp) - float(rp)
            except (TypeError, ValueError):
                pass
        return None

    @staticmethod
    def _parallax_mas_from_star(star: Dict[str, Any]) -> Optional[float]:
        plx = star.get("parallax")
        if plx is not None:
            try:
                return float(plx)
            except (TypeError, ValueError):
                pass
        return None

    @classmethod
    def _absolute_mag_g(cls, star: Dict[str, Any]) -> Optional[float]:
        """Compute M_G = G + 5 + 5*log10(plx/1000)."""
        g = star.get("phot_g_mean_mag")
        plx = cls._parallax_mas_from_star(star)
        if g is not None and plx is not None and plx > 0:
            return float(g) + 5.0 + 5.0 * np.log10(plx / 1000.0)
        return None

    @classmethod
    def _hr_mass_estimate(cls, bp_rp: float, abs_mag_g: float) -> float:
        """
        Rough initial-mass estimate from HR-diagram position.

        Uses empirical main-sequence mass-luminosity relations for:
          - O/B stars (bp_rp < 0): massive MS stars, 2.2–18 M_sun
          - A/F stars (0 ≤ bp_rp < 0.6): intermediate mass
          - G/K stars (0.6 ≤ bp_rp < 1.4): solar-like
          - M dwarfs (bp_rp ≥ 1.4): low-mass
        """
        if bp_rp < -0.2:
            log_m = 0.25 * abs_mag_g - 1.5
        elif bp_rp < 0.0:
            log_m = 0.17 * abs_mag_g - 0.9
        elif bp_rp < 0.6:
            log_m = 0.27 * abs_mag_g - 1.3
        elif bp_rp < 1.4:
            log_m = 0.25 * abs_mag_g - 1.0
        else:
            log_m = 0.2 * abs_mag_g - 0.5
        mass = 10.0 ** log_m
        return round(max(0.08, min(mass, 20.0)), 2)

    @classmethod
    def _teff_from_bp_rp(cls, bp_rp: float) -> float:
        """Approximate effective temperature from BP-RP color (Stefan-Boltzmann / empirical)."""
        if bp_rp <= -0.1:
            return 20000.0
        if bp_rp < 0.2:
            return 9200.0 - 7000.0 * (bp_rp + 0.1) / 0.3
        if bp_rp < 0.6:
            return 7200.0 - 2000.0 * (bp_rp - 0.2) / 0.4
        if bp_rp < 1.2:
            return 5800.0 - 1800.0 * (bp_rp - 0.6) / 0.6
        if bp_rp < 2.1:
            return 4200.0 - 1600.0 * (bp_rp - 1.2) / 0.9
        return 3000.0

    @classmethod
    def _log_g_from_mass(cls, mass: float) -> float:
        """Approximate log(g) from mass for main-sequence approximation (cgs)."""
        if mass >= 2.5:
            return 4.0
        if mass >= 1.2:
            return 4.3
        if mass >= 0.8:
            return 4.4
        return 4.6

    @classmethod
    def estimate_physical_params(cls, star: Dict[str, Any]) -> Dict[str, Any]:
        """
        Estimate full physical parameter set from available photometry.

        Returns dict with: initial_mass, log_g, teff_K, initial_z, bp_rp, abs_mag_g.
        Falls back to heuristic chains when full data unavailable.
        """
        bp_rp = cls._bp_rp_from_star(star)
        abs_mag_g = cls._absolute_mag_g(star)
        catalog_source = str(star.get("catalog_source", "")).upper()

        if bp_rp is not None and abs_mag_g is not None:
            teff = cls._teff_from_bp_rp(bp_rp)
            mass = cls._hr_mass_estimate(bp_rp, abs_mag_g)
        else:
            mass = cls._estimate_initial_mass(star)
            teff = float(star.get("teff_estimated_k", 5778) or 5778)

        log_g = cls._log_g_from_mass(mass)

        if "SMC" in catalog_source:
            z = 0.004
        elif "LMC" in catalog_source:
            z = 0.008
        else:
            z = 0.02

        ruwe = star.get("ruwe")
        high_motion = float(star.get("total_proper_motion_mas_yr", 0)) > STRICT_MOTION_THRESHOLD_MAS_P_YR

        return {
            "initial_mass": mass,
            "log_g": log_g,
            "teff_K": round(teff, 0),
            "initial_z": z,
            "bp_rp": round(bp_rp, 4) if bp_rp is not None else None,
            "abs_mag_g": round(abs_mag_g, 3) if abs_mag_g is not None else None,
            "ruwe": float(ruwe) if ruwe is not None else None,
            "high_motion": high_motion,
            "mass_estimation_method": "hr_diagram" if (bp_rp is not None and abs_mag_g is not None) else "photometry_heuristic",
            "absolute_mag_formula": ABSOLUTE_MAG_FORMULA,
        }

    @staticmethod
    def _estimate_initial_mass(star: Dict[str, Any]) -> float:
        """Estimate a conservative initial mass from available photometry."""
        teff = star.get("teff_estimated_k")
        if teff is not None:
            teff = float(teff)
            if teff >= 9000:
                return 2.2
            if teff >= 7500:
                return 1.7
            if teff >= 6000:
                return 1.15
            if teff >= 5000:
                return 0.95
            return 0.75

        bp = star.get("phot_bp_mean_mag")
        rp = star.get("phot_rp_mean_mag")
        if bp is not None and rp is not None:
            color = float(bp) - float(rp)
            if color <= 0.0:
                return 1.8
            if color <= 0.6:
                return 1.2
            if color <= 1.4:
                return 0.95
            return 0.75

        return 1.0

    @staticmethod
    def _estimate_initial_z(star: Dict[str, Any]) -> float:
        """Estimate a reasonable metallicity prior from catalog provenance."""
        catalog_source = str(star.get("catalog_source", "")).upper()
        if "SMC" in catalog_source:
            return 0.004
        if "LMC" in catalog_source:
            return 0.008
        return 0.02

    @classmethod
    def build_inlist(cls, star: Dict[str, Any], use_hr_diagram: bool = True) -> str:
        """Build a MESA inlist from Gaia-derived parameters."""
        source_id = star.get("source_id", "unknown")

        if use_hr_diagram:
            params = cls.estimate_physical_params(star)
        else:
            params = {
                "initial_mass": cls._estimate_initial_mass(star),
                "initial_z": cls._estimate_initial_z(star),
                "teff_K": float(star.get("teff_estimated_k", 5778) or 5778),
            }

        teff = params.get("teff_K", 5778)
        mass = params["initial_mass"]
        z = params["initial_z"]
        log_g = params.get("log_g")
        bp_rp = params.get("bp_rp")
        abs_mag_g = params.get("abs_mag_g")
        method = params.get("mass_estimation_method", "photometry_heuristic")

        comments = [
            f"! Generated by TaarYa for Gaia source_id {source_id}",
            f"! Physical params: M={mass:.2f} M_sun, Teff={teff:.0f} K, Z={z:.4f}",
        ]
        if log_g is not None:
            comments.append(f"! log(g)={log_g:.1f} [estimated]")
        if bp_rp is not None and abs_mag_g is not None:
            comments.append(f"! BP-RP={bp_rp:.4f}, M_G={abs_mag_g:.3f} (M_G = G + 5 + 5*log10(plx/1000))")
        comments.append(f"! Mass estimation: {method}")

        inlist = (
            "&star_job\n"
            "  create_pre_main_sequence_model = .true.\n"
            "/\n\n"
            "&controls\n"
            f"  initial_mass = {mass:.2f}\n"
            f"  initial_z = {z:.4f}\n"
            f"  initial_Teff = {teff:.0f}\n"
        )
        if log_g is not None:
            inlist += f"  initial_log_g = {log_g:.1f}\n"
        inlist += (
            "  max_age = 1d10\n"
            "  history_interval = 10\n"
            "  profile_interval = 50\n"
            "  terminal_interval = 10\n"
            "  write_profiles_flag = .true.\n"
            "/\n\n"
            + "\n".join(comments)
            + "\n"
        )
        return inlist

    @classmethod
    def generate_inlist(
        cls,
        star: Dict[str, Any],
        output_path: str = "star.inlist",
        use_hr_diagram: bool = True,
    ):
        """Persist a generated MESA inlist to disk."""
        try:
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write(cls.build_inlist(star, use_hr_diagram=use_hr_diagram))
            return {"status": f"MESA inlist generated at {output_path}"}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def build_cluster_inlist(cls, members: List[Dict[str, Any]], cluster_name: str) -> str:
        """
        Build a single MESA inlist representing an isochrone cluster approximation.

        Uses the median HR-diagram position of the member stars to set bulk parameters.
        Useful for cluster evolution runs.
        """
        if not members:
            return "! No members provided for cluster inlist generation"

        bp_rp_vals = []
        abs_mag_vals = []
        for m in members:
            bp_rp = cls._bp_rp_from_star(m)
            abs_m = cls._absolute_mag_g(m)
            if bp_rp is not None:
                bp_rp_vals.append(bp_rp)
            if abs_m is not None:
                abs_mag_vals.append(abs_m)

        median_bp_rp = float(np.median(bp_rp_vals)) if bp_rp_vals else 0.5
        median_abs_mag = float(np.median(abs_mag_vals)) if abs_mag_vals else 4.7
        median_mass = cls._hr_mass_estimate(median_bp_rp, median_abs_mag)
        median_teff = cls._teff_from_bp_rp(median_bp_rp)
        median_log_g = cls._log_g_from_mass(median_mass)

        comment = (
            f"! Cluster inlist for {cluster_name}\n"
            f"! Members: {len(members)}  |  Median BP-RP: {median_bp_rp:.4f}\n"
            f"! M_G = G + 5 + 5*log10(plx/1000) | Median M_G: {median_abs_mag:.3f}\n"
            f"! Median initial mass: {median_mass:.2f} M_sun, Teff: {median_teff:.0f} K\n"
        )
        return (
            "&star_job\n"
            "  create_pre_main_sequence_model = .true.\n"
            "/\n\n"
            "&controls\n"
            f"  initial_mass = {median_mass:.2f}\n"
            f"  initial_z = 0.02\n"
            f"  initial_Teff = {median_teff:.0f}\n"
            f"  initial_log_g = {median_log_g:.1f}\n"
            "  max_age = 1d10\n"
            "  history_interval = 10\n"
            "  profile_interval = 50\n"
            "/\n\n"
            + comment
        )
