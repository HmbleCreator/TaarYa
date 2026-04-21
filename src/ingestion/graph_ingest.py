"""
Ingest graph data from PostgreSQL and Qdrant into Neo4j.
"""

import logging
import re
from typing import Any, Dict, List

from qdrant_client import QdrantClient

from src.config import settings
from src.database import neo4j_conn, postgres_conn, qdrant_conn
from src.retrieval.graph_search import GraphSearch
from src.retrieval.spatial_search import SpatialSearch
from src.retrieval.vector_search import VectorSearch
from src.models import Region
from sqlalchemy import select, text
from src.utils.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def extract_gaia_ids(text: str) -> List[str]:
    """Extract Gaia Source IDs from text using regex.
    
    Gaia IDs are typically 19-digit integers.
    """
    if not text:
        return []
    # Match long integers that look like Gaia IDs (18-20 digits)
    pattern = re.compile(r'\b\d{18,20}\b')
    return list(set(pattern.findall(text)))


def link_stars_to_papers_semantic(graph: GraphSearch) -> int:
    """
    Analyze paper abstracts for Gaia Source IDs and create MENTIONED_IN links.
    
    This is a higher-fidelity linking method than string matching.
    """
    with neo4j_conn.session() as session:
        # Get all papers and their abstracts
        papers = session.run("MATCH (p:Paper) RETURN p.arxiv_id as id, p.abstract as abstract, p.title as title")
        
        links_created = 0
        for record in papers:
            arxiv_id = record["id"]
            content = f"{record['title']} {record['abstract']}"
            
            source_ids = extract_gaia_ids(content)
            for sid in source_ids:
                # Verify if this star exists in our database before linking in graph
                # (Optional: we could create the star node even if not in Postgres)
                graph.link_star_to_paper(sid, arxiv_id)
                links_created += 1
                logger.info(f"Semantically linked star {sid} to paper {arxiv_id}")
                
        return links_created


def seed_clusters(graph: GraphSearch) -> int:
    """Read from regions table and create Cluster nodes."""
    postgres_conn.connect()
    with postgres_conn.session() as session:
        regions = session.execute(select(Region)).scalars().all()

    count = 0
    for r in regions:
        graph.create_cluster_node(name=r.name, ra=r.ra, dec=r.dec)
        count += 1
        logger.info(f"Created cluster: {r.name}")

    logger.info(f"Seeded {count} clusters")
    return count


def seed_stars(graph: GraphSearch, spatial: SpatialSearch) -> int:
    """Read stars from PostgreSQL and create Star nodes in Neo4j."""
    postgres_conn.connect()

    # Get total count
    with postgres_conn.session() as session:
        total = session.execute(text("SELECT COUNT(*) FROM stars")).scalar()

    logger.info(f"Total stars in PostgreSQL: {total}")

    count = 0
    offset = 0

    while offset < total:
        with postgres_conn.session() as session:
            stars = session.execute(
                text(
                    f"SELECT source_id, ra, dec, phot_g_mean_mag, catalog_source FROM stars ORDER BY id LIMIT {BATCH_SIZE} OFFSET {offset}"
                )
            ).fetchall()

        for star in stars:
            star_data = {
                "source_id": star[0],
                "ra": star[1],
                "dec": star[2],
                "phot_g_mean_mag": star[3],
                "catalog_source": star[4],
            }
            graph.create_star_node(star_data)
            count += 1

        logger.info(f"Inserted stars {offset} to {offset + len(stars)}")
        offset += BATCH_SIZE

    logger.info(f"Seeded {count} star nodes")
    return count


def link_stars_to_clusters(graph: GraphSearch, spatial: SpatialSearch) -> int:
    """For each cluster, find stars in the region and link them."""
    postgres_conn.connect()
    with postgres_conn.session() as session:
        regions = session.execute(select(Region)).scalars().all()

    total_links = 0
    for region in regions:
        # Count stars in this region
        star_count = spatial.count_in_region(region.ra, region.dec, region.radius_deg)
        logger.info(f"Cluster {region.name}: {star_count} stars in region")

        # Get stars in this region
        stars = spatial.cone_search(
            region.ra, region.dec, region.radius_deg, limit=star_count
        )

        links = 0
        for star in stars:
            graph.link_star_to_cluster(star["source_id"], region.name)
            links += 1

        logger.info(f"Linked {links} stars to cluster {region.name}")
        total_links += links

    logger.info(f"Created {total_links} MEMBER_OF relationships")
    return total_links


def seed_papers(graph: GraphSearch) -> int:
    """Read papers from Qdrant and create Paper nodes in Neo4j."""
    client = qdrant_conn.get_client()

    # Get all papers using scroll
    all_papers = []
    offset = None

    while True:
        results, offset = client.scroll(
            collection_name="papers",
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        all_papers.extend(results)
        if not offset:
            break

    logger.info(f"Found {len(all_papers)} papers in Qdrant")

    count = 0
    for point in all_papers:
        payload = point.payload
        paper_data = {
            "arxiv_id": payload.get("arxiv_id", ""),
            "title": payload.get("title", ""),
            "abstract": payload.get("abstract", ""),
            "categories": payload.get("categories", ""),
            "published_date": payload.get("published", ""),
        }
        graph.create_paper_node(paper_data)
        count += 1

    logger.info(f"Seeded {count} paper nodes")
    return count


def link_papers_to_clusters(graph: GraphSearch) -> int:
    """Match paper title/categories against cluster names."""
    postgres_conn.connect()
    with postgres_conn.session() as session:
        regions = session.execute(select(Region)).scalars().all()

    cluster_names = [r.name.lower() for r in regions]

    # Also add common aliases
    aliases = {
        "hyades": ["hyades", "melotte 25", "collinder 50"],
        "pleiades": ["pleiades", "melotte 45", "m45", "seven sisters"],
        "orion ob1": ["orion ob1", "orion ob", "orion association"],
        "lmc (large magellanic cloud)": ["lmc", "large magellanic cloud", "nubecula major"],
        "smc (small magellanic cloud)": ["smc", "small magellanic cloud", "nubecula minor"],
        "omega centauri": ["omega centauri", "ngc 5139", "ω cen"],
        "galactic center": ["galactic center", "sagittarius a*", "sgr a*"],
    }

    links = 0

    for region in regions:
        name_lower = region.name.lower()
        search_terms = [name_lower] + aliases.get(name_lower, [])

        # Find papers that mention this cluster
        query = """
        MATCH (p:Paper)
        WHERE toLower(p.title) CONTAINS $term 
           OR toLower(toString(p.categories)) CONTAINS $term
           OR toLower(p.abstract) CONTAINS $term
        MATCH (c:Cluster {name: $cluster_name})
        MERGE (p)-[:COVERS]->(c)
        RETURN count(*) as cnt
        """

        with neo4j_conn.session() as session:
            for term in search_terms:
                result = session.run(query, {"term": term, "cluster_name": region.name})
                try:
                    record = result.single()
                    cnt = record["cnt"] if record else 0
                except Exception:
                    cnt = 0
                if cnt > 0:
                    logger.info(
                        f"Linked {cnt} papers to cluster {region.name} via '{term}'"
                    )
                    links += cnt
                    break

    logger.info(f"Created {links} COVERS relationships")
    return links


def link_papers_to_clusters_semantic(graph: GraphSearch, vector: VectorSearch) -> int:
    """Link papers to clusters based on semantic similarity."""
    postgres_conn.connect()
    with postgres_conn.session() as session:
        regions = session.execute(select(Region)).scalars().all()

    links = 0
    for region in regions:
        # Search for papers semantically related to cluster name
        results = vector.search_similar(query_text=region.name, limit=10)
        
        for r in results:
            arxiv_id = r["payload"].get("arxiv_id")
            if arxiv_id:
                # Create COVERS relationship
                query = """
                MATCH (p:Paper {arxiv_id: $arxiv_id})
                MATCH (c:Cluster {name: $cluster_name})
                MERGE (p)-[:COVERS]->(c)
                RETURN count(*) as cnt
                """
                with neo4j_conn.session() as session:
                    result = session.run(query, {"arxiv_id": arxiv_id, "cluster_name": region.name})
                    links += 1
        
        logger.info(f"Semantically linked papers to cluster {region.name}")
        
    return links


def ingest_graph():
    """Main ingestion pipeline."""
    logger.info("Starting graph ingestion...")

    graph = GraphSearch()
    spatial = SpatialSearch()
    vector = VectorSearch()

    # Step 1: Seed clusters
    logger.info("=== Step 1: Seeding clusters ===")
    seed_clusters(graph)

    # Step 2: Seed stars
    logger.info("=== Step 2: Seeding stars ===")
    seed_stars(graph, spatial)

    # Step 3: Link stars to clusters
    logger.info("=== Step 3: Linking stars to clusters ===")
    link_stars_to_clusters(graph, spatial)

    # Step 4: Seed papers
    logger.info("=== Step 4: Seeding papers ===")
    seed_papers(graph)

    # Step 5: Link papers to clusters (Text Match)
    logger.info("=== Step 5: Linking papers to clusters (Text Match) ===")
    link_papers_to_clusters(graph)
    
    # Step 5b: Link papers to clusters (Semantic Match)
    logger.info("=== Step 5b: Linking papers to clusters (Semantic Match) ===")
    link_papers_to_clusters_semantic(graph, vector)

    # Step 6: Link stars to papers semantically (NEW)
    logger.info("=== Step 6: Linking stars to papers semantically ===")
    link_stars_to_papers_semantic(graph)

    logger.info("Graph ingestion complete!")


if __name__ == "__main__":
    neo4j_conn.connect()
    ingest_graph()
    neo4j_conn.close()
