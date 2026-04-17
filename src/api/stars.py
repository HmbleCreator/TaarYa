"""Star catalog search API routes."""
from fastapi import APIRouter, Query
from typing import Optional, Literal

from src.services.star_service import StarService
from src.schemas import (
    ConeSearchResponse,
    ConeSearchQuery,
    DiscoveryResponse,
    StarCountResponse,
    NearbyStarsResponse,
    SpaceVolumeResponse,
    SpaceClusterResponse,
)

router = APIRouter(prefix="/stars", tags=["Stars"])
_svc = StarService()


@router.get("/cone-search", response_model=ConeSearchResponse)
async def cone_search(
    ra: float = Query(..., description="Right Ascension or Longitude"),
    dec: float = Query(..., description="Declination or Latitude"),
    radius: float = Query(..., gt=0, description="Search radius"),
    unit: str = Query("deg", description="Radius unit: deg, arcmin, arcsec"),
    frame: str = Query("icrs", description="Coordinate frame: icrs, galactic"),
    mag_limit: Optional[float] = Query(None, description="Max G-band magnitude"),
    min_parallax: Optional[float] = Query(None, description="Min parallax in mas"),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
):
    """Find stars within a cone around given coordinates (multi-frame)."""
    stars = _svc.cone_search(
        ra=ra, dec=dec, radius=radius, unit=unit, frame=frame,
        mag_limit=mag_limit, min_parallax=min_parallax, limit=limit,
    )
    return ConeSearchResponse(
        query=ConeSearchQuery(ra=ra, dec=dec, radius_deg=radius),
        count=len(stars),
        stars=stars,
    )


@router.get("/physics/{source_id}")
async def get_star_physics(source_id: str):
    """Get derived physical parameters (absolute mag, stellar class) for a star."""
    return _svc.get_physics_analysis(source_id)


@router.get("/convert-coords")
async def convert_coordinates(
    ra: float = Query(..., description="RA or Longitude"),
    dec: float = Query(..., description="Dec or Latitude"),
    from_frame: str = Query(..., description="Source frame: galactic, icrs"),
):
    """Convert coordinates from specified frame to ICRS."""
    return _svc.convert_coords(ra, dec, from_frame)


@router.get("/lookup/{source_id}")
async def lookup_star(source_id: str):
    """Get a single star by its Gaia source ID."""
    return _svc.lookup(source_id)


@router.get("/nearby/{source_id}", response_model=NearbyStarsResponse)
async def nearby_stars(
    source_id: str,
    radius: float = Query(0.1, gt=0, le=5, description="Search radius in degrees"),
    limit: int = Query(50, ge=1, le=500),
):
    """Find stars near a known star."""
    neighbors = _svc.nearby(source_id, radius_deg=radius, limit=limit)
    return NearbyStarsResponse(
        source_id=source_id,
        radius_deg=radius,
        count=len(neighbors),
        neighbors=neighbors,
    )


@router.get("/count", response_model=StarCountResponse)
async def count_region(
    ra: float = Query(..., ge=0, le=360),
    dec: float = Query(..., ge=-90, le=90),
    radius: float = Query(..., gt=0, le=10),
):
    """Count stars in a region without returning full data."""
    count = _svc.count_region(ra, dec, radius)
    return StarCountResponse(ra=ra, dec=dec, radius_deg=radius, count=count)


@router.get("/space-volume", response_model=SpaceVolumeResponse)
async def space_volume(
    limit: int = Query(8000, ge=1, le=10000, description="Maximum points to return"),
    min_parallax: Optional[float] = Query(None, description="Minimum parallax in mas"),
    mag_limit: Optional[float] = Query(None, description="Maximum G-band magnitude"),
):
    """Return stars projected into 3D space for the volume view."""
    return _svc.space_volume(
        limit=limit,
        min_parallax=min_parallax,
        mag_limit=mag_limit,
    )


@router.get("/ml-clusters", response_model=SpaceClusterResponse)
async def ml_clusters(
    limit: int = Query(4000, ge=50, le=10000, description="Maximum points to sample for clustering"),
    min_parallax: Optional[float] = Query(None, description="Minimum parallax in mas"),
    mag_limit: Optional[float] = Query(None, description="Maximum G-band magnitude"),
    cluster_count: Optional[int] = Query(None, ge=2, le=10, description="Optional manual cluster count"),
):
    """Return data-driven clusters for the 3D space volume."""
    return _svc.ml_clusters(
        limit=limit,
        min_parallax=min_parallax,
        mag_limit=mag_limit,
        cluster_count=cluster_count,
    )


@router.get("/discovery", response_model=DiscoveryResponse)
async def discovery_mode(
    limit: int = Query(15, ge=1, le=50, description="Maximum candidates to return"),
    pool_limit: int = Query(3000, ge=50, le=10000, description="Candidate pool size"),
    radius_deg: float = Query(0.08, gt=0, le=1, description="Local match radius in degrees"),
    mode: Literal["strict", "balanced", "aggressive"] = Query(
        "balanced",
        description="Discovery scoring profile",
    ),
):
    """Return discovery-scored candidates and catalog comparison context."""
    return _svc.discovery(
        limit=limit,
        pool_limit=pool_limit,
        radius_deg=radius_deg,
        mode=mode,
    )
