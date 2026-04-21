"""Hybrid search combining spatial, vector, and graph backends."""

import logging
from typing import List, Optional, Dict, Any
from enum import Enum

from src.retrieval.spatial_search import SpatialSearch
from src.retrieval.vector_search import VectorSearch
from src.retrieval.graph_search import GraphSearch
from src.utils.scientific_consistency import ScientificConsistency
from src.utils.scientific_analysis import ScientificAnalysis
from src.utils.research_logger import ResearchProvenanceLogger
from src.utils.discovery_benchmarker import DiscoveryBenchmarker
from src.utils.photometric_correction import PhotometricCorrection
from src.utils.sed_fitter import SEDFitter
from src.utils.vizier_match import VizierCrossMatch
from src.utils.statistical_rigor import MultiSeedDiscovery
from src.ingestion.gaia_alerts import GaiaAlertsIngestor
from src.utils.samp_client import TaarYaSAMPClient

logger = logging.getLogger(__name__)


class SearchType(Enum):
    """Types of search operations."""

    SPATIAL = "spatial"
    SEMANTIC = "semantic"
    GRAPH = "graph"
    HYBRID = "hybrid"


class HybridSearch:
    """
    Unified search facade combining all three backends.

    This is the primary interface the Agent layer uses to query data.
    It routes queries to the appropriate backend(s) and merges results.
    """

    def __init__(self, session_id: str = None):
        self.spatial = SpatialSearch()
        self.vector = VectorSearch()
        self.graph = GraphSearch()
        self.consistency = ScientificConsistency()
        self.analysis = ScientificAnalysis()
        self.provenance = ResearchProvenanceLogger(session_id)
        self.benchmarker = DiscoveryBenchmarker()
        self.corrections = PhotometricCorrection()
        self.sed = SEDFitter()
        self.vizier = VizierCrossMatch()
        self.rigor = MultiSeedDiscovery()
        self.alerts = GaiaAlertsIngestor()
        self.samp = TaarYaSAMPClient()

    def broadcast_candidate(self, ra: float, dec: float, name: str) -> Dict[str, Any]:
        """Broadcast a point to the local SAMP Hub (Aladin/TOPCAT)."""
        return self.samp.broadcast_star(ra, dec, name)

    def get_statistically_robust_candidates(self, ra: float, dec: float, radius: float, mode: str = "balanced") -> List[Dict[str, Any]]:
        """
        Retrieves candidates and validates them with a multi-seed sweep.
        """
        stars = self.spatial.cone_search(ra, dec, radius, limit=100)
        if not stars:
            return []
            
        robust_stats = self.rigor.compute_robust_scores(stars, mode)
        
        # Merge stats back into star records
        stats_map = {s["source_id"]: s for s in robust_stats}
        for s in stars:
            if s["source_id"] in stats_map:
                s["robust_score"] = stats_map[s["source_id"]]
        
        return sorted(stars, key=lambda x: x.get("robust_score", {}).get("mean_score", 0), reverse=True)

    def get_research_grade_profile(self, source_id: str) -> Dict[str, Any]:
        """
        Build a comprehensive, research-grade profile for a star.
        Includes extinction corrections, SED fitting, and cross-catalog context.
        """
        star = self.spatial.coordinate_lookup(source_id)
        if not star:
            return {"error": f"Star {source_id} not found."}

        # 1. Uncertainty Propagation
        # Get errors from star record (added in previous DB migration)
        g_err = star.get("phot_g_mean_mag_error", 0.01)
        pi_err = star.get("parallax_error", 0.01)
        
        abs_mag_data = self.analysis.estimate_absolute_magnitude_with_error(
            star.get("phot_g_mean_mag"), 
            star.get("parallax"), 
            g_err, pi_err
        )
        star["absolute_g_mag"] = abs_mag_data["value"]
        star["absolute_g_mag_error"] = abs_mag_data["error"]

        # 2. Local Density Anomaly Check
        star["density_context"] = self.spatial.is_density_anomaly(star)
        
        # 3. Apply photometric corrections
        star = self.corrections.apply_extinction(star)

        # 2. Cross-match with major catalogs
        vizier_matches = self.vizier.cross_match_object(star["ra"], star["dec"])
        star["vizier_matches"] = vizier_matches

        # 3. Fit Spectral Energy Distribution (SED)
        flux_points = self.sed.compute_sed(star, vizier_matches)
        star["sed_points"] = flux_points
        star["teff_estimated_k"] = self.sed.estimate_teff_from_sed(flux_points)

        # 4. Standard physics analysis (on corrected photometry)
        # We temporarily replace mags with corrected versions for classification
        corrected_star = star.copy()
        if "phot_g_mean_mag_corrected" in star:
            corrected_star["phot_g_mean_mag"] = star["phot_g_mean_mag_corrected"]
            
        physics = self.get_stellar_analysis(source_id)
        star["physics_analysis"] = physics

        # Log for reproducibility
        self.provenance.log_action("research_profile", {"source_id": source_id}, f"Created profile for star {source_id} with Teff={star['teff_estimated_k']}K.")

        return star

    def get_stellar_analysis(self, source_id: str) -> Dict[str, Any]:
        """
        Compute derived physical parameters for a star.
        """
        star = self.spatial.coordinate_lookup(source_id)
        if not star:
            return {"error": f"Star {source_id} not found."}

        res = {"source_id": source_id}
        g_mag = star.get("phot_g_mean_mag")
        parallax = star.get("parallax")
        bp = star.get("phot_bp_mean_mag")
        rp = star.get("phot_rp_mean_mag")

        if g_mag and parallax:
            res_data = self.analysis.estimate_absolute_magnitude_with_error(g_mag, parallax)
            abs_g = res_data["value"]
            res["absolute_g_mag"] = abs_g
            res["absolute_g_mag_error"] = res_data["error"]
            
            if bp and rp:
                bp_rp = bp - rp
                res["bp_rp_color"] = round(bp_rp, 2)
                res["stellar_class"] = self.analysis.classify_stellar_population(bp_rp, abs_g)

        if star.get("ruwe") and parallax:
            res["binary_sep_limit_au"] = round(self.analysis.estimate_binary_separation_limit(star["ruwe"], parallax), 2)

        return res

    def validate_discovery_with_literature(
        self, source_id: str, limit_papers: int = 5
    ) -> Dict[str, Any]:
        """Validates a star's catalog discovery signals against literature.

        Args:
            source_id: Gaia source ID
            limit_papers: Maximum papers to check

        Returns:
            Validation report with consistency scores
        """
        star = self.spatial.coordinate_lookup(source_id)
        if not star:
            return {"error": f"Star {source_id} not found."}

        papers = self.graph.find_star_papers(
            source_id,
            include_cluster_context=True,
            limit=limit_papers,
        )
        if not papers:
            return {
                "source_id": source_id,
                "status": "unvalidated",
                "message": "No literature found for this star.",
            }

        validations = []
        for paper in papers[:limit_papers]:
            validations.append(self.consistency.check_star_paper_consistency(star, paper))

        overall_score = (
            sum(v["consistency_score"] for v in validations) / len(validations)
            if validations
            else 0.0
        )

        return {
            "source_id": source_id,
            "overall_score": round(overall_score, 2),
            "validations": validations,
            "summary": "Validated with literature." if validations else "No literature match.",
        }

    def run_scoring_validation(self, ra: float, dec: float, radius: float = 1.0) -> Dict[str, Any]:
        """Validate discovery weights against known physics in a region."""
        stars = self.spatial.cone_search(ra, dec, radius, limit=500, include_discovery=True)
        return self.benchmarker.evaluate_precision_recall(stars)

    def cone_search_with_context(
        self,
        ra: float,
        dec: float,
        radius_deg: float,
        limit: int = 50,
        enrich_with_graph: bool = True,
    ) -> Dict[str, Any]:
        """
        Spatial cone search enriched with knowledge graph context.

        Finds stars in a region, then looks up related papers and
        cluster memberships from the knowledge graph.

        Args:
            ra: Right Ascension in degrees
            dec: Declination in degrees
            radius_deg: Search radius in degrees
            limit: Maximum star results
            enrich_with_graph: Whether to add graph context

        Returns:
            Dict with stars list and optional graph context
        """
        logger.info(f"Hybrid cone search: RA={ra}, Dec={dec}, r={radius_deg}°")

        # Step 1: Spatial search
        stars = self.spatial.cone_search(ra=ra, dec=dec, radius=radius_deg, limit=limit)

        # Log action for reproducibility
        self.provenance.log_action("cone_search", {"ra": ra, "dec": dec, "radius": radius_deg}, f"Found {len(stars)} stars.")

        result = {
            "query": {
                "type": "cone_search",
                "ra": ra,
                "dec": dec,
                "radius_deg": radius_deg,
            },
            "count": len(stars),
            "stars": stars,
        }

        # Step 2: Enrich with graph data
        if enrich_with_graph and stars:
            papers_found = []
            seen_papers = set()
            
            for star in stars[:10]:  # Limit graph lookups for performance
                star_papers = self.graph.find_star_papers(
                    star["source_id"],
                    include_cluster_context=True,
                )
                for p in star_papers:
                    if p["arxiv_id"] not in seen_papers:
                        papers_found.append(
                            {
                                "source_id": star["source_id"],
                                "paper": p,
                                "link_type": p.get("link_type", "direct"),
                            }
                        )
                        seen_papers.add(p["arxiv_id"])

            result["related_papers"] = papers_found

        return result

    def semantic_search_with_sources(
        self, query_text: str, collection: Optional[str] = None, limit: int = 10
    ) -> Dict[str, Any]:
        """
        Semantic search on papers, enriched with cited stars.

        Finds papers matching the query semantically, then looks up
        which stars are mentioned in those papers.

        Args:
            query_text: Natural language query
            collection: Qdrant collection name
            limit: Number of paper results

        Returns:
            Dict with papers and their associated stars
        """
        logger.info(f"Semantic search: '{query_text[:80]}'")

        # Step 1: Vector search
        papers = self.vector.search_similar(query_text, collection, limit)

        result = {
            "query": {"type": "semantic_search", "text": query_text},
            "count": len(papers),
            "papers": papers,
        }

        # Step 2: For each paper, find mentioned stars via graph
        # (only if papers have arxiv_id in payload)
        stars_mentioned = []
        for paper in papers:
            arxiv_id = paper.get("payload", {}).get("arxiv_id")
            if arxiv_id:
                # Reverse lookup: find stars mentioned in this paper
                with_stars = self._find_stars_in_paper(arxiv_id)
                if with_stars:
                    stars_mentioned.append({"arxiv_id": arxiv_id, "stars": with_stars})

        result["mentioned_stars"] = stars_mentioned
        return result

    def _find_stars_in_paper(self, arxiv_id: str) -> List[Dict[str, Any]]:
        """Find stars mentioned in a paper via the knowledge graph."""
        query = """
        MATCH (s:Star)-[:MENTIONED_IN]->(p:Paper {arxiv_id: $arxiv_id})
        RETURN s.source_id AS source_id, s.ra AS ra, s.dec AS dec,
               s.phot_g_mean_mag AS phot_g_mean_mag
        """
        from src.database import neo4j_conn

        with neo4j_conn.session() as session:
            result = session.run(query, {"arxiv_id": arxiv_id})
            return [dict(record) for record in result]

    def multi_search(
        self,
        query_text: Optional[str] = None,
        ra: Optional[float] = None,
        dec: Optional[float] = None,
        radius_deg: Optional[float] = None,
        source_id: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Intelligent multi-backend search based on available parameters.

        Automatically determines which backends to query:
        - If ra/dec/radius → cone search
        - If query_text → semantic search
        - If source_id → lookup + neighbors + papers
        - Multiple params → combines results

        Args:
            query_text: Natural language query (for semantic search)
            ra/dec/radius_deg: Spatial parameters (for cone search)
            source_id: Star identifier (for lookup)
            limit: Maximum results per backend

        Returns:
            Combined results from all applicable backends
        """
        results = {"backends_used": []}

        # Spatial search
        if ra is not None and dec is not None and radius_deg is not None:
            stars = self.spatial.cone_search(ra=ra, dec=dec, radius=radius_deg, limit=limit)
            results["spatial"] = {"count": len(stars), "stars": stars}
            results["backends_used"].append("spatial")

        # Semantic search
        if query_text:
            papers = self.vector.search_similar(query_text, limit=limit)
            results["semantic"] = {"count": len(papers), "papers": papers}
            results["backends_used"].append("semantic")

        # Star lookup
        if source_id:
            star = self.spatial.coordinate_lookup(source_id)
            papers = self.graph.find_star_papers(
                source_id,
                include_cluster_context=True,
            )
            related = self.graph.find_related_stars(source_id)

            results["star_detail"] = {
                "star": star,
                "papers": papers,
                "related_stars": related[:10],
            }
            results["backends_used"].append("graph")

        return results

    def get_system_stats(self) -> Dict[str, Any]:
        """Get statistics from all backends."""
        stats = {}

        # PostgreSQL
        try:
            # Use a fast standard count count instead of a 360-degree Q3C query
            # Since Q3C radial query with 360 radius might be invalid or very slow
            try:
                from src.database import postgres_conn
                from sqlalchemy import text

                postgres_conn.connect()
                with postgres_conn.session() as session:
                    count = session.execute(
                        text(
                            "SELECT reltuples::bigint AS estimate FROM pg_class WHERE relname='stars';"
                        )
                    ).scalar()
                    if count is None or count < 100:
                        count = session.execute(
                            text("SELECT COUNT(*) FROM stars")
                        ).scalar()
            except Exception as e:
                logger.warning(f"Stats query failed: {e}")
                count = 0

            stats["postgresql"] = {"total_stars": count, "status": "connected"}
        except Exception as e:
            stats["postgresql"] = {"status": "error", "error": str(e)}

        # Qdrant
        try:
            info = self.vector.get_collection_info()
            stats["qdrant"] = info
        except Exception as e:
            stats["qdrant"] = {"status": "error", "error": str(e)}

        # Neo4j
        try:
            graph_stats = self.graph.get_graph_stats()
            stats["neo4j"] = {**graph_stats, "status": "connected"}
        except Exception as e:
            stats["neo4j"] = {"status": "error", "error": str(e)}

        return stats
