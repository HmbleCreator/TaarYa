"""Patch graph_search.py: replace wildcard multi-hop with cluster-only traversal."""
import pathlib, re

path = pathlib.Path(__file__).resolve().parent.parent / "src" / "retrieval" / "graph_search.py"
content = path.read_text(encoding="utf-8")

# Find the old function body between the markers
old_body = re.search(
    r"(        max_hops = min\(max_hops, 3\).*?return \[dict\(record\) for record in result\])",
    content,
    re.DOTALL,
)

if not old_body:
    print("ERROR: Could not find old find_related_stars body")
    raise SystemExit(1)

new_body = (
    '        # Use explicit cluster-membership traversal. The old [*1..N]\n'
    '        # wildcard matched any relationship type and returned thousands\n'
    '        # of unrelated stars, degrading Full Hybrid precision.\n'
    '        query = """\n'
    '        MATCH (s1:Star {source_id: $source_id})-[:MEMBER_OF]->(c:Cluster)<-[:MEMBER_OF]-(s2:Star)\n'
    '        WHERE s1 <> s2\n'
    '        WITH DISTINCT s2, c.name AS cluster_name\n'
    '        RETURN s2.source_id AS source_id, s2.ra AS ra, s2.dec AS dec,\n'
    '               s2.phot_g_mean_mag AS phot_g_mean_mag, cluster_name,\n'
    '               1 AS distance\n'
    '        ORDER BY s2.phot_g_mean_mag\n'
    '        LIMIT $limit\n'
    '        """\n'
    '\n'
    '        with neo4j_conn.session() as session:\n'
    '            result = session.run(query, {"source_id": source_id, "limit": limit})\n'
    '            return [dict(record) for record in result]'
)

content = content[:old_body.start()] + new_body + content[old_body.end():]

# Also update the docstring
content = content.replace(
    "Find stars connected via shared papers or clusters.",
    "Find stars that share a physical cluster with the given star.",
)
content = content.replace(
    "max_hops: Maximum relationship depth (1-3)",
    "max_hops: Ignored (kept for API compat); always 1-hop cluster",
)
content = content.replace(
    "List of related stars with connection path info",
    "List of co-cluster member stars with cluster context",
)

path.write_text(content, encoding="utf-8")
print("OK: graph_search.py patched successfully")
