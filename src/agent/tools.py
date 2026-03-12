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

logger = logging.getLogger(__name__)

COVERAGE_BUFFER_DEG = 2.0

# Shared instances
_spatial = SpatialSearch()
_vector = VectorSearch()
_graph = GraphSearch()


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
def cone_search(ra: float, dec: float, radius_deg: float = 0.5, limit: int = 20) -> str:
    """Search for stars within a cone around given sky coordinates.

    Use this tool when the user asks about stars near a specific location,
    provides RA/Dec coordinates, or wants to find stars in a region.

    Args:
        ra: Right Ascension in degrees (0-360)
        dec: Declination in degrees (-90 to 90)
        radius_deg: Search radius in degrees (default 0.5)
        limit: Maximum number of results (default 20)
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

        stars = _spatial.cone_search(ra=ra, dec=dec, radius_deg=radius_deg, limit=limit)
        if not stars:
            return f"No stars found within {radius_deg}° of RA={ra}, Dec={dec}."

        summary = f"Found {len(stars)} stars within {radius_deg}° of RA={ra:.4f}, Dec={dec:.4f}:\n"
        for s in stars[:10]:
            mag = s.get("phot_g_mean_mag", "N/A")
            dist = s.get("angular_distance", "N/A")
            if isinstance(dist, float):
                dist = f"{dist:.4f}°"
            summary += (
                f"  - {s['source_id']}: RA={s['ra']:.4f}, Dec={s['dec']:.4f}, "
                f"G-mag={mag}, distance={dist}\n"
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
                    ingested_at=datetime.utcnow(),
                )
            )
            session.commit()

        return f"Successfully ingested {inserted} stars from region '{name}' (RA={ra}, Dec={dec}, radius={radius_deg}°). The region is now available for queries."
    except Exception as e:
        return f"Error ingesting region '{name}': {str(e)}"


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
]
