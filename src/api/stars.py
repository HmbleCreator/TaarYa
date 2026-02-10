"""Star catalog search API routes."""
from fastapi import APIRouter, Query
from typing import Optional

from src.retrieval.spatial_search import SpatialSearch

router = APIRouter(prefix="/stars", tags=["Stars"])
spatial = SpatialSearch()


@router.get("/cone-search")
async def cone_search(
    ra: float = Query(..., ge=0, le=360, description="Right Ascension in degrees"),
    dec: float = Query(..., ge=-90, le=90, description="Declination in degrees"),
    radius: float = Query(..., gt=0, le=10, description="Search radius in degrees"),
    mag_limit: Optional[float] = Query(None, description="Max G-band magnitude"),
    min_parallax: Optional[float] = Query(None, description="Min parallax in mas"),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
):
    """
    Find stars within a cone around given coordinates using Q3C spatial index.
    
    This is the primary spatial query endpoint, leveraging PostgreSQL's Q3C
    extension for efficient cone searches on the Gaia DR3 catalog.
    """
    if mag_limit is not None or min_parallax is not None:
        stars = spatial.radial_search(
            ra=ra, dec=dec, radius_deg=radius,
            mag_limit=mag_limit, min_parallax=min_parallax, limit=limit
        )
    else:
        stars = spatial.cone_search(ra=ra, dec=dec, radius_deg=radius, limit=limit)
    
    return {
        "query": {"ra": ra, "dec": dec, "radius_deg": radius},
        "count": len(stars),
        "stars": stars,
    }


@router.get("/lookup/{source_id}")
async def lookup_star(source_id: str):
    """Get a single star by its Gaia source ID."""
    star = spatial.coordinate_lookup(source_id)
    if star is None:
        return {"error": "Star not found", "source_id": source_id}
    return star


@router.get("/nearby/{source_id}")
async def nearby_stars(
    source_id: str,
    radius: float = Query(0.1, gt=0, le=5, description="Search radius in degrees"),
    limit: int = Query(50, ge=1, le=500),
):
    """Find stars near a known star."""
    neighbors = spatial.nearby_stars(source_id, radius_deg=radius, limit=limit)
    return {
        "source_id": source_id,
        "radius_deg": radius,
        "count": len(neighbors),
        "neighbors": neighbors,
    }


@router.get("/count")
async def count_region(
    ra: float = Query(..., ge=0, le=360),
    dec: float = Query(..., ge=-90, le=90),
    radius: float = Query(..., gt=0, le=10),
):
    """Count stars in a region without returning full data."""
    count = spatial.count_in_region(ra, dec, radius)
    return {"ra": ra, "dec": dec, "radius_deg": radius, "count": count}
