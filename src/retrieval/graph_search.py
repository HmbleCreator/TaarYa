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

    def link_stars_to_papers(self, links: List[Dict[str, Any]]) -> int:
        """Create MENTIONED_IN relationships in one Neo4j batch."""
        normalized: List[Dict[str, Any]] = []
        seen = set()
        for link in links:
            source_id = str(link.get("source_id", "")).strip()
            arxiv_id = str(link.get("arxiv_id", "")).strip()
            if not source_id or not arxiv_id:
                continue
            key = (source_id, arxiv_id)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                {
                    "source_id": source_id,
                    "arxiv_id": arxiv_id,
                    "evidence": link.get("evidence", ""),
                    "confidence": float(link.get("confidence", 1.0)),
                    "method": link.get("method", "batched"),
                }
            )

        if not normalized:
            return 0

        marker = time.time_ns()
        query = """
        UNWIND $links AS link
        MATCH (s:Star {source_id: link.source_id})
        MATCH (p:Paper {arxiv_id: link.arxiv_id})
        MERGE (s)-[r:MENTIONED_IN]->(p)
        ON CREATE SET r.ingested_at = $marker
        SET r.updated_at = $marker,
            r.evidence = CASE
                WHEN r.evidence IS NULL OR r.evidence = '' THEN link.evidence
                ELSE r.evidence
            END,
            r.confidence = CASE
                WHEN r.confidence IS NULL OR link.confidence > r.confidence THEN link.confidence
                ELSE r.confidence
            END,
            r.method = CASE
                WHEN r.method IS NULL OR r.method = '' THEN link.method
                ELSE r.method
            END
        RETURN sum(CASE WHEN r.ingested_at = $marker THEN 1 ELSE 0 END) AS created
        """
        with neo4j_conn.session() as session:
            record = session.run(query, {"links": normalized, "marker": marker}).single()
            return int(record["created"] or 0) if record else 0

    def delete_paper_star_links(self, arxiv_ids: List[str]) -> int:
        """Delete existing MENTIONED_IN links for selected papers before re-linking."""
        normalized = [str(arxiv_id).strip() for arxiv_id in arxiv_ids if str(arxiv_id).strip()]
        if not normalized:
            return 0
        query = """
        MATCH (:Star)-[r:MENTIONED_IN]->(p:Paper)
        WHERE p.arxiv_id IN $arxiv_ids
        WITH collect(r) AS rels
        FOREACH (r IN rels | DELETE r)
        RETURN size(rels) AS deleted
        """
        with neo4j_conn.session() as session:
            record = session.run(query, {"arxiv_ids": normalized}).single()
            return int(record["deleted"] or 0) if record else 0
    
    def link_star_to_cluster(self, source_id: str, cluster_name: str) -> None:
        """Create MEMBER_OF relationship between a star and a cluster."""
        query = """
        MATCH (s:Star {source_id: $source_id})
        MATCH (c:Cluster {name: $cluster_name})
        MERGE (s)-[:MEMBER_OF]->(c)
        """
        with neo4j_conn.session() as session:
            session.run(query, {"source_id": source_id, "cluster_name": cluster_name})

    def replace_star_cluster_links(self, source_id: str, cluster_names: List[str]) -> None:
        """Replace a star's cluster memberships with the supplied set."""
        unique_names = sorted({name for name in cluster_names if name})
        with neo4j_conn.session() as session:
            session.run(
                """
                MATCH (s:Star {source_id: $source_id})-[r:MEMBER_OF]->(:Cluster)
                DELETE r
                """,
                {"source_id": source_id},
            )
            for cluster_name in unique_names:
                session.run(
                    """
                    MATCH (s:Star {source_id: $source_id})
                    MATCH (c:Cluster {name: $cluster_name})
                    MERGE (s)-[:MEMBER_OF]->(c)
                    """,
                    {"source_id": source_id, "cluster_name": cluster_name},
                )
    
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

    def find_papers_for_stars(
        self,
        source_ids: List[str],
        include_cluster_context: bool = True,
        limit_per_star: int = 10,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Find literature for many stars with one Neo4j query."""
        ordered_ids: List[str] = []
        seen = set()
        for source_id in source_ids:
            sid = str(source_id).strip()
            if sid and sid not in seen:
                ordered_ids.append(sid)
                seen.add(sid)
        if not ordered_ids:
            return {}

        if include_cluster_context:
            query = """
            UNWIND $source_ids AS sid
            CALL {
                WITH sid
                MATCH (s:Star {source_id: sid})-[:MENTIONED_IN]->(p:Paper)
                RETURN p.arxiv_id AS arxiv_id,
                       p.title AS title,
                       p.abstract AS abstract,
                       p.categories AS categories,
                       p.published_date AS published_date,
                       "direct" AS link_type,
                       null AS cluster_name
                UNION
                WITH sid
                MATCH (s:Star {source_id: sid})-[:MEMBER_OF]->(c:Cluster)<-[:COVERS]-(p:Paper)
                RETURN p.arxiv_id AS arxiv_id,
                       p.title AS title,
                       p.abstract AS abstract,
                       p.categories AS categories,
                       p.published_date AS published_date,
                       "cluster_context" AS link_type,
                       c.name AS cluster_name
            }
            WITH sid AS source_id, arxiv_id, title, abstract, categories, published_date,
                 collect(link_type) AS link_types, collect(cluster_name) AS cluster_names
            WITH source_id, arxiv_id, title, abstract, categories, published_date,
                 CASE WHEN "direct" IN link_types THEN "direct" ELSE "cluster_context" END AS link_type,
                 [name IN cluster_names WHERE name IS NOT NULL][0] AS cluster_name
            ORDER BY source_id, published_date DESC, arxiv_id
            WITH source_id, collect({
                arxiv_id: arxiv_id,
                title: title,
                abstract: abstract,
                categories: categories,
                published_date: published_date,
                link_type: link_type,
                cluster_name: cluster_name
            })[..$limit_per_star] AS papers
            RETURN source_id, papers
            """
        else:
            query = """
            UNWIND $source_ids AS source_id
            MATCH (s:Star {source_id: source_id})-[:MENTIONED_IN]->(p:Paper)
            WITH source_id, p
            ORDER BY p.published_date DESC, p.arxiv_id
            WITH source_id, collect({
                arxiv_id: p.arxiv_id,
                title: p.title,
                abstract: p.abstract,
                categories: p.categories,
                published_date: p.published_date,
                link_type: "direct",
                cluster_name: null
            })[..$limit_per_star] AS papers
            RETURN source_id, papers
            """

        with neo4j_conn.session() as session:
            result = session.run(
                query,
                {"source_ids": ordered_ids, "limit_per_star": max(1, limit_per_star)},
            )
            return {record["source_id"]: list(record["papers"] or []) for record in result}

    def find_paper_stars(
        self,
        arxiv_id: str,
        limit: int = 50,
        include_cluster_context: bool = False,
    ) -> List[Dict[str, Any]]:
        """Find stars connected to a paper.

        Args:
            arxiv_id: The paper's arXiv identifier.
            limit: Maximum number of stars to return.
            include_cluster_context: Include stars in clusters covered by the paper.

        Returns:
            List of star records with source_id, ra, dec, etc.
        """
        if include_cluster_context:
            query = """
            CALL {
                MATCH (p:Paper {arxiv_id: $arxiv_id})<-[:MENTIONED_IN]-(s:Star)
                RETURN s.source_id AS source_id,
                       s.ra AS ra,
                       s.dec AS dec,
                       s.phot_g_mean_mag AS phot_g_mean_mag,
                       s.catalog AS catalog,
                       "direct" AS link_type,
                       null AS cluster_name
                UNION
                MATCH (p:Paper {arxiv_id: $arxiv_id})-[:COVERS]->(c:Cluster)<-[:MEMBER_OF]-(s:Star)
                RETURN s.source_id AS source_id,
                       s.ra AS ra,
                       s.dec AS dec,
                       s.phot_g_mean_mag AS phot_g_mean_mag,
                       s.catalog AS catalog,
                       "cluster_context" AS link_type,
                       c.name AS cluster_name
            }
            RETURN source_id, ra, dec, phot_g_mean_mag, catalog, link_type, cluster_name
            ORDER BY CASE link_type WHEN "direct" THEN 0 ELSE 1 END, phot_g_mean_mag
            LIMIT $limit
            """
        else:
            query = """
            MATCH (p:Paper {arxiv_id: $arxiv_id})<-[:MENTIONED_IN]-(s:Star)
            RETURN s.source_id AS source_id,
                   s.ra AS ra,
                   s.dec AS dec,
                   s.phot_g_mean_mag AS phot_g_mean_mag,
                   s.catalog AS catalog,
                   "direct" AS link_type,
                   null AS cluster_name
            LIMIT $limit
            """
        with neo4j_conn.session() as session:
            return [dict(record) for record in session.run(
                query, {"arxiv_id": arxiv_id, "limit": limit}
            )]

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
        Find stars that share a physical cluster with the given star.
        
        Args:
            source_id: Starting star's Gaia source ID
            max_hops: Ignored (kept for API compat); always 1-hop cluster
            limit: Maximum results
            
        Returns:
            List of co-cluster member stars with cluster context
        """
        # Use explicit cluster-membership traversal. The old [*1..N]
        # wildcard matched any relationship type and returned thousands
        # of unrelated stars, degrading Full Hybrid precision.
        query = """
        MATCH (s1:Star {source_id: $source_id})-[:MEMBER_OF]->(c:Cluster)<-[:MEMBER_OF]-(s2:Star)
        WHERE s1 <> s2
        WITH DISTINCT s2, c.name AS cluster_name
        RETURN s2.source_id AS source_id, s2.ra AS ra, s2.dec AS dec,
               s2.phot_g_mean_mag AS phot_g_mean_mag, cluster_name,
               1 AS distance
        ORDER BY s2.phot_g_mean_mag
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
            "mentioned_in":  _count("MATCH ()-[r:MENTIONED_IN]->() RETURN count(r) AS cnt"),
            "member_of":     _count("MATCH ()-[r:MEMBER_OF]->() RETURN count(r) AS cnt"),
            "covers":        _count("MATCH ()-[r:COVERS]->() RETURN count(r) AS cnt"),
        }
