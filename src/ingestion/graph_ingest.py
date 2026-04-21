"""
Ingest graph data from PostgreSQL and Qdrant into Neo4j.
"""

import logging
import re
from typing import Any, Dict, List

from src.config import settings
from src.database import neo4j_conn, postgres_conn, qdrant_conn
from src.retrieval.graph_search import GraphSearch
from src.retrieval.spatial_search import SpatialSearch
from src.retrieval.vector_search import VectorSearch
from src.utils.ner_extractor import NERExtractor
from src.utils.logger import setup_logging
from src.models import Region
from sqlalchemy import select, text

setup_logging()
logger = logging.getLogger(__name__)

ALIASED_CLUSTERS = {
    "hyades": ["hyades", "melotte 25", "collinder 50", "cr 50"],
    "pleiades": ["pleiades", "melotte 45", "m45", "seven sisters", "ngc 1432"],
    "orion ob1": ["orion ob1", "orion ob", "orion association", "orion moving group"],
    "coma berenices": ["coma berenices", "coma ber", "melotte 111", "ngc 5024", "ngc 5053"],
    "praesepe": ["praesepe", "m44", "ngc 2632", "beehive cluster", "melotte 121"],
    "ngc 2516": ["ngc 2516", "ngc2516", "spotted cluster"],
    "alpha per": ["alpha per", "alpha persei", "ngc 7092", "m34"],
    "ic 2391": ["ic 2391", "ic2391", "omicron velorum cluster", "sharpless 308"],
    "lmc": ["lmc", "large magellanic cloud", "nubecula major", "ngc 292"],
    "smc": ["smc", "small magellanic cloud", "nubecula minor", "ngc 292"],
    "omega centauri": ["omega centauri", "ngc 5139", "omega cen", "ω cen"],
    "galactic center": ["galactic center", "sagittarius a*", "sgr a*", "galactic centre"],
}

BATCH_SIZE = 500

# Canonical cluster definitions with J2000 coordinates and typical radii.
# Coordinates from: Gaia Collaboration (2018), Kharchenko+ (2013), WEBDA, Simbad.
# radii are conservative in degrees to capture field contamination without
# including neighbouring clusters.
KNOWN_CLUSTERS = [
    # name, ra_deg, dec_deg, radius_deg, description
    ("Hyades",           66.75,   15.87,  5.5,  "Nearest open cluster, ~45 pc, ~300 Myr"),
    ("Pleiades",         56.75,   24.12,  2.0,  "M45, ~120 pc, ~125 Myr, classic YMG"),
    ("Orion OB1",        83.82,   -5.39,  4.0,  "Orion OB1 association, ~400 pc, ~10 Myr"),
    ("Coma Berenices",  185.00,   25.83,  4.0,  "Melotte 111, ~280 pc, ~400 Myr, nearest rich OC"),
    ("Praesepe",        130.05,   19.52,  2.5,  "M44 / NGC 2632, ~180 pc, ~600 Myr, beehive"),
    ("NGC 2516",        119.71,  -60.85,  0.5,  "Southern open cluster, ~400 pc, ~120 Myr"),
    ("Alpha Persei",    51.08,    49.86,  2.0,  "NGC 7092 / M34, ~475 pc, ~200 Myr"),
    ("IC 2391",         130.07,  -52.97,  0.3,  "Omicron Velorum cluster, ~180 pc, ~50 Myr"),
]


def extract_gaia_ids(text: str) -> List[str]:
    """Extract Gaia Source IDs from text using multi-strategy matching.

    Strategies (in priority order):
      1. Explicit Gaia DR2/DR3 prefix: 'Gaia DR3 1234567890123456789'
      2. 'Gaia source [id]' pattern
      3. Bare 18-20 digit integers that appear near the word 'Gaia'

    Strategy 3 uses a proximity heuristic (within 200 chars of 'Gaia')
    to reduce false-positive matches on random long integers.
    """
    if not text:
        return []

    ids: List[str] = []
    seen: set = set()

    # Strategy 1 & 2: explicit Gaia prefix (handled by NER module)
    explicit_pattern = re.compile(
        r"\bGaia(?:\s+DR[23])?(?:\s+source(?:\s*id)?)?\s+(\d{18,20})\b",
        re.IGNORECASE,
    )
    for match in explicit_pattern.finditer(text):
        gid = match.group(1)
        if gid not in seen:
            ids.append(gid)
            seen.add(gid)

    # Strategy 3: bare long integers near the word 'Gaia'
    bare_pattern = re.compile(r"\b(\d{18,20})\b")
    gaia_mentions = [m.start() for m in re.finditer(r"\bGaia\b", text, re.IGNORECASE)]
    for match in bare_pattern.finditer(text):
        gid = match.group(1)
        if gid in seen:
            continue
        # Only accept if within 200 chars of a 'Gaia' mention
        pos = match.start()
        if any(abs(pos - gm) < 200 for gm in gaia_mentions):
            ids.append(gid)
            seen.add(gid)

    return ids


def extract_catalog_identifiers(text: str) -> List[str]:
    """Extract non-Gaia catalog identifiers (HD, HIP, TYC, 2MASS, etc.).

    These can be resolved to Gaia source IDs via SIMBAD or local coordinate maps.
    """
    if not text:
        return []

    identifiers: List[str] = []
    seen: set = set()

    patterns = [
        re.compile(r"\b(HD\s*\d{1,6})\b", re.IGNORECASE),
        re.compile(r"\b(HIP\s*\d{1,6})\b", re.IGNORECASE),
        re.compile(r"\b(TYC\s*\d{4}-\d{1,5}-\d)\b", re.IGNORECASE),
        re.compile(r"\b(2MASS\s+J\d{6,8}[+-]\d{6,8})\b", re.IGNORECASE),
        re.compile(r"\b(HR\s*\d{1,5})\b", re.IGNORECASE),
        re.compile(r"\b(TIC\s*\d{1,10})\b", re.IGNORECASE),
        re.compile(r"\b(GJ\s*\d{1,4}[A-Z]?)\b", re.IGNORECASE),
        re.compile(r"\b(LHS\s*\d{1,5})\b", re.IGNORECASE),
    ]

    for pattern in patterns:
        for match in pattern.finditer(text):
            ident = match.group(1).strip()
            key = ident.upper().replace(" ", "")
            if key not in seen:
                identifiers.append(ident)
                seen.add(key)

    return identifiers


def link_stars_to_papers_semantic(graph: GraphSearch) -> int:
    """
    Analyze paper abstracts for Gaia Source IDs and catalog identifiers,
    then create MENTIONED_IN links in the graph.

    Multi-strategy approach:
      1. Direct Gaia ID extraction (high precision)
      2. Catalog identifier extraction (HD/HIP/TYC/2MASS) with NER resolution
    """
    with neo4j_conn.session() as session:
        papers = session.run(
            "MATCH (p:Paper) RETURN p.arxiv_id as id, p.abstract as abstract, p.title as title"
        )
        records = list(papers)

    logger.info(f"Linking {len(records)} papers to stars (multi-strategy)...")

    links_created = 0
    gaia_direct = 0
    catalog_resolved = 0

    for record in records:
        arxiv_id = record["id"]
        content = f"{record['title']} {record['abstract']}"

        # Strategy 1: Direct Gaia IDs
        source_ids = extract_gaia_ids(content)
        for sid in source_ids:
            if graph.link_star_to_paper(sid, arxiv_id):
                links_created += 1
                gaia_direct += 1

        # Strategy 2: Catalog identifiers → NER resolution
        cat_ids = extract_catalog_identifiers(content)
        if cat_ids:
            try:
                ner = NERExtractor()
                resolved = ner.resolve_to_source_ids(cat_ids[:5])  # Limit per paper
                for sid in resolved:
                    if graph.link_star_to_paper(sid, arxiv_id):
                        links_created += 1
                        catalog_resolved += 1
            except Exception as e:
                logger.debug(f"NER resolution failed for {arxiv_id}: {e}")

    logger.info(
        f"Star-paper linking complete: {links_created} total links "
        f"(Gaia direct: {gaia_direct}, catalog resolved: {catalog_resolved})"
    )
    return links_created


def link_stars_to_papers_ner(graph: GraphSearch) -> int:
    """
    Use deterministic extraction plus optional SIMBAD resolution.

    This makes the paper-linking pass reproducible and removes the missing
    agent dependency from graph ingestion.
    """
    ner = NERExtractor()
    links_created = 0
    
    with neo4j_conn.session() as session:
        # Get all papers
        papers = session.run("MATCH (p:Paper) RETURN p.arxiv_id as id, p.abstract as abstract, p.title as title")
        
        # Convert to list to avoid session issues during external name resolution
        records = list(papers)
        
        logger.info(f"Starting NER linking for {len(records)} papers...")
        
        for record in records:
            arxiv_id = record["id"]
            content = f"{record['title']} {record['abstract']}"
            
            source_ids = ner.process_text(content)
            
            for sid in source_ids:
                if graph.link_star_to_paper(sid, arxiv_id):
                    links_created += 1
                    logger.info(f"NER linked star {sid} to paper {arxiv_id}")
                
    return links_created


def seed_clusters(graph: GraphSearch) -> int:
    """Upsert all KNOWN_CLUSTERS into PostgreSQL regions table, then create Neo4j Cluster nodes."""
    postgres_conn.connect()

    # Step 1: upsert canonical clusters into PostgreSQL
    for name, ra, dec, radius, _desc in KNOWN_CLUSTERS:
        stmt = text("""
            INSERT INTO regions (name, ra, dec, radius_deg, star_count, ingested_at)
            VALUES (:name, :ra, :dec, :radius, 0, NOW())
            ON CONFLICT (name) DO UPDATE SET
                ra = EXCLUDED.ra,
                dec = EXCLUDED.dec,
                radius_deg = EXCLUDED.radius_deg
        """)
        with postgres_conn.session() as session:
            session.execute(stmt, {"name": name, "ra": ra, "dec": dec, "radius": radius})
            session.commit()
        logger.info(f"Upserted region: {name} (RA={ra}, Dec={dec}, r={radius}°)")

    # Step 2: seed all regions (original table + KNOWN_CLUSTERS) into Neo4j
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
    links = 0

    for region in regions:
        name_lower = region.name.lower()
        search_terms = [name_lower] + ALIASED_CLUSTERS.get(name_lower, [])

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

    # Step 6: Link stars to papers semantically
    logger.info("=== Step 6: Linking stars to papers semantically (Regex) ===")
    link_stars_to_papers_semantic(graph)

    # Step 7: Link stars to papers via NER (NEW)
    logger.info("=== Step 7: Linking stars to papers via NER ===")
    link_stars_to_papers_ner(graph)

    logger.info("Graph ingestion complete!")


if __name__ == "__main__":
    neo4j_conn.connect()
    ingest_graph()
    neo4j_conn.close()
