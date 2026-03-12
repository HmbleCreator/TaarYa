"""Star catalog search API routes."""
from fastapi import APIRouter, Query
from typing import Optional

from src.services.star_service import StarService
from src.schemas import ConeSearchResponse, ConeSearchQuery, StarCountResponse, NearbyStarsResponse

router = APIRouter(prefix="/stars", tags=["Stars"])
_svc = StarService()


@router.get("/cone-search", response_model=ConeSearchResponse)
async def cone_search(
    ra: float = Query(..., ge=0, le=360, description="Right Ascension in degrees"),
    dec: float = Query(..., ge=-90, le=90, description="Declination in degrees"),
    radius: float = Query(..., gt=0, le=10, description="Search radius in degrees"),
    mag_limit: Optional[float] = Query(None, description="Max G-band magnitude"),
    min_parallax: Optional[float] = Query(None, description="Min parallax in mas"),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
):
    """Find stars within a cone around given coordinates."""
    stars = _svc.cone_search(
        ra=ra, dec=dec, radius_deg=radius,
        mag_limit=mag_limit, min_parallax=min_parallax, limit=limit,
    )
    return ConeSearchResponse(
        query=ConeSearchQuery(ra=ra, dec=dec, radius_deg=radius),
        count=len(stars),
        stars=stars,
    )


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
