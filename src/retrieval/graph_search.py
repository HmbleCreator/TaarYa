"""Knowledge graph traversal using Neo4j."""
import logging
import time
from typing import List, Optional, Dict, Any

try:
    from astropy.coordinates import SkyCoord
    import astropy.units as u
except ImportError:
    SkyCoord = None
    u = None

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
    
    def link_star_to_paper(self, source_id: str, arxiv_id: str) -> bool:
        """Create a MENTIONED_IN relationship and report whether it was newly created."""
        marker = time.time_ns()
        query = """
        MATCH (s:Star {source_id: $source_id})
        MATCH (p:Paper {arxiv_id: $arxiv_id})
        MERGE (s)-[r:MENTIONED_IN]->(p)
        ON CREATE SET r.ingested_at = $ingested_at
        RETURN r.ingested_at = $ingested_at AS created
        """
        with neo4j_conn.session() as session:
            record = session.run(
                query,
                {
                    "source_id": source_id,
                    "arxiv_id": arxiv_id,
                    "ingested_at": marker,
                },
            ).single()
            return bool(record and record["created"])
    
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
    
    def find_star_papers(
        self,
        source_id: str,
        include_cluster_context: bool = False,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find literature connected to a star.
        
        Args:
            source_id: Gaia source ID
            include_cluster_context: Include papers linked via cluster membership
            limit: Optional maximum number of returned papers
            
        Returns:
            List of paper records
        """
        if include_cluster_context:
            query = """
            CALL {
                MATCH (s:Star {source_id: $source_id})-[:MENTIONED_IN]->(p:Paper)
                RETURN p.arxiv_id AS arxiv_id,
                       p.title AS title,
                       p.abstract AS abstract,
                       p.categories AS categories,
                       p.published_date AS published_date,
                       "direct" AS link_type,
                       null AS cluster_name
                UNION
                MATCH (s:Star {source_id: $source_id})-[:MEMBER_OF]->(c:Cluster)<-[:COVERS]-(p:Paper)
                RETURN p.arxiv_id AS arxiv_id,
                       p.title AS title,
                       p.abstract AS abstract,
                       p.categories AS categories,
                       p.published_date AS published_date,
                       "cluster_context" AS link_type,
                       c.name AS cluster_name
            }
            RETURN arxiv_id, title, abstract, categories, published_date, link_type, cluster_name
            """
        else:
            query = """
            MATCH (s:Star {source_id: $source_id})-[:MENTIONED_IN]->(p:Paper)
            RETURN p.arxiv_id AS arxiv_id,
                   p.title AS title,
                   p.abstract AS abstract,
                   p.categories AS categories,
                   p.published_date AS published_date,
                   "direct" AS link_type,
                   null AS cluster_name
            """

        with neo4j_conn.session() as session:
            result = session.run(query, {"source_id": source_id})
            records = [dict(record) for record in result]

        deduped: Dict[str, Dict[str, Any]] = {}
        for record in records:
            arxiv_id = record.get("arxiv_id")
            if not arxiv_id:
                continue
            existing = deduped.get(arxiv_id)
            if existing is None:
                deduped[arxiv_id] = record
                continue
            if existing.get("link_type") != "direct" and record.get("link_type") == "direct":
                deduped[arxiv_id] = record

        ordered = sorted(
            deduped.values(),
            key=lambda record: ((record.get("published_date") or ""), record.get("arxiv_id") or ""),
            reverse=True,
        )
        if limit is not None:
            return ordered[:limit]
        return ordered

    def find_cluster_papers_for_star(
        self,
        source_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Find papers covering clusters that the given star belongs to."""
        query = """
        MATCH (s:Star {source_id: $source_id})-[:MEMBER_OF]->(c:Cluster)<-[:COVERS]-(p:Paper)
        RETURN DISTINCT p.arxiv_id AS arxiv_id,
               p.title AS title,
               p.abstract AS abstract,
               p.categories AS categories,
               p.published_date AS published_date,
               c.name AS cluster_name
        ORDER BY p.published_date DESC, p.arxiv_id
        """
        with neo4j_conn.session() as session:
            records = [dict(record) for record in session.run(query, {"source_id": source_id})]
        if limit is not None:
            return records[:limit]
        return records
    
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

    def find_star_by_name(self, name: str) -> List[Dict[str, Any]]:
        """
        Find a star in the graph by common name or alias via SIMBAD/local resolution.

        Resolution order:
          1. Exact match on Star.name property
          2. SIMBAD name → coordinate → cone search in local DB

        Args:
            name: Common name (e.g. "Sirius", "Betelgeuse")

        Returns:
            List of matching star records (usually 1)
        """
        with neo4j_conn.session() as session:
            result = session.run(
                "MATCH (s:Star) WHERE s.name = $name RETURN s.source_id AS source_id, "
                "s.ra AS ra, s.dec AS dec, s.phot_g_mean_mag AS phot_g_mean_mag, s.name AS name",
                {"name": name},
            )
            direct = [dict(r) for r in result]
        if direct:
            return direct

        coords = self._resolve_name_to_coordinates(name)
        if coords is None:
            return []
        stars = self._cone_search_near(coords["ra"], coords["dec"], radius_arcsec=10)
        return [{"source_id": s["source_id"], "ra": s["ra"], "dec": s["dec"],
                 "phot_g_mean_mag": s.get("phot_g_mean_mag"), "name": name,
                 "resolution_method": "coordinate"} for s in stars]

    def _resolve_name_to_coordinates(self, name: str) -> Optional[Dict[str, float]]:
        """Resolve a common star name to RA/Dec using local map then SIMBAD."""
        from src.utils.ner_extractor import NERExtractor
        ner = NERExtractor()
        coords = ner.resolve_local_coordinates(name)
        if coords:
            return coords
        try:
            from src.utils.simbad_validation import query_simbad_by_name
            obj = query_simbad_by_name(name)
            if not obj or not obj.get("ra") or not obj.get("dec"):
                return None
            if SkyCoord is None:
                return None
            ra_str = " ".join(str(obj["ra"]).split())
            dec_str = " ".join(str(obj["dec"]).split())
            coord = SkyCoord(ra_str, dec_str, unit=(u.hourangle, u.deg))
            return {"ra": coord.ra.deg, "dec": coord.dec.deg}
        except Exception:
            return None

    def _cone_search_near(
        self, ra: float, dec: float, radius_arcsec: float = 10
    ) -> List[Dict[str, Any]]:
        """Query local PostgreSQL for stars near RA/Dec."""
        from src.retrieval.spatial_search import SpatialSearch
        spatial = SpatialSearch()
        radius_deg = radius_arcsec / 3600.0
        return spatial.cone_search(ra=ra, dec=dec, radius=radius_deg, limit=3)

    def find_papers_about_topic(
        self,
        keyword: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Find papers semantically similar to a keyword/topic using Qdrant.

        Args:
            keyword: Search term
            limit: Maximum results

        Returns:
            List of paper records with scores
        """
        from src.retrieval.vector_search import VectorSearch

        vector = VectorSearch()
        results = vector.search_similar(keyword, limit=limit)

        papers = []
        for r in results:
            payload = r.get("payload", {})
            papers.append({
                "arxiv_id": payload.get("arxiv_id", ""),
                "title": payload.get("title", ""),
                "categories": payload.get("categories", ""),
                "score": r.get("score", 0.0)
            })

        logger.info(f"Qdrant semantic search for '{keyword}': {len(papers)} results")
        return papers
    
    def get_graph_stats(self) -> Dict[str, int]:
        """Get counts of nodes and relationships in the graph.

        Runs a lightweight liveness probe first so that a stale/dropped
        driver is re-established via the retry logic before the real
        stat queries execute.  This prevents the UI from flipping to
        'not running' after Neo4j restarts or after a long idle period.
        """

        # Liveness probe — handles three cases:
        #   1. driver is None  → background retry still in progress, raise immediately
        #   2. driver is stale → verify_connectivity() fails, reconnect and continue
        #   3. driver is fine  → proceed to stat queries
        if neo4j_conn.driver is None:
            raise RuntimeError("Neo4j driver not yet initialised (background retry in progress)")
        try:
            neo4j_conn.driver.verify_connectivity()
        except Exception:
            logger.warning("Neo4j liveness check failed — attempting reconnect...")
            neo4j_conn.close()
            neo4j_conn.connect()

        def _count(query: str) -> int:
            """Run a COUNT query and return 0 if the graph is empty."""
            with neo4j_conn.session() as session:
                record = session.run(query).single()
                return int(record["cnt"]) if record is not None else 0

        return {
            "stars":         _count("MATCH (s:Star)    RETURN count(s) AS cnt"),
            "papers":        _count("MATCH (p:Paper)   RETURN count(p) AS cnt"),
            "clusters":      _count("MATCH (c:Cluster) RETURN count(c) AS cnt"),
            "relationships": _count("MATCH ()-[r]->()  RETURN count(r) AS cnt"),
        }
