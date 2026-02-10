"""Tests for the retrieval layer."""
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def test_spatial_search():
    """Test Q3C cone search on ingested Gaia data."""
    from src.retrieval.spatial_search import SpatialSearch
    
    search = SpatialSearch()
    
    # 1. Cone search around the center of our sample data (~RA=45, Dec=0.5)
    print("\n=== Cone Search (RA=45, Dec=0.5, r=1°) ===")
    results = search.cone_search(ra=45.0, dec=0.5, radius_deg=1.0, limit=10)
    print(f"Found {len(results)} stars")
    assert len(results) > 0, "Expected at least 1 star in the region"
    
    for star in results[:3]:
        print(f"  {star['source_id']}: RA={star['ra']:.4f}, Dec={star['dec']:.4f}, "
              f"G={star.get('phot_g_mean_mag', 'N/A')}, dist={star.get('angular_distance', 0):.6f}°")
    
    # 2. Radial search with magnitude filter
    print("\n=== Radial Search (mag <= 18.0) ===")
    bright = search.radial_search(ra=45.0, dec=0.5, radius_deg=1.0, mag_limit=18.0, limit=10)
    print(f"Found {len(bright)} bright stars (G <= 18.0)")
    for star in bright:
        assert star['phot_g_mean_mag'] is None or star['phot_g_mean_mag'] <= 18.0, \
            f"Magnitude filter failed: {star['phot_g_mean_mag']}"
    
    # 3. Coordinate lookup
    if results:
        sid = results[0]["source_id"]
        print(f"\n=== Coordinate Lookup: {sid} ===")
        star = search.coordinate_lookup(sid)
        assert star is not None, f"Star {sid} not found"
        print(f"  RA={star['ra']}, Dec={star['dec']}")
    
    # 4. Nearby stars
    if results:
        sid = results[0]["source_id"]
        print(f"\n=== Nearby Stars for {sid} (r=0.5°) ===")
        neighbors = search.nearby_stars(sid, radius_deg=0.5, limit=5)
        print(f"Found {len(neighbors)} neighbors")
    
    # 5. Count
    count = search.count_in_region(45.0, 0.5, 1.0)
    print(f"\n=== Total stars in region: {count} ===")
    
    print("\n✅ Spatial search tests PASSED")


def test_vector_search():
    """Test Qdrant vector search (collection lifecycle)."""
    from src.retrieval.vector_search import VectorSearch
    
    search = VectorSearch()
    
    # 1. Ensure test collection
    print("\n=== Qdrant: Create Test Collection ===")
    test_collection = "test_retrieval"
    search.ensure_collection(test_collection)
    print("Collection created/verified")
    
    # 2. Index some test documents
    print("\n=== Qdrant: Index Documents ===")
    docs = [
        {
            "id": 1,
            "text": "Gaia DR3 reveals new insights into the structure of the Milky Way disk",
            "metadata": {"arxiv_id": "2301.00001", "title": "Milky Way structure from Gaia"}
        },
        {
            "id": 2,
            "text": "Spectroscopic analysis of red giant stars in globular clusters",
            "metadata": {"arxiv_id": "2301.00002", "title": "Red giants in globular clusters"}
        },
        {
            "id": 3,
            "text": "Transient detection pipeline for gravitational wave follow-up",
            "metadata": {"arxiv_id": "2301.00003", "title": "Gravitational wave transients"}
        },
    ]
    count = search.index_documents(docs, test_collection)
    assert count == 3, f"Expected 3 indexed, got {count}"
    print(f"Indexed {count} documents")
    
    # 3. Semantic search
    print("\n=== Qdrant: Semantic Search ===")
    hits = search.search_similar("structure of our galaxy", collection=test_collection, limit=3)
    print(f"Found {len(hits)} results")
    assert len(hits) > 0, "Expected at least 1 result"
    
    for hit in hits:
        print(f"  Score={hit['score']:.4f} | {hit['payload'].get('title', 'N/A')}")
    
    # Top result should be about Milky Way
    assert hits[0]["payload"]["arxiv_id"] == "2301.00001", \
        f"Expected Milky Way paper first, got {hits[0]['payload']}"
    
    # 4. Collection info
    info = search.get_collection_info(test_collection)
    print(f"\n=== Collection Info: {info} ===")
    
    # 5. Cleanup test collection
    from src.database import qdrant_conn
    qdrant_conn.get_client().delete_collection(test_collection)
    print("Test collection cleaned up")
    
    print("\n✅ Vector search tests PASSED")


def test_graph_search():
    """Test Neo4j graph operations."""
    from src.retrieval.graph_search import GraphSearch
    
    search = GraphSearch()
    
    # 1. Setup schema
    print("\n=== Neo4j: Setup Schema ===")
    search.setup_schema()
    print("Schema initialized")
    
    # 2. Create test nodes
    print("\n=== Neo4j: Create Test Nodes ===")
    search.create_star_node({"source_id": "TEST_STAR_1", "ra": 45.0, "dec": 0.5, "phot_g_mean_mag": 15.0})
    search.create_star_node({"source_id": "TEST_STAR_2", "ra": 45.1, "dec": 0.6, "phot_g_mean_mag": 16.0})
    search.create_paper_node({"arxiv_id": "TEST_PAPER_1", "title": "Test Paper on Stars"})
    search.create_cluster_node("Test_Cluster", ra=45.05, dec=0.55)
    print("Nodes created")
    
    # 3. Create relationships
    print("\n=== Neo4j: Create Relationships ===")
    search.link_star_to_paper("TEST_STAR_1", "TEST_PAPER_1")
    search.link_star_to_paper("TEST_STAR_2", "TEST_PAPER_1")
    search.link_star_to_cluster("TEST_STAR_1", "Test_Cluster")
    search.link_star_to_cluster("TEST_STAR_2", "Test_Cluster")
    print("Relationships created")
    
    # 4. Query papers for a star
    print("\n=== Neo4j: Star → Papers ===")
    papers = search.find_star_papers("TEST_STAR_1")
    print(f"Star TEST_STAR_1 mentioned in {len(papers)} papers")
    assert len(papers) >= 1, "Expected at least 1 paper"
    
    # 5. Related stars via shared paper
    print("\n=== Neo4j: Related Stars ===")
    related = search.find_related_stars("TEST_STAR_1", max_hops=2)
    print(f"Found {len(related)} related stars")
    source_ids = [r["source_id"] for r in related]
    assert "TEST_STAR_2" in source_ids, "Expected TEST_STAR_2 as related"
    
    # 6. Cluster members
    print("\n=== Neo4j: Cluster Members ===")
    members = search.find_cluster_members("Test_Cluster")
    print(f"Cluster has {len(members)} members")
    assert len(members) >= 2, "Expected at least 2 cluster members"
    
    # 7. Graph stats
    stats = search.get_graph_stats()
    print(f"\n=== Graph Stats: {stats} ===")
    
    # 8. Cleanup test data
    from src.database import neo4j_conn
    with neo4j_conn.session() as session:
        session.run("MATCH (n) WHERE n.source_id STARTS WITH 'TEST_' OR n.arxiv_id STARTS WITH 'TEST_' OR n.name = 'Test_Cluster' DETACH DELETE n")
    print("Test data cleaned up")
    
    print("\n✅ Graph search tests PASSED")


def main():
    """Run all retrieval tests."""
    print("=" * 60)
    print("  TaarYa Retrieval Layer Tests")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    tests = [
        ("Spatial Search (PostgreSQL + Q3C)", test_spatial_search),
        ("Vector Search (Qdrant)", test_vector_search),
        ("Graph Search (Neo4j)", test_graph_search),
    ]
    
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            logger.error(f"❌ {name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
