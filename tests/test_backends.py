"""Quick test of Qdrant and Neo4j backends."""
import sys

def test_qdrant():
    print("\n=== Testing Qdrant Vector Search ===")
    from src.retrieval.vector_search import VectorSearch
    vs = VectorSearch()
    
    # Create test collection
    vs.ensure_collection("test_col")
    print("Collection created")
    
    # Index
    docs = [
        {"id": 1, "text": "Milky Way disk structure from Gaia DR3", "metadata": {"title": "MW structure"}},
        {"id": 2, "text": "Red giant stars in globular clusters", "metadata": {"title": "Red giants"}},
        {"id": 3, "text": "Gravitational wave transient detection", "metadata": {"title": "GW transients"}},
    ]
    n = vs.index_documents(docs, "test_col")
    print(f"Indexed {n} documents")
    
    # Search
    hits = vs.search_similar("galactic structure", collection="test_col", limit=3)
    print(f"Search found {len(hits)} results:")
    for h in hits:
        print(f"  score={h['score']:.4f} | {h['payload'].get('title')}")
    
    # Cleanup
    from src.database import qdrant_conn
    qdrant_conn.get_client().delete_collection("test_col")
    print("Cleanup done")
    print("✅ Qdrant PASSED")

def test_neo4j():
    print("\n=== Testing Neo4j Graph Search ===")
    from src.retrieval.graph_search import GraphSearch
    gs = GraphSearch()
    
    gs.setup_schema()
    print("Schema created")
    
    gs.create_star_node({"source_id": "T1", "ra": 45.0, "dec": 0.5})
    gs.create_star_node({"source_id": "T2", "ra": 45.1, "dec": 0.6})
    gs.create_paper_node({"arxiv_id": "TP1", "title": "Test Paper"})
    gs.link_star_to_paper("T1", "TP1")
    gs.link_star_to_paper("T2", "TP1")
    print("Nodes + relationships created")
    
    papers = gs.find_star_papers("T1")
    print(f"Star T1 papers: {len(papers)}")
    
    related = gs.find_related_stars("T1", max_hops=2)
    print(f"Related stars: {[r['source_id'] for r in related]}")
    
    stats = gs.get_graph_stats()
    print(f"Graph stats: {stats}")
    
    # Cleanup
    from src.database import neo4j_conn
    with neo4j_conn.session() as s:
        s.run("MATCH (n) WHERE n.source_id IN ['T1','T2'] OR n.arxiv_id='TP1' DETACH DELETE n")
    print("Cleanup done")
    print("✅ Neo4j PASSED")

if __name__ == "__main__":
    failed = 0
    for name, fn in [("Qdrant", test_qdrant), ("Neo4j", test_neo4j)]:
        try:
            fn()
        except Exception as e:
            print(f"❌ {name} FAILED: {e}")
            import traceback; traceback.print_exc()
            failed += 1
    sys.exit(failed)
