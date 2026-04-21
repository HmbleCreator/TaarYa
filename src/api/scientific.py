"""Scientific API endpoints for TaarYa.

Provides VO-standard outputs (VOTable, CSV, JSON) and scientific
analysis tools (HR diagrams, SIMBAD cross-registration).

Every export endpoint logs provenance via ResearchProvenanceLogger,
ensuring that exported data can be traced back to exact parameters.
"""

import logging
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from src.extensions.taarya_ds9 import TaarYaDS9
from src.extensions.taarya_mesa import TaarYaMESA
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
    format_evolutionary_tracks_for_plotly,
    annotate_evolutionary_tracks,
)
from src.utils.simbad_validation import cross_register_stars, filter_by_otype

from src.utils.samp_client import TaarYaSAMPClient
from src.utils.research_logger import ResearchProvenanceLogger

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scientific"])
_samp = TaarYaSAMPClient()
_ds9 = TaarYaDS9()
_provenance = ResearchProvenanceLogger(session_id="api")


def _cone_search_for_exports(
    ra: float,
    dec: float,
    radius_deg: float,
    limit: int,
    include_discovery: bool = True,
):
    """Run the standard cone search used by export-oriented scientific endpoints."""
    spatial = SpatialSearch()
    return spatial.cone_search(
        ra=ra,
        dec=dec,
        radius=radius_deg,
        limit=limit,
        include_discovery=include_discovery,
    )


@router.post("/interop/broadcast-star")
async def broadcast_star(
    ra: float = Query(..., description="Right Ascension (degrees)"),
    dec: float = Query(..., description="Declination (degrees)"),
    name: str = Query("TaarYa Candidate", description="Label for the point"),
):
    """Broadcast a single coordinate to SAMP-enabled tools (Aladin, DS9)."""
    return _samp.broadcast_star(ra, dec, name)


@router.post("/interop/broadcast-table")
async def broadcast_table(
    ra: float = Query(..., description="Right Ascension (degrees)"),
    dec: float = Query(..., description="Declination (degrees)"),
    radius_deg: float = Query(0.5, description="Search radius (degrees)"),
    limit: int = Query(100, description="Maximum results"),
):
    """Broadcast a full discovery table to SAMP-enabled tools (TOPCAT, Aladin)."""
    stars = _cone_search_for_exports(
        ra=ra,
        dec=dec,
        radius_deg=radius_deg,
        limit=limit,
        include_discovery=True,
    )
    if not stars:
        return {"error": "No stars found to broadcast."}
    return _samp.broadcast_table(stars, f"TaarYa_{ra}_{dec}")


@router.get("/interop/ds9-regions")
async def export_ds9_regions(
    ra: float = Query(..., description="Right Ascension (degrees)"),
    dec: float = Query(..., description="Declination (degrees)"),
    radius_deg: float = Query(0.5, description="Search radius (degrees)"),
    limit: int = Query(100, description="Maximum results"),
    include_discovery: bool = Query(True, description="Include discovery scoring"),
):
    """Export a DS9 region file for the current cone-search result set."""
    try:
        stars = _cone_search_for_exports(
            ra=ra,
            dec=dec,
            radius_deg=radius_deg,
            limit=limit,
            include_discovery=include_discovery,
        )
        if not stars:
            return {"message": "No stars found in the specified region", "count": 0}

        _provenance.log_action(
            "ds9_region_export",
            {"ra": ra, "dec": dec, "radius_deg": radius_deg, "limit": limit},
            f"Exported DS9 regions for {len(stars)} stars",
            tags=["export", "ds9"],
        )

        content = _ds9.render_region_file(stars)
        return Response(
            content=content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="taarya_regions_{ra}_{dec}.reg"',
                "X-TaarYa-Session-Id": _provenance.session_id,
            },
        )
    except Exception as e:
        logger.error(f"DS9 region export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/interop/ds9-load")
async def load_ds9_regions(
    ra: float = Query(..., description="Right Ascension (degrees)"),
    dec: float = Query(..., description="Declination (degrees)"),
    radius_deg: float = Query(0.5, description="Search radius (degrees)"),
    limit: int = Query(100, description="Maximum results"),
):
    """Load a cone-search region set directly into a running DS9 instance."""
    try:
        stars = _cone_search_for_exports(
            ra=ra,
            dec=dec,
            radius_deg=radius_deg,
            limit=limit,
            include_discovery=True,
        )
        if not stars:
            return {"message": "No stars found in the specified region", "count": 0}

        region_text = _ds9.render_region_file(stars)
        loaded = _ds9.load_region_text(region_text)
        return {
            "count": len(stars),
            "ds9_running": _ds9.is_ds9_running(),
            "loaded": loaded,
        }
    except Exception as e:
        logger.error(f"DS9 region load failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interop/aladin-link")
async def aladin_link(
    ra: float = Query(..., description="Right Ascension (degrees)"),
    dec: float = Query(..., description="Declination (degrees)"),
    radius_deg: float = Query(0.5, description="Search radius (degrees)"),
):
    """Return a deep link that opens the region in Aladin Lite."""
    target = quote(f"{ra:.6f} {dec:.6f}")
    fov = max(radius_deg * 2.0, 0.02)
    url = (
        "https://aladin.u-strasbg.fr/AladinLite/"
        f"?target={target}&fov={fov:.4f}&survey=P%2FDSS2%2Fcolor"
    )
    return {
        "target": {"ra": ra, "dec": dec, "radius_deg": radius_deg},
        "url": url,
    }


@router.get("/mesa/inlist/{source_id}")
async def export_mesa_inlist(
    source_id: str,
    use_hr_diagram: bool = Query(True, description="Use HR-diagram-based mass/Teff estimation"),
):
    """Export a MESA inlist for a specific star.

    If use_hr_diagram=True (default), physical parameters are estimated from
    BP-RP color and absolute G magnitude via main-sequence relations.
    Falls back to photometry heuristics when full HR-diagram data is unavailable.
    """
    try:
        spatial = SpatialSearch()
        star = spatial.coordinate_lookup(source_id)
        if not star:
            raise HTTPException(status_code=404, detail=f"Star {source_id} not found")

        _provenance.log_action(
            "mesa_inlist_export",
            {"source_id": source_id, "use_hr_diagram": use_hr_diagram},
            f"Generated MESA inlist for star {source_id}",
            tags=["export", "mesa"],
        )

        content = TaarYaMESA.build_inlist(star, use_hr_diagram=use_hr_diagram)
        return Response(
            content=content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="taarya_{source_id}.inlist"',
                "X-TaarYa-Session-Id": _provenance.session_id,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MESA inlist export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mesa/physical-params/{source_id}")
async def get_physical_params(source_id: str):
    """Return the estimated physical parameters for a star (mass, Teff, log_g, Z, BP-RP, M_G)."""
    try:
        spatial = SpatialSearch()
        star = spatial.coordinate_lookup(source_id)
        if not star:
            raise HTTPException(status_code=404, detail=f"Star {source_id} not found")
        params = TaarYaMESA.estimate_physical_params(star)
        return {"source_id": source_id, "physical_params": params}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Physical params estimation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mesa/cluster/{cluster_name}")
async def export_cluster_mesa_inlist(
    cluster_name: str,
    min_members: int = Query(10, description="Minimum member count to proceed"),
):
    """Export a cluster-level MESA inlist using the median HR-diagram position of cluster members."""
    try:
        from src.retrieval.graph_search import GraphSearch
        graph = GraphSearch()
        members = graph.find_cluster_members(cluster_name, limit=200)
        if len(members) < min_members:
            raise HTTPException(
                status_code=404,
                detail=f"Cluster '{cluster_name}' has only {len(members)} members (need {min_members})",
            )
        content = TaarYaMESA.build_cluster_inlist(members, cluster_name)
        safe_name = cluster_name.replace(" ", "_").lower()
        return Response(
            content=content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="taarya_cluster_{safe_name}.inlist"'
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cluster MESA inlist export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        stars = _cone_search_for_exports(
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

        _provenance.log_action(
            "cone_search_export",
            {"ra": ra, "dec": dec, "radius_deg": radius_deg, "format": format,
             "limit": limit, "simbad_validate": simbad_validate},
            f"Exported {len(stars)} stars as {format}",
            tags=["export", format],
        )

        session_header = {"X-TaarYa-Session-Id": _provenance.session_id}

        if format == "votable":
            content = export_to_votable(stars)
            return Response(
                content=content,
                media_type="application/xml",
                headers={
                    "Content-Disposition": f'attachment; filename="taarya_results_{ra}_{dec}.xml"',
                    **session_header,
                },
            )
        elif format == "csv":
            content = export_to_csv(stars)
            return Response(
                content=content,
                media_type="text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="taarya_results_{ra}_{dec}.csv"',
                    **session_header,
                },
            )
        elif format == "json":
            content = export_to_json(stars)
            return Response(
                content=content,
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="taarya_results_{ra}_{dec}.json"',
                    **session_header,
                },
            )
        elif format == "topcat":
            content = format_for_topcat(stars)
            return Response(
                content=content,
                media_type="text/plain",
                headers={
                    "Content-Disposition": f'attachment; filename="taarya_topcat_{ra}_{dec}.csv"',
                    **session_header,
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
        stars = _cone_search_for_exports(
            ra=ra,
            dec=dec,
            radius_deg=radius_deg,
            limit=limit,
            include_discovery=True,
        )

        hr_data = generate_hr_diagram_data(stars)

        _provenance.log_action(
            "hr_diagram",
            {"ra": ra, "dec": dec, "radius_deg": radius_deg, "ascii": ascii},
            f"Generated HR diagram with {hr_data['total_stars']} stars",
            tags=["analysis", "hr_diagram"],
        )

        if ascii:
            ascii_diagram = generate_ascii_hr_diagram(hr_data)
            return {
                "format": "ascii",
                "diagram": ascii_diagram,
                "session_id": _provenance.session_id,
                "statistics": {
                    "total_stars": hr_data["total_stars"],
                    "population_distribution": hr_data["population_distribution"],
                    "color_range": hr_data["color_range"],
                    "magnitude_range": hr_data["magnitude_range"],
                }
            }

        plotly_data = format_hr_diagram_for_plotly(hr_data)
        track_overlays = format_evolutionary_tracks_for_plotly()
        track_annotations = annotate_evolutionary_tracks()

        return {
            "format": "plotly",
            "data": plotly_data,
            "evolutionary_tracks": track_overlays,
            "track_metadata": [
                {"key": t["key"], "name": t["name"], "reference": t["reference"]}
                for t in track_annotations
            ],
            "layout": {
                "title": f"HR Diagram — {hr_data['total_stars']} stars",
                "xaxis": {"title": "BP−RP (Color Index)", "range": [-0.5, 4.5]},
                "yaxis": {"title": "Absolute G Magnitude", "autorange": "reversed"},
                "showlegend": True,
                "template": "plotly_dark",
            },
            "session_id": _provenance.session_id,
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
        stars = _cone_search_for_exports(
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
        stars = _cone_search_for_exports(
            ra=ra,
            dec=dec,
            radius_deg=radius_deg,
            limit=100,
            include_discovery=True,
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


@router.get("/catalog/overlap")
async def catalog_overlap_analysis(
    ra: float = Query(..., description="Right Ascension (degrees)"),
    dec: float = Query(..., description="Declination (degrees)"),
    radius_deg: float = Query(1.0, description="Search radius (degrees)"),
    match_radius_arcsec: float = Query(3.0, description="Positional match radius (arcsec)"),
    limit: int = Query(500, description="Maximum stars to analyze"),
):
    """Cross-catalog overlap analysis for a sky region.

    Computes pair-wise positional cross-matches between all catalogs
    present in the TaarYa database for the given region. Reports:

      - Per-catalog star counts
      - Pair-wise overlap fractions
      - Stars unique to each catalog (no cross-match)
      - Aggregate multi-catalog detection rate

    Essential for defensible multi-wavelength studies and publication
    figures showing catalog completeness.
    """
    import math as _math

    try:
        stars = _cone_search_for_exports(
            ra=ra, dec=dec, radius_deg=radius_deg,
            limit=limit, include_discovery=False,
        )

        if not stars:
            return {"message": "No stars found", "count": 0}

        _provenance.log_action(
            "catalog_overlap_analysis",
            {"ra": ra, "dec": dec, "radius_deg": radius_deg,
             "match_radius_arcsec": match_radius_arcsec},
            f"Analyzed catalog overlap for {len(stars)} stars",
            tags=["analysis", "cross_catalog"],
        )

        # Group by catalog
        catalogs: dict = {}
        for s in stars:
            cat = (s.get("catalog_source") or "UNKNOWN").strip().upper()
            catalogs.setdefault(cat, []).append(s)

        catalog_names = sorted(catalogs.keys())
        per_catalog = {c: len(catalogs[c]) for c in catalog_names}

        # Angular separation utility
        match_deg = match_radius_arcsec / 3600.0

        def _ang_sep(ra1, dec1, ra2, dec2):
            ra1r, dec1r = _math.radians(ra1), _math.radians(dec1)
            ra2r, dec2r = _math.radians(ra2), _math.radians(dec2)
            cos_angle = (
                _math.sin(dec1r) * _math.sin(dec2r)
                + _math.cos(dec1r) * _math.cos(dec2r)
                  * _math.cos(ra1r - ra2r)
            )
            cos_angle = max(-1.0, min(1.0, cos_angle))
            return _math.degrees(_math.acos(cos_angle))

        # Pair-wise overlap
        overlap_matrix: dict = {}
        for i, c1 in enumerate(catalog_names):
            for c2 in catalog_names[i + 1:]:
                matches = 0
                for s1 in catalogs[c1]:
                    r1 = s1.get("ra")
                    d1 = s1.get("dec")
                    if r1 is None or d1 is None:
                        continue
                    for s2 in catalogs[c2]:
                        r2 = s2.get("ra")
                        d2 = s2.get("dec")
                        if r2 is None or d2 is None:
                            continue
                        if _ang_sep(r1, d1, r2, d2) <= match_deg:
                            matches += 1
                            break  # one match per s1 is enough

                pair_key = f"{c1}↔{c2}"
                denom = min(len(catalogs[c1]), len(catalogs[c2]))
                overlap_matrix[pair_key] = {
                    "matches": matches,
                    "fraction": round(matches / denom, 3) if denom else 0.0,
                    f"{c1}_total": len(catalogs[c1]),
                    f"{c2}_total": len(catalogs[c2]),
                }

        # Unique-to-catalog counts
        unique_per_catalog: dict = {}
        for cat_name in catalog_names:
            others = [s for c, ss in catalogs.items() if c != cat_name for s in ss]
            unique = 0
            for s1 in catalogs[cat_name]:
                r1 = s1.get("ra")
                d1 = s1.get("dec")
                if r1 is None or d1 is None:
                    continue
                has_match = False
                for s2 in others:
                    r2 = s2.get("ra")
                    d2 = s2.get("dec")
                    if r2 is None or d2 is None:
                        continue
                    if _ang_sep(r1, d1, r2, d2) <= match_deg:
                        has_match = True
                        break
                if not has_match:
                    unique += 1
            unique_per_catalog[cat_name] = unique

        multi_detected = len(stars) - sum(unique_per_catalog.values())

        return {
            "region": {"ra": ra, "dec": dec, "radius_deg": radius_deg},
            "match_radius_arcsec": match_radius_arcsec,
            "total_stars": len(stars),
            "catalogs": per_catalog,
            "pairwise_overlap": overlap_matrix,
            "unique_per_catalog": unique_per_catalog,
            "multi_catalog_detections": multi_detected,
            "multi_catalog_fraction": round(
                multi_detected / len(stars), 3
            ) if stars else 0.0,
            "session_id": _provenance.session_id,
        }

    except Exception as e:
        logger.error(f"Catalog overlap analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
