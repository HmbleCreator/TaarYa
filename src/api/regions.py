"""Region coverage stats endpoint."""

from fastapi import APIRouter
from sqlalchemy import select

from src.database import postgres_conn
from src.models import Region

router = APIRouter(tags=["System"])


@router.get("/regions")
async def region_stats():
    """
    Return star counts per seeded sky region.
    Used by the dashboard coverage map.
    """
    postgres_conn.connect()
    with postgres_conn.session() as session:
        regions = session.execute(select(Region)).scalars().all()

    results = []
    for r in regions:
        results.append(
            {
                "name": r.name,
                "ra": r.ra,
                "dec": r.dec,
                "radius": r.radius_deg,
                "count": r.star_count,
            }
        )
    return {"regions": results}
