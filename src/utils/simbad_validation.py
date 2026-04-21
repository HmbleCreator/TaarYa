"""SIMBAD cross-registration and validation utilities.

SIMBAD is the gold-standard astronomical database managed by CDS, Strasbourg.
This module provides cross-registration capabilities to validate TaarYa results
against SIMBAD and enhance star records with SIMBAD identifiers.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_simbad = None


def _get_simbad():
    """Lazily initialize SIMBAD client."""
    global _simbad
    if _simbad is None:
        try:
            from astroquery.simbad import Simbad
            _simbad = Simbad
            logger.info("SIMBAD client initialized")
        except ImportError:
            logger.warning("astroquery not available, SIMBAD cross-registration disabled")
            return None
    return _simbad


def query_simbad_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Query SIMBAD for an object by name.

    Args:
        name: Common name of the object (e.g., "Betelgeuse", "M31")

    Returns:
        Matching SIMBAD object with main identifier and coordinates, or None
    """
    Simbad = _get_simbad()
    if Simbad is None:
        return None

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = Simbad.query_object(name)

        if result is None or len(result) == 0:
            return None

        row = result[0]
        obj = {}
        for col in result.colnames:
            try:
                # result RA/DEC are often strings like "05 55 10.3053"
                obj[col.lower()] = str(row[col])
            except Exception:
                pass
        
        logger.info(f"SIMBAD found object '{name}' at RA={obj.get('ra')}, Dec={obj.get('dec')}")
        return obj

    except Exception as e:
        logger.error(f"SIMBAD name query failed for '{name}': {e}")
        return None


def query_simbad_by_coords(
    ra: float, dec: float, radius_arcsec: float = 5.0
) -> List[Dict[str, Any]]:
    """Query SIMBAD for objects near given coordinates.

    Args:
        ra: Right Ascension in degrees
        dec: Declination in degrees
        radius_arcsec: Search radius in arcseconds (default 5")

    Returns:
        List of matching SIMBAD objects with identifiers and types
    """
    Simbad = _get_simbad()
    if Simbad is None:
        return []

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = Simbad.query_region(
                f"{ra} {dec}",
                radius=f"{radius_arcsec}s",
            )

        if result is None or len(result) == 0:
            return []

        objects = []
        columns = result.colnames

        for row in result:
            obj = {}
            for col in columns:
                try:
                    obj[col.lower()] = row[col]
                except Exception:
                    pass
            objects.append(obj)

        logger.info(f"SIMBAD found {len(objects)} objects near RA={ra}, Dec={dec}")
        return objects

    except Exception as e:
        logger.error(f"SIMBAD query failed: {e}")
        return []


def validate_star_in_simbad(source_id: str, ra: float, dec: float, radius_arcsec: float = 10.0) -> Optional[Dict[str, Any]]:
    """Validate a Gaia source against SIMBAD by coordinates.

    Args:
        source_id: Gaia DR3 source ID
        ra: Right Ascension in degrees
        dec: Declination in degrees
        radius_arcsec: Search radius in arcseconds (default 10")

    Returns:
        SIMBAD validation result with matching info, or None if not found
    """
    matches = query_simbad_by_coords(ra, dec, radius_arcsec=radius_arcsec)

    if not matches:
        return {
            "source_id": source_id,
            "validated": False,
            "simbad_id": None,
            "otype": None,
            "note": "No SIMBAD counterpart within 10 arcsec"
        }

    best_match = matches[0]
    return {
        "source_id": source_id,
        "validated": True,
        "simbad_id": str(best_match.get("main_id", "")),
        "otype": str(best_match.get("otype", "")) if best_match.get("otype") else None,
        "note": f"Matched to SIMBAD object: {best_match.get('main_id', 'unknown')}"
    }


def cross_register_stars(stars: List[Dict], radius_arcsec: float = 5.0) -> List[Dict]:
    """Cross-register a list of stars against SIMBAD.

    Args:
        stars: List of star dictionaries with source_id, ra, dec
        radius_arcsec: Search radius for matching

    Returns:
        Same stars list with SIMBAD validation info added
    """
    validated = 0
    for star in stars:
        simbad_info = validate_star_in_simbad(
            star.get("source_id", ""),
            star.get("ra", 0),
            star.get("dec", 0),
            radius_arcsec=radius_arcsec
        )
        if simbad_info:
            star["simbad_validated"] = simbad_info["validated"]
            star["simbad_id"] = simbad_info.get("simbad_id")
            star["simbad_otype"] = simbad_info.get("otype")
            if simbad_info["validated"]:
                validated += 1

    logger.info(f"SIMBAD cross-registration: {validated}/{len(stars)} stars validated")
    return stars


def get_otype_distribution(stars: List[Dict]) -> Dict[str, int]:
    """Get distribution of SIMBAD object types in a star list.

    Args:
        stars: List of stars with SIMBAD cross-registration data

    Returns:
        Dictionary mapping object type to count
    """
    distribution = {}
    for star in stars:
        otype = star.get("simbad_otype", "Unknown")
        if not otype:
            otype = "Unknown"
        distribution[otype] = distribution.get(otype, 0) + 1
    return distribution


def filter_by_otype(stars: List[Dict], include_types: List[str], exclude_types: List[str] = None) -> List[Dict]:
    """Filter stars by SIMBAD object type.

    Args:
        stars: List of stars with SIMBAD data
        include_types: List of object types to include (e.g., ["Star", "Brown_Dwarf"])
        exclude_types: List of object types to exclude (e.g., ["Galaxy", "QSO"])

    Returns:
        Filtered star list
    """
    exclude_types = exclude_types or []
    filtered = []

    for star in stars:
        otype = str(star.get("simbad_otype", ""))

        if not star.get("simbad_validated", False):
            continue

        if include_types and otype not in include_types:
            continue

        if exclude_types and otype in exclude_types:
            continue

        filtered.append(star)

    return filtered
