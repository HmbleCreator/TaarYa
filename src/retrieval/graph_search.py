"""Knowledge graph traversal using Neo4j."""
import logging
from typing import List, Optional, Dict, Any

from src.database import neo4j_conn

logger = logging.getLogger(__name__)


class GraphSearch:
    """Neo4j-powered knowledge graph queries for astronomical entities."""
    
    # --- Schema Setup ---
    
    def setup_schema(self) -> None:
        """Create indexes and constraints for the knowledge graph."""
        constraints = [
            "CREATE CONSTRAINT star_source_id IF NOT EXISTS FOR (s:Star) REQUIRE s.source_id IS UNIQUE",
            "CREATE CONSTRAINT paper_arxiv_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.arxiv_id IS UNIQUE",
            "CREATE CONSTRAINT cluster_name IF NOT EXISTS FOR (c:Cluster) REQUIRE c.name IS UNIQUE",
        ]
        indexes = [
            "CREATE INDEX star_ra_dec IF NOT EXISTS FOR (s:Star) ON (s.ra, s.dec)",
        ]
        
        with neo4j_conn.session() as session:
            for stmt in constraints + indexes:
                try:
                    session.run(stmt)
                except Exception as e:
                    logger.debug(f"Schema statement skipped: {e}")
            
        logger.info("Neo4j schema initialized")
    
    # --- Node Creation ---
    
    def create_star_node(self, star_data: Dict[str, Any]) -> None:
        """
        Create or update a Star node in the graph.
        
        Args:
            star_data: Dict with source_id, ra, dec, and optional properties
        """
        query = """
        MERGE (s:Star {source_id: $source_id})
        SET s.ra = $ra,
            s.dec = $dec,
            s.phot_g_mean_mag = $mag,
            s.catalog = $catalog
        """
        
        with neo4j_conn.session() as session:
            session.run(query, {
                "source_id": star_data["source_id"],
                "ra": star_data.get("ra"),
                "dec": star_data.get("dec"),
                "mag": star_data.get("phot_g_mean_mag"),
                "catalog": star_data.get("catalog_source", "GAIA"),
            })
    
    def create_paper_node(self, paper_data: Dict[str, Any]) -> None:
        """
        Create or update a Paper node in the graph.
        
        Args:
            paper_data: Dict with arxiv_id, title, and optional properties
        """
        query = """
        MERGE (p:Paper {arxiv_id: $arxiv_id})
        SET p.title = $title,
            p.abstract = $abstract,
            p.categories = $categories,
            p.published_date = $published_date
        """
        
        with neo4j_conn.session() as session:
            session.run(query, {
                "arxiv_id": paper_data["arxiv_id"],
                "title": paper_data.get("title", ""),
                "abstract": paper_data.get("abstract", ""),
                "categories": paper_data.get("categories", ""),
                "published_date": paper_data.get("published_date", ""),
            })
    
    def create_cluster_node(self, name: str, ra: float = None, dec: float = None) -> None:
        """Create or update a Cluster node."""
        query = """
        MERGE (c:Cluster {name: $name})
        SET c.ra = $ra, c.dec = $dec
        """
        with neo4j_conn.session() as session:
            session.run(query, {"name": name, "ra": ra, "dec": dec})
    
    # --- Relationship Creation ---
    
    def link_star_to_paper(self, source_id: str, arxiv_id: str) -> None:
        """Create MENTIONED_IN relationship between a star and a paper."""
        query = """
        MATCH (s:Star {source_id: $source_id})
        MATCH (p:Paper {arxiv_id: $arxiv_id})
        MERGE (s)-[:MENTIONED_IN]->(p)
        """
        with neo4j_conn.session() as session:
            session.run(query, {"source_id": source_id, "arxiv_id": arxiv_id})
    
    def link_star_to_cluster(self, source_id: str, cluster_name: str) -> None:
        """Create MEMBER_OF relationship between a star and a cluster."""
        query = """
        MATCH (s:Star {source_id: $source_id})
        MATCH (c:Cluster {name: $cluster_name})
        MERGE (s)-[:MEMBER_OF]->(c)
        """
        with neo4j_conn.session() as session:
            session.run(query, {"source_id": source_id, "cluster_name": cluster_name})
    
    def link_paper_cites(self, citing_id: str, cited_id: str) -> None:
        """Create CITES relationship between papers."""
        query = """
        MATCH (a:Paper {arxiv_id: $citing})
        MATCH (b:Paper {arxiv_id: $cited})
        MERGE (a)-[:CITES]->(b)
        """
        with neo4j_conn.session() as session:
            session.run(query, {"citing": citing_id, "cited": cited_id})
    
    # --- Queries ---
    
    def find_star_papers(self, source_id: str) -> List[Dict[str, Any]]:
        """
        Find all papers that mention a star.
        
        Args:
            source_id: Gaia source ID
            
        Returns:
            List of paper records
        """
        query = """
        MATCH (s:Star {source_id: $source_id})-[:MENTIONED_IN]->(p:Paper)
        RETURN p.arxiv_id AS arxiv_id, p.title AS title,
               p.categories AS categories, p.published_date AS published_date
        ORDER BY p.published_date DESC
        """
        
        with neo4j_conn.session() as session:
            result = session.run(query, {"source_id": source_id})
            return [dict(record) for record in result]
    
    def find_related_stars(
        self,
        source_id: str,
        max_hops: int = 2,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Find stars connected via shared papers or clusters.
        
        Args:
            source_id: Starting star's Gaia source ID
            max_hops: Maximum relationship depth (1-3)
            limit: Maximum results
            
        Returns:
            List of related stars with connection path info
        """
        max_hops = min(max_hops, 3)  # Safety cap
        
        query = f"""
        MATCH (s1:Star {{source_id: $source_id}})
        MATCH path = (s1)-[*1..{max_hops}]-(s2:Star)
        WHERE s1 <> s2
        WITH DISTINCT s2, length(path) AS distance
        RETURN s2.source_id AS source_id, s2.ra AS ra, s2.dec AS dec,
               s2.phot_g_mean_mag AS phot_g_mean_mag, distance
        ORDER BY distance, s2.phot_g_mean_mag
        LIMIT $limit
        """
        
        with neo4j_conn.session() as session:
            result = session.run(query, {"source_id": source_id, "limit": limit})
            return [dict(record) for record in result]
    
    def find_cluster_members(
        self,
        cluster_name: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Find all stars that are members of a cluster.
        
        Args:
            cluster_name: Name of the cluster
            limit: Maximum results
            
        Returns:
            List of star records
        """
        query = """
        MATCH (s:Star)-[:MEMBER_OF]->(c:Cluster {name: $cluster_name})
        RETURN s.source_id AS source_id, s.ra AS ra, s.dec AS dec,
               s.phot_g_mean_mag AS phot_g_mean_mag
        ORDER BY s.phot_g_mean_mag
        LIMIT $limit
        """
        
        with neo4j_conn.session() as session:
            result = session.run(query, {"cluster_name": cluster_name, "limit": limit})
            return [dict(record) for record in result]
    
    def find_papers_about_topic(
        self,
        keyword: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Find papers whose title or abstract contains a keyword.
        
        Args:
            keyword: Search term
            limit: Maximum results
            
        Returns:
            List of paper records
        """
        query = """
        MATCH (p:Paper)
        WHERE toLower(p.title) CONTAINS toLower($keyword)
           OR toLower(p.abstract) CONTAINS toLower($keyword)
        RETURN p.arxiv_id AS arxiv_id, p.title AS title,
               p.categories AS categories
        LIMIT $limit
        """
        
        with neo4j_conn.session() as session:
            result = session.run(query, {"keyword": keyword, "limit": limit})
            return [dict(record) for record in result]
    
    def get_graph_stats(self) -> Dict[str, int]:
        """Get counts of nodes and relationships in the graph."""
        with neo4j_conn.session() as session:
            stars = session.run("MATCH (s:Star) RETURN count(s) AS cnt").single()["cnt"]
            papers = session.run("MATCH (p:Paper) RETURN count(p) AS cnt").single()["cnt"]
            clusters = session.run("MATCH (c:Cluster) RETURN count(c) AS cnt").single()["cnt"]
            rels = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt").single()["cnt"]
            
            return {
                "stars": stars,
                "papers": papers,
                "clusters": clusters,
                "relationships": rels
            }
