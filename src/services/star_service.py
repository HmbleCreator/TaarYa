"""Star catalog service — wraps SpatialSearch with error handling."""
import logging
from typing import List, Optional, Dict, Any

from fastapi import HTTPException

from src.retrieval.spatial_search import SpatialSearch

logger = logging.getLogger(__name__)


class StarService:
    """Business logic layer for star catalog operations."""

    def __init__(self):
        self._spatial = SpatialSearch()

    def cone_search(
        self,
        ra: float,
        dec: float,
        radius_deg: float,
        mag_limit: Optional[float] = None,
        min_parallax: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Run a cone search with optional filters."""
        try:
            if mag_limit is not None or min_parallax is not None:
                return self._spatial.radial_search(
                    ra=ra, dec=dec, radius_deg=radius_deg,
                    mag_limit=mag_limit, min_parallax=min_parallax, limit=limit,
                )
            return self._spatial.cone_search(ra=ra, dec=dec, radius_deg=radius_deg, limit=limit)
        except Exception as e:
            logger.error(f"Cone search failed: {e}")
            raise HTTPException(status_code=503, detail=f"Star database unavailable: {e}")

    def lookup(self, source_id: str) -> Dict[str, Any]:
        """Look up a single star by source ID."""
        try:
            star = self._spatial.coordinate_lookup(source_id)
        except Exception as e:
            logger.error(f"Star lookup failed: {e}")
            raise HTTPException(status_code=503, detail=f"Star database unavailable: {e}")
        if star is None:
            raise HTTPException(status_code=404, detail=f"Star {source_id} not found")
        return star

    def nearby(self, source_id: str, radius_deg: float = 0.1, limit: int = 50) -> List[Dict[str, Any]]:
        """Find stars near a known star."""
        try:
            return self._spatial.nearby_stars(source_id, radius_deg=radius_deg, limit=limit)
        except Exception as e:
            logger.error(f"Nearby search failed: {e}")
            raise HTTPException(status_code=503, detail=f"Star database unavailable: {e}")

    def count_region(self, ra: float, dec: float, radius_deg: float) -> int:
        """Count stars in a region."""
        try:
            return self._spatial.count_in_region(ra, dec, radius_deg)
        except Exception as e:
            logger.error(f"Count failed: {e}")
            raise HTTPException(status_code=503, detail=f"Star database unavailable: {e}")
