"""Scientific API endpoints for TaarYa.

Provides VO-standard outputs (VOTable, CSV, JSON) and scientific
analysis tools (HR diagrams, SIMBAD cross-registration).
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from src.retrieval.spatial_search import SpatialSearch
from src.utils.scientific_output import (
    export_to_votable,
    export_to_csv,
    export_to_json,
    format_for_topcat,
)
from src.utils.hr_diagram import (
    generate_hr_diagram_data,
    generate_ascii_hr_diagram,
    format_hr_diagram_for_plotly,
)
from src.utils.simbad_validation import cross_register_stars, filter_by_otype

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scientific"])


@router.get("/cone-search/export")
async def cone_search_export(
    ra: float = Query(..., description="Right Ascension (degrees)"),
    dec: float = Query(..., description="Declination (degrees)"),
    radius_deg: float = Query(0.5, description="Search radius (degrees)"),
    limit: int = Query(100, description="Maximum results"),
    format: str = Query("votable", description="Output format: votable, csv, json"),
    include_discovery: bool = Query(True, description="Include discovery scoring"),
    simbad_validate: bool = Query(False, description="Cross-register with SIMBAD"),
):
    """Cone search with scientific format export.

    Returns stellar data in standard astronomy formats (VOTable, CSV, JSON)
    for use with TOPCAT, Aladin, DS9, and other VO-compliant tools.
    """
    try:
        spatial = SpatialSearch()
        stars = spatial.cone_search(
            ra=ra,
            dec=dec,
            radius_deg=radius_deg,
            limit=limit,
            include_discovery=include_discovery,
        )

        if not stars:
            return {"message": "No stars found in the specified region", "count": 0}

        if simbad_validate:
            logger.info("Cross-registering stars with SIMBAD...")
            stars = cross_register_stars(stars, radius_arcsec=5.0)

        if format == "votable":
            content = export_to_votable(stars)
            return Response(
                content=content,
                media_type="application/xml",
                headers={
                    "Content-Disposition": f'attachment; filename="taarya_results_{ra}_{dec}.xml"'
                },
            )
        elif format == "csv":
            content = export_to_csv(stars)
            return Response(
                content=content,
                media_type="text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="taarya_results_{ra}_{dec}.csv"'
                },
            )
        elif format == "json":
            content = export_to_json(stars)
            return Response(
                content=content,
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="taarya_results_{ra}_{dec}.json"'
                },
            )
        elif format == "topcat":
            content = format_for_topcat(stars)
            return Response(
                content=content,
                media_type="text/plain",
                headers={
                    "Content-Disposition": f'attachment; filename="taarya_topcat_{ra}_{dec}.csv"'
                },
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown format: {format}. Use: votable, csv, json, or topcat"
            )

    except Exception as e:
        logger.error(f"Cone search export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hr-diagram")
async def hr_diagram(
    ra: float = Query(..., description="Right Ascension (degrees)"),
    dec: float = Query(..., description="Declination (degrees)"),
    radius_deg: float = Query(1.0, description="Search radius (degrees)"),
    limit: int = Query(200, description="Maximum stars to include"),
    ascii: bool = Query(False, description="Return ASCII art version"),
):
    """Generate Hertzsprung-Russell diagram data for a stellar region.

    The HR diagram plots absolute magnitude vs. color index (BP-RP),
    revealing stellar evolutionary status.
    """
    try:
        spatial = SpatialSearch()
        stars = spatial.cone_search(
            ra=ra,
            dec=dec,
            radius_deg=radius_deg,
            limit=limit,
            include_discovery=True,
        )

        hr_data = generate_hr_diagram_data(stars)

        if ascii:
            ascii_diagram = generate_ascii_hr_diagram(hr_data)
            return {
                "format": "ascii",
                "diagram": ascii_diagram,
                "statistics": {
                    "total_stars": hr_data["total_stars"],
                    "population_distribution": hr_data["population_distribution"],
                    "color_range": hr_data["color_range"],
                    "magnitude_range": hr_data["magnitude_range"],
                }
            }

        return {
            "format": "plotly",
            "data": format_hr_diagram_for_plotly(hr_data),
            "statistics": {
                "total_stars": hr_data["total_stars"],
                "population_distribution": hr_data["population_distribution"],
                "color_range": hr_data["color_range"],
                "magnitude_range": hr_data["magnitude_range"],
            }
        }

    except Exception as e:
        logger.error(f"HR diagram generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simbad/validate")
async def validate_with_simbad(
    stars: List[dict],
    radius_arcsec: float = Query(5.0, description="Match radius in arcseconds"),
):
    """Cross-register a list of stars with SIMBAD for validation.

    Accepts JSON list of stars with source_id, ra, dec fields.
    Returns enhanced stars with SIMBAD identifiers and object types.
    """
    try:
        validated = cross_register_stars(stars, radius_arcsec=radius_arcsec)

        from src.utils.simbad_validation import get_otype_distribution
        otype_dist = get_otype_distribution(validated)

        return {
            "total_stars": len(validated),
            "validated_count": sum(1 for s in validated if s.get("simbad_validated", False)),
            "population_distribution": otype_dist,
            "stars": validated,
        }

    except Exception as e:
        logger.error(f"SIMBAD validation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/filter/by-otype")
async def filter_stars_by_otype(
    ra: float = Query(..., description="Right Ascension (degrees)"),
    dec: float = Query(..., description="Declination (degrees)"),
    radius_deg: float = Query(0.5, description="Search radius (degrees)"),
    include_types: str = Query("", description="Comma-separated list of types to include"),
    exclude_types: str = Query("Galaxy,QSO,Galaxy核", description="Comma-separated types to exclude"),
):
    """Filter stars by SIMBAD object type after cone search.

    Only returns objects whose SIMBAD type matches the include list
    and is not in the exclude list.

    Common types: Star, Brown_Dwarf, White_Dwarf, Neutron_Star, Galaxy, QSO
    """
    try:
        spatial = SpatialSearch()
        stars = spatial.cone_search(
            ra=ra,
            dec=dec,
            radius_deg=radius_deg,
            limit=200,
            include_discovery=True,
        )

        validated = cross_register_stars(stars, radius_arcsec=5.0)

        include_list = [t.strip() for t in include_types.split(",") if t.strip()]
        exclude_list = [t.strip() for t in exclude_types.split(",") if t.strip()]

        if include_list:
            filtered = filter_by_otype(validated, include_types=include_list, exclude_types=exclude_list)
        else:
            filtered = filter_by_otype(validated, include_types=["Star"], exclude_types=exclude_list)

        return {
            "total_found": len(filtered),
            "filters_applied": {
                "include_types": include_list or ["Star"],
                "exclude_types": exclude_list,
            },
            "stars": filtered,
        }

    except Exception as e:
        logger.error(f"Star filtering failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/comparison")
async def compare_with_catalogs(
    ra: float = Query(..., description="Right Ascension (degrees)"),
    dec: float = Query(..., description="Declination (degrees)"),
    radius_deg: float = Query(0.5, description="Search radius (degrees)"),
):
    """Compare TaarYa catalog results with external catalog coverage.

    Returns information about what external catalogs cover this region,
    useful for multi-wavelength studies.
    """
    try:
        from src.retrieval.spatial_search import SpatialSearch
        spatial = SpatialSearch()
        stars = spatial.cone_search(
            ra=ra, dec=dec, radius_deg=radius_deg, limit=100, include_discovery=True
        )

        validated = cross_register_stars(stars, radius_arcsec=10.0)

        catalog_coverage = {
            "total_stars": len(stars),
            "with_simbad_match": sum(1 for s in validated if s.get("simbad_validated")),
            "catalog_sources": {},
        }

        for star in validated:
            source = star.get("catalog_source", "unknown")
            catalog_coverage["catalog_sources"][source] = \
                catalog_coverage["catalog_sources"].get(source, 0) + 1

        return catalog_coverage

    except Exception as e:
        logger.error(f"Catalog comparison failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
