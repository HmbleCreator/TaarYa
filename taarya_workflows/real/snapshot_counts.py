"""
Snapshot of what the databases contain RIGHT NOW, with synthetic fixtures separated from real data.
Every corpus count in the paper (stars, papers, edges, clusters) must come from this file, not from memory or an old run.

  set TAARYA_PG_DSN=...  NEO4J_PASSWORD=...  [NEO4J_URI, NEO4J_USER, QDRANT_URL]
  python -m taarya_workflows.real.snapshot_counts --out results/counts.json [--toi-csv nasa_tois.csv]

UNVERIFIED HERE (no access to your databases): table/label/collection names below are taken from your schema as described in earlier logs
(stars.catalog_source, :Star/:Paper/:Cluster, MEMBER_OF/COVERS/MENTIONED_IN, Qdrant collection 'papers'). Override via arguments if different.
`snapshot()` takes injectable runners so it is unit-tested without databases.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path

PG_BY_SOURCE = "SELECT catalog_source, count(*) FROM stars GROUP BY catalog_source"
NODE_LABELS = ("Star", "Paper", "Cluster", "Alert")
REL_TYPES = ("MEMBER_OF", "COVERS", "MENTIONED_IN", "NEAR_ALERT", "CITES")


def toi_catalog_counts(df) -> dict:
    return dict(total=int(len(df)), planets_cp_kp=int((df.label == 0).sum()), false_positives=int((df.label == 1).sum()),
                unresolved_or_other=int((df.label < 0).sum()))


def snapshot(run_pg, run_neo, qdrant_count, toi_df=None, regions_sql=None) -> dict:
    by = {str(k): int(v) for k, v in run_pg(PG_BY_SOURCE)}
    synth = sum(v for k, v in by.items() if k.upper().startswith("SYNTHETIC"))
    pg = dict(stars_total=sum(by.values()), stars_synthetic=synth, stars_real=sum(by.values()) - synth, by_catalog_source=by)
    if regions_sql: pg["regions"] = int(run_pg(regions_sql)[0][0])
    neo = {f"nodes_{l.lower()}": int(run_neo(f"MATCH (n:{l}) RETURN count(n)")[0][0]) for l in NODE_LABELS}
    neo.update({f"edges_{r.lower()}": int(run_neo(f"MATCH ()-[r:{r}]->() RETURN count(r)")[0][0]) for r in REL_TYPES})
    out = dict(utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), postgres=pg, neo4j=neo, qdrant=dict(papers=int(qdrant_count())))
    if toi_df is not None: out["toi_catalog"] = toi_catalog_counts(toi_df)
    warnings = []
    if synth: warnings.append(f"{synth} synthetic fixture rows are present in stars; exclude them from every reported scientific number")
    if neo["nodes_star"] != pg["stars_total"]: warnings.append(f"Neo4j has {neo['nodes_star']} Star nodes but Postgres has {pg['stars_total']} stars: graph and catalogue are out of sync")
    out["warnings"] = warnings
    return out


def _default_runners(pg_dsn=None):
    import psycopg2
    from neo4j import GraphDatabase
    from qdrant_client import QdrantClient
    dsn = pg_dsn or os.environ["TAARYA_PG_DSN"]

    def run_pg(sql):
        with psycopg2.connect(dsn) as c, c.cursor() as cur: cur.execute(sql); return cur.fetchall()
    drv = GraphDatabase.driver(os.environ.get("NEO4J_URI", "bolt://localhost:7687"), auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]))

    def run_neo(q):
        with drv.session() as s: return [list(r.values()) for r in s.run(q)]
    qc = QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333"))
    return run_pg, run_neo, (lambda: qc.count(collection_name=os.environ.get("QDRANT_COLLECTION", "papers"), exact=True).count)


if __name__ == "__main__":
    import argparse; ap = argparse.ArgumentParser(); ap.add_argument("--out", default="results/counts.json"); ap.add_argument("--toi-csv"); ap.add_argument("--regions-sql")
    a = ap.parse_args(); toi = None
    if a.toi_csv:
        from . import exofop; toi = exofop.normalise(__import__("pandas").read_csv(a.toi_csv))
    snap = snapshot(*_default_runners(), toi_df=toi, regions_sql=a.regions_sql)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(snap, indent=2)); print(json.dumps(snap, indent=2))
