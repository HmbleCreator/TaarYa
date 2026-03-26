"""Shared Gaia TAP query helper for region ingestion."""

import logging
import socket
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

_gaia = None  # Lazily initialised to avoid slow Gaia archive contact at import time


def _get_gaia():
    """Return the configured Gaia client, initialising it on first use."""
    global _gaia
    if _gaia is None:
        from astroquery.gaia import Gaia  # noqa: PLC0415 – intentional lazy import

        Gaia.ROW_LIMIT = 2000
        Gaia.MAIN_GAIA_TABLE = "gaiadr3.gaia_source"
        Gaia.TIMEOUT = 30
        _gaia = Gaia
    return _gaia


def query_gaia_region(
    ra: float, dec: float, radius_deg: float, max_stars: int = 5000, offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Query Gaia DR3 for stars in a circular sky region.

    Args:
        ra: Right Ascension in degrees
        dec: Declination in degrees
        radius_deg: Search radius in degrees
        max_stars: Maximum number of stars to return (default 5000)
        offset: Number of rows to skip (for pagination)

    Returns:
        List of star dictionaries with keys:
        source_id, ra, dec, parallax, pmra, pmdec, phot_g_mean_mag,
        phot_bp_mean_mag, phot_rp_mean_mag, ruwe
    """
    gaia_query = f"""
        SELECT TOP {max_stars + offset}
            source_id, ra, dec, parallax, pmra, pmdec,
            phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, ruwe
        FROM gaiadr3.gaia_source
        WHERE CONTAINS(
            POINT('ICRS', ra, dec),
            CIRCLE('ICRS', {ra}, {dec}, {radius_deg})
        ) = 1
          AND parallax > 0
          AND phot_g_mean_mag < 18
    """

    Gaia = _get_gaia()  # lazy init – contacts Gaia archive only on first real query
    try:
        logger.info(
            f"Querying Gaia for region: RA={ra}, Dec={dec}, radius={radius_deg}°"
        )
        job = Gaia.launch_job(gaia_query, verbose=False)
        table = job.get_results()
        logger.info(f"Gaia returned {len(table)} results")
    except (socket.timeout, TimeoutError, OSError, Exception) as e:
        logger.warning(f"Gaia query failed: {e}")
        raise

    rows = []
    for i, record in enumerate(table):
        # Skip offset rows
        if offset > 0 and i < offset:
            continue
        try:
            source_id = record.get("source_id") or record.get("SOURCE_ID")
            if source_id is None:
                continue

            rows.append(
                {
                    "source_id": str(source_id),
                    "ra": float(record["ra"]),
                    "dec": float(record["dec"]),
                    "parallax": float(record["parallax"])
                    if record["parallax"] is not None
                    else None,
                    "pmra": float(record["pmra"])
                    if record["pmra"] is not None
                    else None,
                    "pmdec": float(record["pmdec"])
                    if record["pmdec"] is not None
                    else None,
                    "phot_g_mean_mag": float(record["phot_g_mean_mag"])
                    if record["phot_g_mean_mag"] is not None
                    else None,
                    "phot_bp_mean_mag": float(record["phot_bp_mean_mag"])
                    if record["phot_bp_mean_mag"] is not None
                    else None,
                    "phot_rp_mean_mag": float(record["phot_rp_mean_mag"])
                    if record["phot_rp_mean_mag"] is not None
                    else None,
                    "ruwe": float(record["ruwe"]) if record["ruwe"] is not None else None,
                }
            )
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Error processing Gaia record: {e}")
            continue

    return rows
