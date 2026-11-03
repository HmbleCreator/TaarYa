# TaarYa System Audit — 2026-04-27

## Scope

This audit reviewed:
- the formal ablation and evaluation pipeline
- spatial, semantic, graph, and hybrid retrieval paths
- PostgreSQL/Qdrant/Neo4j corpus alignment
- graph-ingestion automation and live graph state

## Current Live State

Validated after a manual graph reconciliation inside `taarya-app` on 2026-04-27:

- PostgreSQL stars: `29,798`
- PostgreSQL regions: `13`
- Neo4j stars: `29,798`
- Neo4j papers: `6,464`
- Neo4j clusters: `13`
- Neo4j `MEMBER_OF`: `28,881`
- Neo4j `COVERS`: `191`
- Neo4j `MENTIONED_IN`: `0`

Interpretation:
- corpus drift between PostgreSQL/Qdrant and Neo4j has been corrected for star, paper, and cluster node counts
- graph traversal through paper-to-star links is still effectively unavailable because `MENTIONED_IN` remains zero

## Problems Identified

### 1. Neo4j was not auto-synchronized

Before this fix, Gaia, catalog, and ArXiv ingestion updated PostgreSQL/Qdrant but did not automatically refresh Neo4j. The graph was a manual replica.

### 2. Remaining evaluation circularity

`eval/ablation_formal.py` was improved earlier, but the ground-truth builder still treated high `discovery_score` objects as relevant by default. That is circular because the label comes from the system-side scoring logic being evaluated.

### 3. Graph bottleneck

The full graph reconciliation is still slow and mostly serial:
- star node upserts run one-by-one
- paper node upserts run one-by-one
- star-paper linking falls back to many heuristic/SIMBAD resolution attempts

The manual rebuild completed, but it took several minutes and still produced `0` `MENTIONED_IN` edges.

### 4. Weakest retrieval path

The current bottleneck is not spatial retrieval or paper retrieval. It is the graph enrichment layer for paper→star traversal:
- semantic paper retrieval can return papers
- graph can now hold the paper nodes
- but star mentions are not being resolved into graph edges reliably

## Changes Applied

### Evaluation

- `eval/ablation_formal.py`
  - physical-anomaly relevance is now the default
  - `discovery_score` labels are opt-in only via `--include-discovery-ground-truth`
  - ground-truth cone-search pool was increased so relevant-set construction is less truncated

### Automated graph synchronization

- `src/config.py`
  - added `GRAPH_AUTO_SYNC` flag, default `true`

- `src/ingestion/graph_ingest.py`
  - added `sync_graph_incremental(...)`
  - added targeted star and paper sync helpers
  - full `ingest_graph()` now initializes schema and backend connections itself

- `src/retrieval/graph_search.py`
  - added `replace_star_cluster_links(...)` for safe cluster membership refresh

- `src/ingestion/seed.py`
- `src/ingestion/gaia_ingestor.py`
- `src/ingestion/catalog_ingestor.py`
- `src/ingestion/arxiv_ingest.py`
  - these ingestion paths now trigger Neo4j synchronization after successful writes

- `src/api/ingestion.py`
  - added `POST /api/ingest/graph` for manual full reconciliation
  - ingestion status now reports graph-reconciliation activity

## Verification

Completed locally:

- `python -m py_compile` on all modified code paths
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_eval_metrics.py`
  - `18 passed`
- `python eval/ablation_formal.py --offline`
  - passed

Completed with elevated Docker access:

- `docker exec taarya-app python /app/src/ingestion/graph_ingest.py`
  - succeeded
  - reconciled Neo4j stars, papers, and clusters to current corpus counts

## Remaining Bottlenecks

### High priority

1. Replace heuristic paper→star linking with a more reliable pipeline.
   - current regex + catalog-name extraction is too weak
   - repeated SIMBAD lookups are slow and still fail to attach local stars

2. Batch Neo4j writes.
   - current per-node/per-edge MERGE loops will become a scaling bottleneck

3. Add a confidence threshold or review gate to semantic cluster→paper linking.
   - current top-`k` semantic linking creates `COVERS` edges without a similarity cutoff

### Medium priority

1. Add runtime verification for the new graph auto-sync path.
2. Add a graph-sync regression test or smoke test in Docker.
3. Normalize catalog-source labels across ingest paths where discovery logic depends on exact `GAIA` matching.

## Practical Outcome

The system is in a better state than before this audit:
- node-count drift is fixed
- future ingestion can keep Neo4j updated automatically
- the formal ablation no longer uses circular labels by default

The main unresolved issue is now sharply defined:
- graph-backed paper→star enrichment is still the weakest link and the current bottleneck for improving Full Hybrid retrieval.
