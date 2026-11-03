"""
Reconcile and synchronize datastores across PostgreSQL, Neo4j, and Qdrant.

Ensures complete parity:
  1. Stars: Syncs un-reconciled stars from PostgreSQL into Neo4j Star nodes.
  2. Papers: Vectorizes and upserts un-embedded papers from Neo4j into Qdrant.
  3. Verifies zero gaps between primary stores.
"""

from __future__ import annotations
import os
import sys
import uuid
import datetime
from typing import Dict, List, Any
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg2
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from src.retrieval.vector_search import VectorSearch


def reconcile_stars(pg_conn, neo_driver) -> dict:
    print("\n--- Reconciling Stars (PostgreSQL -> Neo4j) ---")
    with pg_conn.cursor() as cur:
        cur.execute("SELECT source_id, ra, dec, phot_g_mean_mag, catalog_source FROM stars;")
        pg_rows = cur.fetchall()
    
    pg_stars = {r[0]: dict(source_id=r[0], ra=r[1], dec=r[2], phot_g_mean_mag=r[3], catalog=r[4]) for r in pg_rows}
    print(f"Total stars in PostgreSQL: {len(pg_stars)}")

    with neo_driver.session() as session:
        res = session.run("MATCH (s:Star) RETURN s.source_id")
        neo_ids = {str(r["s.source_id"]) for r in res}
    print(f"Total Star nodes in Neo4j before sync: {len(neo_ids)}")

    missing_in_neo = [pg_stars[sid] for sid in pg_stars if sid not in neo_ids]
    print(f"Stars in PostgreSQL missing in Neo4j: {len(missing_in_neo)}")

    if missing_in_neo:
        batch_size = 500
        with neo_driver.session() as session:
            for i in range(0, len(missing_in_neo), batch_size):
                batch = missing_in_neo[i:i + batch_size]
                query = """
                UNWIND $batch AS star
                MERGE (s:Star {source_id: star.source_id})
                SET s.ra = star.ra,
                    s.dec = star.dec,
                    s.phot_g_mean_mag = star.phot_g_mean_mag,
                    s.catalog = star.catalog
                """
                session.run(query, {"batch": batch})
        print(f"Successfully upserted {len(missing_in_neo)} Star nodes into Neo4j.")

    with neo_driver.session() as session:
        final_cnt = session.run("MATCH (s:Star) RETURN count(s)").single()[0]
    print(f"Final Star nodes in Neo4j: {final_cnt}")
    return {"postgres_stars": len(pg_stars), "neo4j_stars_before": len(neo_ids), "neo4j_stars_after": final_cnt, "added": len(missing_in_neo)}


def reconcile_papers(neo_driver, qdrant_client, vs: VectorSearch) -> dict:
    print("\n--- Reconciling Papers (Neo4j -> Qdrant) ---")
    with neo_driver.session() as session:
        res = session.run("MATCH (p:Paper) RETURN p.arxiv_id, p.title, p.abstract, p.categories, p.published_date")
        neo_papers = {}
        for r in res:
            aid = str(r["p.arxiv_id"] or "")
            if aid:
                neo_papers[aid] = dict(
                    arxiv_id=aid,
                    title=r["p.title"] or "",
                    abstract=r["p.abstract"] or "",
                    categories=r["p.categories"] if isinstance(r["p.categories"], list) else [str(r["p.categories"])] if r["p.categories"] else [],
                    published=str(r["p.published_date"] or "")
                )
    print(f"Total Paper nodes in Neo4j: {len(neo_papers)}")

    qdrant_points, _ = qdrant_client.scroll(collection_name="papers", limit=10000, with_payload=True, with_vectors=False)
    qdrant_ids = set()
    for p in qdrant_points:
        aid = p.payload.get("arxiv_id") or p.payload.get("paper_id") or str(p.id)
        qdrant_ids.add(str(aid))
    print(f"Total papers in Qdrant before sync: {len(qdrant_ids)}")

    missing_in_qdrant = [neo_papers[aid] for aid in neo_papers if aid not in qdrant_ids]
    print(f"Papers in Neo4j missing in Qdrant: {len(missing_in_qdrant)}")

    if missing_in_qdrant:
        texts_to_embed = [f"{p['title']}. {p['abstract']}" for p in missing_in_qdrant]
        print(f"Generating embeddings for {len(texts_to_embed)} papers...")
        vectors = vs.embed_batch(texts_to_embed)

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        points = []
        for p, vec in zip(missing_in_qdrant, vectors):
            pt_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, p["arxiv_id"]))
            payload = {
                "title": p["title"],
                "abstract": p["abstract"],
                "arxiv_id": p["arxiv_id"],
                "categories": p["categories"],
                "published": p["published"],
                "authors": [],
                "query_category": "Reconciled",
                "ingested_at": now_iso
            }
            points.append(PointStruct(id=pt_id, vector=vec, payload=payload))

        batch_size = 50
        for i in range(0, len(points), batch_size):
            chunk = points[i:i + batch_size]
            qdrant_client.upsert(collection_name="papers", points=chunk)
        print(f"Successfully upserted {len(points)} paper vectors into Qdrant.")

    info = qdrant_client.get_collection("papers")
    final_count = info.points_count
    print(f"Final papers in Qdrant: {final_count}")
    return {"neo4j_papers": len(neo_papers), "qdrant_papers_before": len(qdrant_ids), "qdrant_papers_after": final_count, "added": len(missing_in_qdrant)}


def main():
    pg_dsn = os.environ.get("TAARYA_PG_DSN", "postgresql://taarya:taarya123@localhost:5432/astronomy")
    neo_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo_user = os.environ.get("NEO4J_USER", "neo4j")
    neo_pass = os.environ.get("NEO4J_PASSWORD", "taarya123")
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")

    pg_conn = psycopg2.connect(pg_dsn)
    neo_driver = GraphDatabase.driver(neo_uri, auth=(neo_user, neo_pass))
    qdrant_client = QdrantClient(url=qdrant_url)
    vs = VectorSearch()

    try:
        star_res = reconcile_stars(pg_conn, neo_driver)
        paper_res = reconcile_papers(neo_driver, qdrant_client, vs)
        print("\n=== Store Reconciliation Summary ===")
        print(f"Stars:  Postgres={star_res['postgres_stars']} | Neo4j={star_res['neo4j_stars_after']} (Gap: {abs(star_res['postgres_stars'] - star_res['neo4j_stars_after'])})")
        print(f"Papers: Neo4j={paper_res['neo4j_papers']} | Qdrant={paper_res['qdrant_papers_after']} (Gap: {abs(paper_res['neo4j_papers'] - paper_res['qdrant_papers_after'])})")
    finally:
        pg_conn.close()
        neo_driver.close()


if __name__ == "__main__":
    main()
