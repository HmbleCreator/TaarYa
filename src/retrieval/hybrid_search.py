"""Hybrid search combining spatial, vector, and graph backends."""
import logging
from typing import List, Optional, Dict, Any
from enum import Enum

from src.retrieval.spatial_search import SpatialSearch
from src.retrieval.vector_search import VectorSearch
from src.retrieval.graph_search import GraphSearch

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
    
    def __init__(self):
        self.spatial = SpatialSearch()
        self.vector = VectorSearch()
        self.graph = GraphSearch()
    
    def cone_search_with_context(
        self,
        ra: float,
        dec: float,
        radius_deg: float,
        limit: int = 50,
        enrich_with_graph: bool = True
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
        stars = self.spatial.cone_search(ra, dec, radius_deg, limit)
        
        result = {
            "query": {
                "type": "cone_search",
                "ra": ra,
                "dec": dec,
                "radius_deg": radius_deg
            },
            "count": len(stars),
            "stars": stars,
        }
        
        # Step 2: Enrich with graph data
        if enrich_with_graph and stars:
            papers_found = []
            for star in stars[:10]:  # Limit graph lookups for performance
                star_papers = self.graph.find_star_papers(star["source_id"])
                if star_papers:
                    papers_found.append({
                        "source_id": star["source_id"],
                        "papers": star_papers
                    })
            
            result["related_papers"] = papers_found
        
        return result
    
    def semantic_search_with_sources(
        self,
        query_text: str,
        collection: Optional[str] = None,
        limit: int = 10
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
            "query": {
                "type": "semantic_search",
                "text": query_text
            },
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
                    stars_mentioned.append({
                        "arxiv_id": arxiv_id,
                        "stars": with_stars
                    })
        
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
        limit: int = 20
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
            stars = self.spatial.cone_search(ra, dec, radius_deg, limit)
            results["spatial"] = {
                "count": len(stars),
                "stars": stars
            }
            results["backends_used"].append("spatial")
        
        # Semantic search
        if query_text:
            papers = self.vector.search_similar(query_text, limit=limit)
            results["semantic"] = {
                "count": len(papers),
                "papers": papers
            }
            results["backends_used"].append("semantic")
        
        # Star lookup
        if source_id:
            star = self.spatial.coordinate_lookup(source_id)
            papers = self.graph.find_star_papers(source_id)
            related = self.graph.find_related_stars(source_id)
            
            results["star_detail"] = {
                "star": star,
                "papers": papers,
                "related_stars": related[:10]
            }
            results["backends_used"].append("graph")
        
        return results
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Get statistics from all backends."""
        stats = {}
        
        # PostgreSQL
        try:
            count = self.spatial.count_in_region(0, 0, 360)
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
