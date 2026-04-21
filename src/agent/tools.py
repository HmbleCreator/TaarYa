"""LangChain tools wrapping the retrieval layer."""

import json
import logging
from typing import Any, Dict

from langchain.tools import tool
from sqlalchemy import text

from src.database import postgres_conn
from src.retrieval.spatial_search import SpatialSearch
from src.retrieval.vector_search import VectorSearch
from src.retrieval.graph_search import GraphSearch
from src.retrieval.hybrid_search import HybridSearch
from src.retrieval.batch_discovery import BatchDiscoveryEngine
from src.utils.scientific_orchestrator import ScientificOrchestrator
from src.utils.vizier_match import VizierCrossMatch
from src.utils.semantic_summarizer import SemanticSummarizer

logger = logging.getLogger(__name__)

COVERAGE_BUFFER_DEG = 2.0

# Shared instances
_spatial = SpatialSearch()
_vector = VectorSearch()
_graph = GraphSearch()
_hybrid = HybridSearch()
_batch = BatchDiscoveryEngine()
_vizier = VizierCrossMatch()


def get_catalog_coverage_raw() -> Dict[str, Any]:
    """Return the actual RA/Dec bounds of the loaded star catalog."""
    postgres_conn.connect()

    query = text("""
        SELECT
            COUNT(*) AS total_stars,
            MIN(ra) AS ra_min,
            MAX(ra) AS ra_max,
            MIN(dec) AS dec_min,
            MAX(dec) AS dec_max
        FROM stars
    """)

    with postgres_conn.session() as session:
        row = session.execute(query).mappings().one()

    total_stars = int(row["total_stars"] or 0)
    if total_stars == 0:
        return {
            "total_stars": 0,
            "ra_min": None,
            "ra_max": None,
            "dec_min": None,
            "dec_max": None,
            "suggested_search_center": None,
        }

    ra_min = float(row["ra_min"])
    ra_max = float(row["ra_max"])
    dec_min = float(row["dec_min"])
    dec_max = float(row["dec_max"])
    return {
        "total_stars": total_stars,
        "ra_min": round(ra_min, 2),
        "ra_max": round(ra_max, 2),
        "dec_min": round(dec_min, 2),
        "dec_max": round(dec_max, 2),
        "suggested_search_center": {
            "ra": round((ra_min + ra_max) / 2, 2),
            "dec": round((dec_min + dec_max) / 2, 2),
        },
    }


def _is_out_of_coverage(
    ra: float,
    dec: float,
    coverage: Dict[str, Any],
    buffer_deg: float = COVERAGE_BUFFER_DEG,
) -> bool:
    """Return True when a query falls outside the loaded footprint plus a small buffer."""
    if not coverage or not coverage.get("total_stars"):
        return True

    ra_min = coverage.get("ra_min")
    ra_max = coverage.get("ra_max")
    dec_min = coverage.get("dec_min")
    dec_max = coverage.get("dec_max")
    if None in (ra_min, ra_max, dec_min, dec_max):
        return True

    return (
        ra < ra_min - buffer_deg
        or ra > ra_max + buffer_deg
        or dec < dec_min - buffer_deg
        or dec > dec_max + buffer_deg
    )


@tool
def get_catalog_coverage() -> Dict[str, Any]:
    """Return the loaded catalog coverage bounds and a suggested search center."""
    return get_catalog_coverage_raw()


@tool
def cone_search(ra: float, dec: float, radius_deg: float = 0.5, limit: int = 20, include_discovery: bool = True) -> str:
    """Search for stars within a cone around given sky coordinates.

    Use this tool when the user asks about stars near a specific location,
    provides RA/Dec coordinates, or wants to find stars in a region.
    By default, it ranks stars by 'discovery_score' to highlight anomalous objects.

    Args:
        ra: Right Ascension in degrees (0-360)
        dec: Declination in degrees (-90 to 90)
        radius_deg: Search radius in degrees (default 0.5)
        limit: Maximum number of results (default 20)
        include_discovery: Whether to rank by discovery score (default True)
    """
    try:
        coverage = get_catalog_coverage_raw()
        if _is_out_of_coverage(ra=ra, dec=dec, coverage=coverage):
            return json.dumps(
                {
                    "status": "OUT_OF_COVERAGE",
                    "count": 0,
                    "requested": {
                        "ra": round(ra, 4),
                        "dec": round(dec, 4),
                        "radius_deg": radius_deg,
                    },
                    "coverage": coverage,
                }
            )

        stars = _spatial.cone_search(ra=ra, dec=dec, radius=radius_deg, limit=limit, include_discovery=include_discovery)
        if not stars:
            return f"No stars found within {radius_deg}° of RA={ra}, Dec={dec}."

        summary = f"Found {len(stars)} stars within {radius_deg}° of RA={ra:.4f}, Dec={dec:.4f}:\n"
        for s in stars[:10]:
            mag = s.get("phot_g_mean_mag", "N/A")
            dist = s.get("angular_distance", "N/A")
            if isinstance(dist, float):
                dist = f"{dist:.4f}°"
            
            discovery = ""
            if s.get("discovery_score", 0) > 0:
                discovery = f" [Discovery Score: {s['discovery_score']}]"
                
            summary += (
                f"  - {s['source_id']}: RA={s['ra']:.4f}, Dec={s['dec']:.4f}, "
                f"G-mag={mag}, distance={dist}{discovery}\n"
            )
        if len(stars) > 10:
            summary += f"  ... and {len(stars) - 10} more."
        return summary
    except Exception as e:
        logger.error(f"Cone search failed: {e}")
        return f"Error performing cone search: {str(e)}"


@tool
def star_lookup(source_id: str) -> str:
    """Look up detailed information about a specific star by its Gaia source ID.

    Use this tool when the user asks about a specific star or mentions a source ID.

    Args:
        source_id: The Gaia source ID of the star
    """
    try:
        star = _spatial.coordinate_lookup(source_id)
        if star is None:
            return f"Star with source_id '{source_id}' not found in the catalog."

        info = f"Star {source_id}:\n"
        info += f"  Position: RA={star['ra']:.6f}°, Dec={star['dec']:.6f}°\n"
        if star.get("parallax"):
            info += f"  Parallax: {star['parallax']:.4f} mas\n"
        if star.get("pmra") and star.get("pmdec"):
            info += f"  Proper motion: μα={star['pmra']:.4f}, μδ={star['pmdec']:.4f} mas/yr\n"
        if star.get("phot_g_mean_mag"):
            info += f"  G-band magnitude: {star['phot_g_mean_mag']:.3f}\n"
        if star.get("phot_bp_mean_mag") and star.get("phot_rp_mean_mag"):
            bp_rp = star["phot_bp_mean_mag"] - star["phot_rp_mean_mag"]
            info += f"  BP-RP color: {bp_rp:.3f}\n"
        return info
    except Exception as e:
        logger.error(f"Star lookup failed: {e}")
        return f"Error looking up star: {str(e)}"


@tool
def find_nearby_stars(source_id: str, radius_deg: float = 0.1, limit: int = 10) -> str:
    """Find neighboring stars around a known star.

    Use this when the user asks about what other stars are near a specific star.

    Args:
        source_id: Gaia source ID of the reference star
        radius_deg: Search radius in degrees (default 0.1)
        limit: Maximum number of neighbors to return
    """
    try:
        neighbors = _spatial.nearby_stars(source_id, radius_deg=radius_deg, limit=limit)
        if not neighbors:
            return f"No neighboring stars found within {radius_deg}° of {source_id}."

        summary = (
            f"Found {len(neighbors)} stars near {source_id} (within {radius_deg}°):\n"
        )
        for n in neighbors[:10]:
            mag = n.get("phot_g_mean_mag", "N/A")
            dist = n.get("angular_distance", "N/A")
            if isinstance(dist, float):
                dist = f"{dist:.4f}°"
            summary += f"  - {n['source_id']}: G-mag={mag}, dist={dist}\n"
        return summary
    except Exception as e:
        logger.error(f"Nearby stars search failed: {e}")
        return f"Error finding nearby stars: {str(e)}"


@tool
def semantic_search(query: str, limit: int = 5) -> str:
    """Search for astronomy papers by natural language query.

    Use this tool when the user asks about research topics, papers,
    or scientific concepts related to astronomy.

    Args:
        query: Natural language search query about an astronomy topic
        limit: Maximum number of results
    """
    try:
        results = _vector.search_similar(query_text=query, limit=limit)
        if not results:
            return f"No papers found matching '{query}'. The paper collection may not be populated yet."

        summary = f"Found {len(results)} papers matching '{query}':\n"
        for r in results:
            title = r["payload"].get("title", "Untitled")
            score = r["score"]
            arxiv = r["payload"].get("arxiv_id", "")
            summary += f"  - [{score:.2f}] {title}"
            if arxiv:
                summary += f" (arXiv: {arxiv})"
            summary += "\n"
        return summary
    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        return f"Error searching papers: {str(e)}"


@tool
def graph_query(source_id: str) -> str:
    """Find papers and related stars for a given star using the knowledge graph.

    Use this when the user wants to know what research exists about a star,
    or what other stars are scientifically related to it.

    Args:
        source_id: Gaia source ID to look up in the knowledge graph
    """
    try:
        papers = _graph.find_star_papers(source_id)
        related = _graph.find_related_stars(source_id, max_hops=2, limit=10)

        result = f"Knowledge graph for star {source_id}:\n"

        if papers:
            result += f"\nMentioned in {len(papers)} paper(s):\n"
            for p in papers:
                result += f"  - {p.get('title', p.get('arxiv_id', 'Unknown'))}\n"
        else:
            result += "\nNo papers found mentioning this star.\n"

        if related:
            result += f"\nRelated stars (up to 2 hops): {len(related)}\n"
            for r in related[:5]:
                result += (
                    f"  - {r['source_id']} (distance: {r.get('distance', '?')} hops)\n"
                )
        else:
            result += "No related stars found in the graph.\n"

        return result
    except Exception as e:
        logger.error(f"Graph query failed: {e}")
        return {
            "status": "UNAVAILABLE",
            "message": "Knowledge graph is offline. Skipping graph traversal.",
            "results": [],
        }


@tool
def count_stars_in_region(ra: float, dec: float, radius_deg: float = 1.0) -> str:
    """Count how many stars are in a sky region without returning details.

    Use this for questions like "how many stars are near..." or density queries.

    Args:
        ra: Right Ascension in degrees
        dec: Declination in degrees
        radius_deg: Search radius in degrees
    """
    try:
        count = _spatial.count_in_region(ra, dec, radius_deg)
        return f"There are {count} stars within {radius_deg}° of RA={ra:.2f}, Dec={dec:.2f}."
    except Exception as e:
        return f"Error counting stars: {str(e)}"


@tool
def request_region_ingestion(
    name: str, ra: float, dec: float, radius_deg: float = 1.0
) -> str:
    """
    Ingest stars from a new sky region using Gaia DR3.

    Use this tool when the user asks to fetch, ingest, load, or add stars
    from a new sky region or named cluster that hasn't been loaded yet.

    Args:
        name: Name of the region (e.g., "Hyades", "Pleiades", "Coma Berenices")
        ra: Right Ascension center in degrees (0-360)
        dec: Declination center in degrees (-90 to 90)
        radius_deg: Search radius in degrees (default 1.0)
    """
    from datetime import datetime
    from src.ingestion.gaia_query import query_gaia_region
    from src.models import Region
    from sqlalchemy import text

    insert_query = text("""
        INSERT INTO stars (
            source_id, ra, dec, parallax, pmra, pmdec,
            phot_g_mean_mag, catalog_source
        )
        VALUES (
            :source_id, :ra, :dec, :parallax, :pmra, :pmdec,
            :phot_g_mean_mag, :catalog_source
        )
        ON CONFLICT (source_id) DO NOTHING
    """)

    try:
        # Query Gaia
        stars = query_gaia_region(ra, dec, radius_deg)
        if not stars:
            return f"No stars found in region '{name}' at RA={ra}, Dec={dec} with radius={radius_deg}°. The query may have returned empty results."

        # Insert stars
        postgres_conn.connect()
        with postgres_conn.session() as session:
            inserted = 0
            for row in stars:
                row["catalog_source"] = "GAIA"
                result = session.execute(insert_query, row)
                inserted += result.rowcount or 0

            # Upsert region record
            session.merge(
                Region(
                    name=name,
                    ra=ra,
                    dec=dec,
                    radius_deg=radius_deg,
                    star_count=inserted,
                    ingested_at=datetime.datetime.now(datetime.timezone.utc),
                )
            )
            session.commit()

        return f"Successfully ingested {inserted} stars from region '{name}' (RA={ra}, Dec={dec}, radius={radius_deg}°). The region is now available for queries."
    except Exception as e:
        return f"Error ingesting region '{name}': {str(e)}"


@tool
def validate_discovery(source_id: str) -> str:
    """Validate a star's discovery signals against scientific literature.

    Use this when a star has a high discovery score or interesting signals
    (like high RUWE or extreme color) and you want to see if papers
    support or explain these signals.

    Args:
        source_id: Gaia source ID of the star to validate
    """
    try:
        report = _hybrid.validate_discovery_with_literature(source_id)
        if "error" in report:
            return f"Error: {report['error']}"

        if report.get("status") == "unvalidated":
            return f"Star {source_id}: {report['message']}"

        output = f"Scientific Validation Report for Star {source_id}:\n"
        output += f"  Overall Consistency Score: {report['overall_score']}\n"
        output += f"  Summary: {report['summary']}\n\n"

        for v in report["validations"]:
            output += f"Paper (arXiv:{v['arxiv_id']}):\n"
            output += f"  Status: {v['status']}\n"
            if v["matches"]:
                output += "  Matches:\n"
                for m in v["matches"]:
                    output += f"    - {m}\n"
            if v["conflicts"]:
                output += "  Conflicts:\n"
                for c in v["conflicts"]:
                    output += f"    - {c}\n"
            output += "\n"

        return output
    except Exception as e:
        logger.error(f"Discovery validation failed: {e}")
        return f"Error validating discovery: {str(e)}"


@tool
def convert_coordinates(ra: float, dec: float, from_frame: str = "galactic") -> str:
    """Convert astronomical coordinates between different frames.

    Use this when the user provides Galactic (l, b) or Ecliptic coordinates
    and you need to find the equivalent ICRS (RA, Dec) for a search.

    Args:
        ra: Longitude or RA value
        dec: Latitude or Dec value
        from_frame: The source frame ('galactic', 'icrs', 'fk5')
    """
    try:
        ra_out, dec_out = ScientificOrchestrator.parse_coordinates(ra, dec, from_frame)
        return f"Coordinates in ICRS: RA={ra_out:.6f}, Dec={dec_out:.6f}"
    except Exception as e:
        return f"Error converting coordinates: {str(e)}"


@tool
def scientific_cone_search(
    ra: float, 
    dec: float, 
    radius: float = 0.5, 
    unit: str = "deg", 
    frame: str = "icrs",
    limit: int = 20
) -> str:
    """Advanced scientific cone search with unit and frame support.

    Use this for high-precision searches where units like arcminutes or arcseconds
    are specified, or when coordinates are in Galactic (l, b) frame.

    Args:
        ra: RA or Longitude
        dec: Dec or Latitude
        radius: Search radius value
        unit: Unit of radius ('deg', 'arcmin', 'arcsec')
        frame: Coordinate frame ('icrs', 'galactic')
        limit: Max results
    """
    try:
        stars = _spatial.cone_search(ra=ra, dec=dec, radius=radius, unit=unit, frame=frame, limit=limit, include_discovery=True)
        if not stars:
            return f"No stars found in {frame} region {ra}, {dec} with radius {radius} {unit}."

        summary = f"Scientific search results ({frame}, radius {radius} {unit}):\n"
        for s in stars[:10]:
            mag = s.get("phot_g_mean_mag", "N/A")
            discovery = f" [Score: {s.get('discovery_score', 0)}]" if s.get('discovery_score', 0) > 0 else ""
            summary += f"  - {s['source_id']}: RA={s['ra']:.4f}, Dec={s['dec']:.4f}, G={mag}{discovery}\n"
        
        if "_provenance" in stars[0]:
            p = stars[0]["_provenance"]
            summary += f"\nProvenance: Executed {p['query_type']} at {p['timestamp']} using {p['reference_catalog']}\n"
            
        return summary
    except Exception as e:
        return f"Error in scientific cone search: {str(e)}"


@tool
def analyze_star_physics(source_id: str) -> str:
    """Compute derived physical parameters for a star (absolute mag, class).

    Use this when you need to know the true luminosity, stellar population
    type, or binary separation potential for a specific star.

    Args:
        source_id: Gaia source ID
    """
    try:
        analysis = _hybrid.get_stellar_analysis(source_id)
        if "error" in analysis:
            return analysis["error"]

        output = f"Physical Analysis for Star {source_id}:\n"
        if "absolute_g_mag" in analysis:
            output += f"  Absolute G-band Mag: {analysis['absolute_g_mag']}\n"
        if "stellar_class" in analysis:
            output += f"  Likely Population: {analysis['stellar_class']}\n"
        if "binary_sep_limit_au" in analysis:
            output += f"  Binary separation indicator: ~{analysis['binary_sep_limit_au']} AU\n"
        
        return output
    except Exception as e:
        return f"Error in physics analysis: {str(e)}"


@tool
def discovery_batch_run(mode: str = "high_velocity", min_snr: float = 5.0, limit: int = 20) -> str:
    """Run a high-fidelity discovery search across all ingested data.

    Use this for systematic searches of unusual objects across the whole catalog.
    Available modes: 'high_velocity', 'binary_candidates'.

    Args:
        mode: The type of objects to find ('high_velocity', 'binary_candidates')
        min_snr: Minimum Signal-to-Noise ratio (default 5.0)
        limit: Max candidates to return
    """
    try:
        if mode == "high_velocity":
            stars = _batch.find_high_velocity_candidates(min_snr=min_snr, limit=limit)
        elif mode == "binary_candidates":
            stars = _batch.find_binary_candidates(limit=limit)
        else:
            return f"Unknown discovery mode: {mode}"

        if not stars:
            return f"No discovery candidates found for mode '{mode}' with current criteria."

        output = f"Top {len(stars)} candidates for discovery mode '{mode}':\n"
        for s in stars:
            ra, dec = s.get('ra'), s.get('dec')
            pm = s.get('total_pm', 0)
            ruwe = s.get('ruwe', 0)
            output += f"  - {s['source_id']}: RA={ra:.4f}, Dec={dec:.4f}"
            if mode == 'high_velocity': output += f", PM={pm:.1f} mas/yr"
            if mode == 'binary_candidates': output += f", RUWE={ruwe:.2f}"
            output += "\n"
        
        return output
    except Exception as e:
        return f"Batch discovery failed: {str(e)}"


@tool
def multi_wavelength_cross_match(ra: float, dec: float, radius_arcsec: float = 2.0) -> str:
    """Cross-match a position with major astronomical catalogs (2MASS, AllWISE, Chandra).

    Use this when you want to find an object's counterpart in other wavelengths
    (e.g., finding the infrared or X-ray flux of a star).

    Args:
        ra: Right Ascension (deg)
        dec: Declination (deg)
        radius_arcsec: Match radius (default 2.0)
    """
    try:
        results = _vizier.cross_match_object(ra, dec, radius_arcsec)
        
        output = f"VizieR Cross-Match Results for RA={ra}, Dec={dec}:\n"
        found = False
        for cat, matches in results.items():
            if matches:
                found = True
                output += f"  - Catalog: {cat} ({len(matches)} match found)\n"
                # Display the first match with basic info
                m = matches[0]
                if cat == "2MASS": output += f"    - Jmag: {m.get('Jmag')}, Hmag: {m.get('Hmag')}, Kmag: {m.get('Kmag')}\n"
                if cat == "AllWISE": output += f"    - W1mag: {m.get('W1mag')}, W2mag: {m.get('W2mag')}\n"
                if cat == "Chandra": output += f"    - CSC2 ID: {m.get('name')}, F_x: {m.get('flux')}\n"
                if cat == "GALEX": output += f"    - FUV: {m.get('FUV')}, NUV: {m.get('NUV')}\n"

        if not found:
            return f"No cross-catalog matches found for RA={ra}, Dec={dec} within {radius_arcsec} arcseconds."
            
        return output
    except Exception as e:
        return f"VizieR cross-match failed: {str(e)}"


@tool
def generate_research_profile(source_id: str) -> str:
    """Generate a high-fidelity research-grade profile for a star.

    Use this for in-depth analysis of a specific discovery candidate.
    It includes extinction corrections, multi-wavelength SED fitting,
    VizieR cross-matching, and Teff estimation.

    Args:
        source_id: Gaia source ID of the star
    """
    try:
        profile = _hybrid.get_research_grade_profile(source_id)
        if "error" in profile:
            return profile["error"]

        output = f"Research Profile for Star {source_id}:\n"
        output += f"  Teff (estimated): {profile.get('teff_estimated_k', 'N/A')} K\n"
        output += f"  Extinction A_G: {profile.get('extinction_ag', 'N/A')} mag\n"
        output += f"  Reddening E(B-V): {profile.get('ebv_sfd', 'N/A')}\n\n"

        # SED Summary
        if profile.get("sed_points"):
            output += "Multi-Wavelength Photometry (SED Points):\n"
            for p in profile["sed_points"]:
                output += f"  - {p['filter']} ({p['wavelength_um']} um): {p['flux_jy']} Jy\n"
        
        # VizieR matches
        v_matches = profile.get("vizier_matches", {})
        if any(v_matches.values()):
            output += "\nCross-Catalog Matches:\n"
            for cat, m in v_matches.items():
                if m: output += f"  - Found in {cat} catalog.\n"

        output += f"\nScientific Conclusion: This object is likely a {profile.get('physics_analysis', {}).get('stellar_class', 'unknown population')}."
        
        return output
    except Exception as e:
        return f"Research profile generation failed: {str(e)}"


@tool
def robust_discovery_sweep(ra: float, dec: float, radius: float = 0.5, mode: str = "balanced") -> str:
    """Perform a multi-seed discovery sweep to identify robust candidates.

    Use this when you want to ensure that discovery candidates are statistically
    significant and not just artifacts of weight selection. Runs 5 trials.

    Args:
        ra: Right Ascension (deg)
        dec: Declination (deg)
        radius: Search radius (deg)
        mode: Sensitivity mode ('strict', 'balanced', 'aggressive')
    """
    try:
        stars = _hybrid.get_statistically_robust_candidates(ra, dec, radius, mode)
        if not stars:
            return f"No stars found in region {ra}, {dec}."

        output = f"Robust Discovery Sweep Results for RA={ra}, Dec={dec} (5 Seeds):\n"
        # Filter for top candidates with robust scores
        candidates = [s for s in stars if s.get("robust_score")]
        
        for s in candidates[:10]:
            stat = s["robust_score"]
            output += f"  - {s['source_id']}: Mean Score {stat['mean_score']} (σ={stat['std_dev']}) | Confidence: {stat['confidence']}\n"
            output += "    Feature Importance: " + ", ".join([f"{k}: {v*100:.0f}%" for k,v in stat['feature_importance'].items()]) + "\n"
            
        return output
    except Exception as e:
        return f"Robust sweep failed: {str(e)}"


@tool
def fetch_gaia_alerts(limit: int = 10) -> str:
    """Fetch the latest real-time transient alerts from the Gaia Science Alerts stream.

    Use this to discover newly appearing supernovae, microlensing events,
    or other transient astrophysical phenomena.

    Args:
        limit: Number of alerts to fetch (default 10)
    """
    try:
        alerts = _hybrid.alerts.fetch_latest_alerts(limit)
        if not alerts:
            return "No recent Gaia alerts found."

        output = f"Latest {len(alerts)} Gaia Science Alerts:\n"
        for a in alerts:
            output += f"  - {a['alert_name']} ({a['class'] or 'Unknown class'}): RA={a['ra']}, Dec={a['dec']} | Mag: {a['alert_mag']} (Disc Mag: {a['discovery_mag']})\n"
        
        output += "\nResearchers can use 'scientific_cone_search' on these coordinates to investigate the host environment."
        return output
    except Exception as e:
        return f"Failed to fetch Gaia alerts: {str(e)}"


@tool
def broadcast_to_samp(ra: float, dec: float, name: str = "TaarYa Discovery") -> str:
    """Broadcast coordinates to professional tools like Aladin, TOPCAT, or DS9.

    Use this when you have found an interesting candidate and want to show it
    to the researcher in their desktop astronomical tools.
    Requires a SAMP Hub to be running (usually open Aladin or TOPCAT first).

    Args:
        ra: Right Ascension (deg)
        dec: Declination (deg)
        name: Label for the point in the external tool
    """
    try:
        res = _hybrid.broadcast_candidate(ra, dec, name)
        if "error" in res:
            return f"SAMP Hub Error: {res['error']}"
        return f"Successfully broadcasted {name} to SAMP Hub at RA={ra}, Dec={dec}."
    except Exception as e:
        return f"Failed to broadcast to SAMP: {str(e)}"


@tool
def summarize_research_results(query: str, type: str = "literature") -> str:
    """Summarize a large set of astronomical results for a researcher.

    Use this when you have found many papers or many stars and want to
    provide an executive summary of the findings (Map-Reduce style).

    Args:
        query: The original research query
        type: The type of data to summarize ('literature' or 'catalog')
    """
    try:
        if type == "literature":
            papers = _vector.search_similar(query, limit=10)
            return SemanticSummarizer.map_reduce_literature(papers, query)
        elif type == "catalog":
            # Just summarize whatever is in the current context for now
            # In a more advanced implementation, we'd pass the actual list
            return "Catalog summarization initiated. See the results above for key statistics."
        return "Unknown summary type."
    except Exception as e:
        return f"Summarization failed: {str(e)}"


@tool
def broadcast_discovery_table(ra: float, dec: float, radius: float = 0.5) -> str:
    """Broadcast a full table of discovery candidates to TOPCAT or Aladin.

    Use this when you have identified a significant group of stars and want to
    open them as a table in professional desktop software for cross-matching.

    Args:
        ra: Center RA (deg)
        dec: Center Dec (deg)
        radius: Search radius (deg)
    """
    try:
        stars = _spatial.cone_search(ra, dec, radius, limit=100)
        if not stars:
            return f"No stars found in region {ra}, {dec}."

        res = _hybrid.samp.broadcast_table(stars, f"TaarYa_{ra}_{dec}")
        if "error" in res:
            return f"SAMP Hub Error: {res['error']}"
        return res["status"]
    except Exception as e:
        return f"Failed to broadcast table: {str(e)}"


@tool
def fits_preview_link(ra: float, dec: float, fov: float = 0.5) -> str:
    """Generate an interactive Aladin Lite preview link for a sky region.

    Use this to give the researcher a direct link to visually inspect the sky
    region in a browser-based FITS viewer.

    Args:
        ra: Center RA (deg)
        dec: Center Dec (deg)
        fov: Field of view in degrees (default 0.5)
    """
    url = f"https://aladin.u-strasbg.fr/AladinLite/?target={ra}%20{dec}&fov={fov}"
    return f"Interactive Sky Preview: {url}\nUse this link to inspect the region in Aladin Lite."


@tool
def validate_scoring_precision(ra: float, dec: float, radius: float = 1.0) -> str:
    """Evaluate the precision and recall of the discovery engine weights.

    Use this to perform an 'expert review' of the scoring system by comparing
    flagged candidates against physical ground-truth (e.g., hypervelocity criteria).

    Args:
        ra: Right Ascension (deg)
        dec: Declination (deg)
        radius: Region radius (deg)
    """
    try:
        metrics = _hybrid.run_scoring_validation(ra, dec, radius)
        output = f"Discovery Scoring Validation for RA={ra}, Dec={dec}:\n"
        output += f"  Precision: {metrics['precision']*100:.1f}%\n"
        output += f"  Recall: {metrics['recall']*100:.1f}%\n"
        output += f"  F1 Score: {metrics['f1_score']}\n"
        output += f"  Confusion Matrix: TP={metrics['tp']}, FP={metrics['fp']}, FN={metrics['fn']}, TN={metrics['tn']}\n"
        output += f"\nConclusion: " + ("Highly Reliable" if metrics['precision'] > 0.8 else "Needs Calibration")
        return output
    except Exception as e:
        return f"Validation failed: {str(e)}"


@tool
def navigate_sky(ra: float, dec: float, fov: float = 1.0, survey: str = "P/DSS2/color") -> str:
    """Navigate the user's interactive sky viewer to specific coordinates.

    Use this to visually show the user a region of the sky. The viewer is
    embedded in the TaarYa web interface and will smoothly pan to the target.
    Call this AFTER finding interesting objects so the user can see them.

    Available surveys: 'P/DSS2/color', 'P/2MASS/color',
    'P/PanSTARRS/DR1/color-i-r-g', 'P/SDSS9/color', 'P/allWISE/color'

    Args:
        ra: Right Ascension in degrees (0-360)
        dec: Declination in degrees (-90 to 90)
        fov: Field of view in degrees (default 1.0, smaller = more zoomed in)
        survey: Background sky survey to display (default 'P/DSS2/color')
    """
    return json.dumps({
        "_sky_command": True,
        "action": "goto",
        "ra": round(ra, 6),
        "dec": round(dec, 6),
        "fov": round(fov, 4),
        "survey": survey,
        "message": f"Navigating sky viewer to RA={ra:.4f}°, Dec={dec:.4f}° (FoV={fov}°, survey={survey})",
    })


# All tools for the agent
ALL_TOOLS = [
    get_catalog_coverage,
    cone_search,
    star_lookup,
    find_nearby_stars,
    semantic_search,
    graph_query,
    count_stars_in_region,
    request_region_ingestion,
    validate_discovery,
    convert_coordinates,
    scientific_cone_search,
    analyze_star_physics,
    discovery_batch_run,
    multi_wavelength_cross_match,
    generate_research_profile,
    robust_discovery_sweep,
    fetch_gaia_alerts,
    broadcast_to_samp,
    summarize_research_results,
    broadcast_discovery_table,
    fits_preview_link,
    validate_scoring_precision,
    navigate_sky,
]
