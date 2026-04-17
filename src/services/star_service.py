"""Star catalog service — wraps SpatialSearch with error handling."""
import logging
from typing import List, Optional, Dict, Any

from fastapi import HTTPException

from src.retrieval.spatial_search import SpatialSearch
from src.retrieval.hybrid_search import HybridSearch
from src.utils.scientific_orchestrator import ScientificOrchestrator

logger = logging.getLogger(__name__)


class StarService:
    """Business logic layer for star catalog operations."""

    def __init__(self):
        self._spatial = SpatialSearch()
        self._hybrid = HybridSearch()

    def cone_search(
        self,
        ra: float,
        dec: float,
        radius: float,
        unit: str = "deg",
        frame: str = "icrs",
        mag_limit: Optional[float] = None,
        min_parallax: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Run a cone search with optional filters (multi-frame)."""
        try:
            if mag_limit is not None or min_parallax is not None:
                return self._spatial.radial_search(
                    ra=ra, dec=dec, radius=radius, unit=unit, frame=frame,
                    mag_limit=mag_limit, min_parallax=min_parallax, limit=limit,
                )
            return self._spatial.cone_search(
                ra=ra, dec=dec, radius=radius, unit=unit, frame=frame, limit=limit
            )
        except Exception as e:
            logger.error(f"Cone search failed: {e}")
            raise HTTPException(status_code=503, detail=f"Star database unavailable: {e}")

    def get_physics_analysis(self, source_id: str) -> Dict[str, Any]:
        """Get derived physical parameters for a star."""
        try:
            return self._hybrid.get_stellar_analysis(source_id)
        except Exception as e:
            logger.error(f"Physics analysis failed for {source_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def convert_coords(self, ra: float, dec: float, from_frame: str) -> Dict[str, Any]:
        """Convert coordinates between astronomical frames."""
        try:
            ra_out, dec_out = ScientificOrchestrator.parse_coordinates(ra, dec, from_frame)
            return {"ra": ra_out, "dec": dec_out, "frame": "icrs"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

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

    def space_volume(
        self,
        limit: int = 8000,
        min_parallax: Optional[float] = None,
        mag_limit: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Return 3D space points for the dashboard volume view."""
        try:
            return self._spatial.space_volume(
                limit=limit,
                min_parallax=min_parallax,
                mag_limit=mag_limit,
            )
        except Exception as e:
            logger.error(f"Space volume failed: {e}")
            raise HTTPException(status_code=503, detail=f"Star database unavailable: {e}")

    def discovery(
        self,
        limit: int = 15,
        pool_limit: int = 3000,
        radius_deg: float = 0.08,
        mode: str = "balanced",
    ) -> Dict[str, Any]:
        """Return discovery-mode candidates and catalog comparison context."""
        try:
            return self._spatial.discovery_candidates(
                limit=limit,
                pool_limit=pool_limit,
                radius_deg=radius_deg,
                mode=mode,
            )
        except Exception as e:
            logger.error(f"Discovery scoring failed: {e}")
            raise HTTPException(status_code=503, detail=f"Star database unavailable: {e}")

    def ml_clusters(
        self,
        limit: int = 4000,
        min_parallax: Optional[float] = None,
        mag_limit: Optional[float] = None,
        cluster_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return ML-derived cluster summaries for the 3D view."""
        try:
            return self._spatial.ml_clusters(
                limit=limit,
                min_parallax=min_parallax,
                mag_limit=mag_limit,
                cluster_count=cluster_count,
            )
        except Exception as e:
            logger.error(f"ML clustering failed: {e}")
            raise HTTPException(status_code=503, detail=f"Star database unavailable: {e}")
